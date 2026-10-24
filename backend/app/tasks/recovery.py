"""Recuperación de tareas: reintento, reasignación, bloqueo por dependencias y qué se puede hacer con una tarea (M49,
Commit 8).

Cuatro cosas distintas que NO se mezclan:

- **Retry**: repetir con el MISMO agente asignado. Intento siguiente, ejecución nueva, misma correlación de misión.
- **Reasignación**: cambiar la asignación vigente (la anterior queda en la auditoría). El intento siguiente usa al
  agente nuevo.
- **Desviación**: ejecuta un agente que NO es el asignado. Se ve (`MISMATCH`) y no cambia la asignación; aceptarla
  como ejecución válida exigiría un override explícito y autorizado que todavía no existe: nada la convierte en otra
  cosa.
- **Bloqueo**: una tarea que no puede arrancar porque lo que necesita falló, está bloqueado o cancelado, o porque su
  agente asignado ya no existe. No se completa «por arrastre» y no se busca otro agente por la capacidad.

Autoridad: el agente informa de su fallo, pide un reintento o sugiere a otro; quien decide es el orquestador o una
persona con permiso (`ApiAction.TASK_RECOVER`). Un agente no se reasigna a sí mismo.

Concurrencia: el reintento y la reasignación bloquean la fila de la tarea (`SELECT … FOR UPDATE`) durante toda la
operación, y el reintento nombra el intento que repite (`after_attempt`). Dos peticiones a la vez se serializan y la
segunda ve otro estado: se rechaza con un conflicto. Nunca hay dos ejecuciones del mismo intento.

El servicio NO hace `commit`: lo hace quien llama (la petición HTTP, o el orquestador al final de la misión).
"""

import datetime
from collections import defaultdict, deque
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.base import AgentResult
from app.agents.manager import AgentManager
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.core.ids import new_correlation_id
from app.db.models.agent_execution_log import AgentExecutionLog
from app.db.models.audit import AuditLog
from app.db.models.project import Project
from app.db.models.task import Task as TaskModel
from app.db.models.task import TaskDependency
from app.fault_injection import ACTOR as FAULT_ACTOR
from app.fault_injection import InjectedFault, drain_expired_audit
from app.memory.service import MemoryService
from app.tasks.assignment import ORCHESTRATOR_CAPABILITIES, AssignmentStatus, ExecutionTrace, TaskAssignmentService
from app.tasks.lifecycle import ensure_transition
from app.tasks.policy import MAX_ATTEMPTS_PER_ASSIGNMENT, MAX_ATTEMPTS_PER_TASK
from app.tasks.schemas import Task as DomainTask
from app.tasks.schemas import TaskStatus

#: Estados desde los que una dependencia impide arrancar a las tareas que dependen de ella.
_BLOCKING_DEPENDENCY_STATUSES = frozenset({TaskStatus.FAILED, TaskStatus.BLOCKED, TaskStatus.CANCELLED})
#: Estados en los que una tarea puede cambiar de agente: ni ejecutándose, ni terminada.
_REASSIGNABLE_STATUSES = frozenset({TaskStatus.FAILED, TaskStatus.BLOCKED, TaskStatus.PENDING})


class RecoveryKind(StrEnum):
    """Qué clase de situación es la de una tarea, para que el CEO distinga sin adivinar."""

    #: Nada que recuperar (completada, cancelada, pendiente o en curso).
    NONE = "none"
    #: Falló y al agente asignado le quedan intentos: se puede reintentar.
    RECOVERABLE = "recoverable"
    #: Falló y el agente asignado ya gastó sus intentos: repetir con él no sirve; hay que reasignar.
    REASSIGN_REQUIRED = "reassign_required"
    #: Falló y la tarea ya gastó el tope de intentos de todos los agentes: ni reintentar ni reasignar lo arreglan.
    DEFINITIVE = "definitive"
    #: El agente asignado ya no está en el registro: no hay fallback por la capacidad.
    UNKNOWN_AGENT = "unknown_agent"
    #: Ejecutó un agente que no es el asignado: una desviación, a la vista.
    MISMATCH = "mismatch"
    #: No puede arrancar: lo que necesita no está completado.
    BLOCKED = "blocked"


@dataclass(frozen=True)
class TaskRecovery:
    kind: RecoveryKind
    can_retry: bool
    attempts_current_assignment: int
    max_attempts_per_assignment: int
    attempts_total: int
    max_attempts_per_task: int
    #: El número que tendría el próximo intento.
    next_attempt: int


def describe_recovery(
    *,
    task_status: str,
    assigned_agent_id: str | None,
    known_agent_ids: Collection[str],
    traces: Sequence[ExecutionTrace],
    relation_status: AssignmentStatus,
) -> TaskRecovery:
    """Qué se puede hacer con una tarea, a partir de su estado, su asignación y sus intentos. Función pura.

Solo cuentan como intentos las ejecuciones del log (`source == "execution_log"`): un rastro histórico de la
    auditoría no es un intento numerado."""
    logged = [trace for trace in traces if trace.source == "execution_log"]
    total = len(logged)
    current = (
        0 if assigned_agent_id is None else sum(1 for trace in logged if trace.assigned_agent_id == assigned_agent_id)
    )
    next_attempt = max((trace.attempt or 0 for trace in logged), default=0) + 1

    if task_status in (TaskStatus.COMPLETED, TaskStatus.CANCELLED):
        kind = RecoveryKind.NONE
    elif assigned_agent_id is not None and assigned_agent_id not in known_agent_ids:
        kind = RecoveryKind.UNKNOWN_AGENT
    elif relation_status is AssignmentStatus.MISMATCH:
        kind = RecoveryKind.MISMATCH
    elif task_status == TaskStatus.FAILED:
        if total == 0:
            kind = RecoveryKind.NONE
        elif total >= MAX_ATTEMPTS_PER_TASK:
            kind = RecoveryKind.DEFINITIVE
        elif current >= MAX_ATTEMPTS_PER_ASSIGNMENT:
            kind = RecoveryKind.REASSIGN_REQUIRED
        else:
            kind = RecoveryKind.RECOVERABLE
    elif task_status == TaskStatus.BLOCKED:
        kind = RecoveryKind.BLOCKED
    else:
        kind = RecoveryKind.NONE
    return TaskRecovery(
        kind=kind,
        can_retry=kind is RecoveryKind.RECOVERABLE,
        attempts_current_assignment=current,
        max_attempts_per_assignment=MAX_ATTEMPTS_PER_ASSIGNMENT,
        attempts_total=total,
        max_attempts_per_task=MAX_ATTEMPTS_PER_TASK,
        next_attempt=next_attempt,
    )


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


class TaskRecoveryService:
    def __init__(self, db: Session, agent_manager: AgentManager) -> None:
        self._db = db
        self._manager = agent_manager
        self._assignments = TaskAssignmentService(db, agent_manager.agent_ids(), agent_manager.capabilities_by_agent())

    # --- reintento explícito ------------------------------------------------------------------------------------------

    def retry(self, task_id: str, *, actor: str, after_attempt: int, reason: str | None = None) -> TaskModel:
        """Repite UNA vez una tarea FAILED con su agente asignado: intento `after_attempt + 1`, ejecución nueva.
        Devuelve la tarea (COMPLETED si el intento acertó, FAILED si no). No reasigna, no cambia de agente y no
        ejecuta a los dependientes."""
        self._assignments.require_authority(actor)
        task = self._lock(task_id)
        # Un fallo de ensayo que caducó sin dispararse (M51A); sin nada armado no hace nada.
        drain_expired_audit(self._db)
        if task.capability in ORCHESTRATOR_CAPABILITIES:
            raise ValidationError(
                f"task {task.name!r} belongs to the orchestrator: it is never retried through an agent"
            )
        if task.status != TaskStatus.FAILED:
            raise ConflictError(f"task {task.id} is {task.status}: only a FAILED task can be retried")
        rows = self._executions(task.id)
        if not rows:
            raise ConflictError(f"task {task.id} has no recorded attempt: there is no failed attempt to retry")
        if rows[-1].success:
            raise ConflictError(f"the last attempt of task {task.id} did not fail: there is nothing to retry")
        last_attempt = max(row.attempt or 0 for row in rows)
        if after_attempt != last_attempt:
            raise ConflictError(
                f"stale retry: the last attempt of task {task.id} is {last_attempt}, not {after_attempt}; "
                "read the task again before retrying"
            )
        assigned = task.assigned_agent_id
        if assigned is None:
            raise ConflictError(f"task {task.id} has no assigned agent: assign or reassign it first")
        if assigned not in self._manager.agent_ids():
            raise ConflictError(
                f"the assigned agent {assigned!r} is unknown to the registry: reassign the task "
                "(there is no fallback by capability)"
            )
        if len(rows) >= MAX_ATTEMPTS_PER_TASK:
            raise ConflictError(
                f"attempt limit reached for task {task.id}: {len(rows)} of {MAX_ATTEMPTS_PER_TASK} attempts used"
            )
        used_by_assigned = sum(1 for row in rows if row.assigned_agent_id == assigned)
        if used_by_assigned >= MAX_ATTEMPTS_PER_ASSIGNMENT:
            raise ConflictError(
                f"agent {assigned!r} used its {used_by_assigned} attempts for task {task.id}: reassign the task"
            )
        if self._parents_not_completed(task):
            raise ConflictError(f"task {task.id} cannot run: a dependency is not completed")
        if not self._manager.is_routable(assigned, task.capability):
            raise ConflictError(
                f"the assigned agent {assigned!r} is not available for {task.capability!r} right now: "
                "retry later or reassign the task"
            )

        correlation_id = rows[-1].correlation_id or new_correlation_id()
        attempt = last_attempt + 1
        self._audit(
            actor,
            "task.retry_requested",
            task,
            before={"status": TaskStatus.FAILED.value},
            after={"after_attempt": after_attempt, "agent_id": assigned, "reason": reason},
            correlation_id=correlation_id,
        )
        self._set_status(task, TaskStatus.PENDING)
        self._start_attempt(task, assigned, attempt, actor=actor, correlation_id=correlation_id)
        self._audit(
            actor,
            "task.retry_started",
            task,
            before=None,
            after={"attempt": attempt, "agent_id": assigned},
            correlation_id=correlation_id,
        )
        self._run_attempt(task, assigned, attempt, correlation_id)
        return task

    def _run_attempt(self, task: TaskModel, agent_id: str, attempt: int, correlation_id: str) -> None:
        project = self._db.get(Project, task.project_id)
        domain = DomainTask(
            id=task.id,
            project_id=task.project_id,
            name=task.name,
            capability=task.capability,
            input=task.input or {},
            retry_count=attempt - 1,
            objective_id=project.objective_id if project is not None else None,
        )
        logged_before = len(self._manager.execution_log)
        error: Exception | None = None
        result: AgentResult | None = None
        try:
            result = self._manager.execute(agent_id, domain)
        except Exception as exc:  # noqa: BLE001 - un fallo del agente es un intento fallido, nunca un error del servicio
            error = exc
        self._record_execution(task, logged_before, attempt, correlation_id)
        if isinstance(error, InjectedFault):
            # Un fallo de ENSAYO (M51A) que se dispara en un reintento explícito: queda en la misma
            # transacción que el intento.
            self._audit(
                FAULT_ACTOR, "fault.fired", task, before=None, after=error.audit_after(), correlation_id=correlation_id
            )
        if error is None and result is not None:
            self._set_status(task, TaskStatus.COMPLETED)
            task.output = result.model_dump()
            task.error = None
            task.completed_at = _now()
            self._audit(
                agent_id,
                "task.completed",
                task,
                before=None,
                after={"recommendation": result.recommendation, "confidence": result.confidence},
                correlation_id=correlation_id,
            )
            if project is not None:
                MemoryService(self._db).remember(
                    scope="objective",
                    scope_id=project.objective_id,
                    key=task.capability,
                    value=result.model_dump(),
                    correlation_id=correlation_id,
                )
            self.unblock_dependents(task, correlation_id)
            return
        self._set_status(task, TaskStatus.FAILED)
        task.error = str(error)
        task.completed_at = _now()
        self.record_failure(task, agent_id, attempt, str(error), correlation_id, announce_failed=True)

    # --- reasignación -------------------------------------------------------------------------------------------------

    def reassign(self, task_id: str, *, agent_id: str, actor: str, reason: str) -> TaskModel:
        """Cambia el agente asignado a una tarea FAILED, BLOCKED o PENDING. No ejecuta nada. El agente tiene que estar
        en el registro y declarar la capacidad de la tarea. La anterior queda en el evento `task.reassigned`."""
        self._assignments.require_authority(actor)
        if not reason or not reason.strip():
            raise ValidationError("a reassignment needs a reason")
        task = self._lock(task_id)
        if task.capability in ORCHESTRATOR_CAPABILITIES:
            raise ValidationError(f"task {task.name!r} belongs to the orchestrator and is never assigned to an agent")
        if task.status not in {status.value for status in _REASSIGNABLE_STATUSES}:
            raise ConflictError(
                f"task {task.id} is {task.status}: it can only be reassigned while FAILED, BLOCKED or PENDING"
            )
        rows = self._executions(task.id)
        correlation_id = rows[-1].correlation_id if rows else new_correlation_id()
        if task.assigned_agent_id is None:
            self._assignments.assign(task, agent_id, actor=actor, reason=reason.strip(), correlation_id=correlation_id)
        else:
            self._assignments.reassign(
                task, agent_id, actor=actor, reason=reason.strip(), correlation_id=correlation_id
            )
        if task.status == TaskStatus.BLOCKED and self._unblockable(task):
            self._set_status(task, TaskStatus.PENDING)
            self._audit(
                actor,
                "task.unblocked",
                task,
                before={"status": TaskStatus.BLOCKED.value},
                after={"reason": "agent_reassigned", "agent_id": agent_id},
                correlation_id=correlation_id,
            )
        return task

    # --- bloqueo y desbloqueo -----------------------------------------------------------------------------------------

    def block_task(self, task: TaskModel, *, reason: str, correlation_id: str, **context: object) -> None:
        """PENDING → BLOCKED con su evento `task.blocked` (motivo: `unknown_agent` o `dependency_not_completed`)."""
        self._set_status(task, TaskStatus.BLOCKED)
        self._audit(
            "ceo",
            "task.blocked",
            task,
            before={"status": TaskStatus.PENDING.value},
            after={"reason": reason, **context},
            correlation_id=correlation_id,
        )

    def block_dependents(self, task: TaskModel, correlation_id: str) -> list[TaskModel]:
        """Bloquea, en cascada, a toda tarea PENDING que dependa (directa o indirectamente) de `task`. No toca a las
        que ya terminaron ni a las que se están ejecutando. Devuelve las que bloqueó."""
        children, parents = self._graph(task.project_id)
        reached: list[str] = []
        queue = deque(children.get(task.id, []))
        seen: set[str] = set()
        while queue:
            current = queue.popleft()
            if current in seen:
                continue
            seen.add(current)
            reached.append(current)
            queue.extend(children.get(current, []))
        blocked: list[TaskModel] = []
        for task_id in reached:
            child = self._db.get(TaskModel, task_id)
            if child is not None and child.status == TaskStatus.PENDING:
                self._set_status(child, TaskStatus.BLOCKED)
                blocked.append(child)
        for child in blocked:
            blockers = [
                parent_id
                for parent_id in parents.get(child.id, [])
                if (parent := self._db.get(TaskModel, parent_id)) is not None
                and parent.status in {status.value for status in _BLOCKING_DEPENDENCY_STATUSES}
            ]
            self._audit(
                "ceo",
                "task.blocked",
                child,
                before={"status": TaskStatus.PENDING.value},
                after={"reason": "dependency_not_completed", "blocked_by": blockers},
                correlation_id=correlation_id,
            )
        return blocked

    def unblock_dependents(self, task: TaskModel, correlation_id: str) -> list[TaskModel]:
        """Tras completarse `task`: las hijas BLOQUEADAS cuyas dependencias ya están todas completadas (y cuyo agente
        sigue siendo válido) vuelven a PENDING. Solo vuelven a poder ejecutarse: no se ejecutan ni se completan por
        arrastre."""
        children, _ = self._graph(task.project_id)
        released: list[TaskModel] = []
        for child_id in children.get(task.id, []):
            child = self._db.get(TaskModel, child_id)
            if child is not None and child.status == TaskStatus.BLOCKED and self._unblockable(child):
                self._set_status(child, TaskStatus.PENDING)
                self._audit(
                    "ceo",
                    "task.unblocked",
                    child,
                    before={"status": TaskStatus.BLOCKED.value},
                    after={"reason": "dependencies_completed", "unblocked_by": task.id},
                    correlation_id=correlation_id,
                )
                released.append(child)
        return released

    def unblock_ready(
        self, project_id: str, correlation_id: str, *, reason: str = "dependencies_completed"
    ) -> list[TaskModel]:
        """Al reanudar una misión: toda tarea BLOQUEADA del proyecto cuyas dependencias ya están completadas (y cuyo
        agente sigue siendo válido) vuelve a PENDING. Las que aún esperan a algo que va a ejecutarse siguen BLOQUEADAS:
        se liberan cuando ese algo se complete (`unblock_dependents`). No ejecuta nada."""
        released: list[TaskModel] = []
        blocked = self._db.scalars(
            select(TaskModel)
            .where(TaskModel.project_id == project_id, TaskModel.status == TaskStatus.BLOCKED.value)
            .order_by(TaskModel.created_at, TaskModel.id)
        ).all()
        for task in blocked:
            if self._unblockable(task):
                self._set_status(task, TaskStatus.PENDING)
                self._audit(
                    "ceo",
                    "task.unblocked",
                    task,
                    before={"status": TaskStatus.BLOCKED.value},
                    after={"reason": reason},
                    correlation_id=correlation_id,
                )
                released.append(task)
        return released

    # --- hechos de un intento (los usa también el orquestador) --------------------------------------------------------

    def start_attempt(self, task: TaskModel, agent_id: str, attempt: int, *, correlation_id: str) -> None:
        """PENDING → RUNNING y el evento `task.execution_started` (quién lo arranca es siempre el orquestador)."""
        self._start_attempt(task, agent_id, attempt, actor="ceo", correlation_id=correlation_id)

    def record_failure(
        self,
        task: TaskModel,
        agent_id: str,
        attempt: int,
        error: str,
        correlation_id: str,
        *,
        announce_failed: bool = False,
    ) -> None:
        """El hecho de que un intento falló: `task.execution_failed`, con el agente que lo ejecutó y el número de
        intento. `announce_failed` añade `task.failed` cuando la tarea queda FAILED (el orquestador ya lo emite él por
        su camino)."""
        self._audit(
            agent_id,
            "task.execution_failed",
            task,
            before=None,
            after={"agent_id": agent_id, "attempt": attempt, "error": error},
            correlation_id=correlation_id,
        )
        if announce_failed:
            self._audit(
                agent_id,
                "task.failed",
                task,
                before=None,
                after={"error": error, "attempt": attempt},
                correlation_id=correlation_id,
            )

    # --- interno ------------------------------------------------------------------------------------------------------

    def _lock(self, task_id: str) -> TaskModel:
        task = self._db.execute(
            select(TaskModel).where(TaskModel.id == task_id).with_for_update().execution_options(populate_existing=True)
        ).scalar_one_or_none()
        if task is None:
            raise NotFoundError(f"task {task_id} not found")
        return task

    def _executions(self, task_id: str) -> list[AgentExecutionLog]:
        return list(
            self._db.scalars(
                select(AgentExecutionLog)
                .where(AgentExecutionLog.task_id == task_id)
                .order_by(AgentExecutionLog.attempt, AgentExecutionLog.created_at)
            ).all()
        )

    def _set_status(self, task: TaskModel, new: TaskStatus) -> None:
        task.status = ensure_transition(task.status, new).value

    def _start_attempt(self, task: TaskModel, agent_id: str, attempt: int, *, actor: str, correlation_id: str) -> None:
        self._set_status(task, TaskStatus.RUNNING)
        task.started_at = _now()
        task.completed_at = None
        self._audit(
            actor,
            "task.execution_started",
            task,
            before=None,
            after={"agent_id": agent_id, "attempt": attempt},
            correlation_id=correlation_id,
        )

    def _record_execution(self, task: TaskModel, logged_before: int, attempt: int, correlation_id: str) -> None:
        log = self._manager.execution_log
        if len(log) <= logged_before:
            return  # la llamada no llegó a ejecutar nada: no se reutiliza la entrada de otra ejecución
        entry = log[-1]
        self._assignments.record_execution(
            task,
            executing_agent_id=entry["agent_id"],
            success=entry["success"],
            duration_ms=entry["duration_ms"],
            started_at=entry.get("started_at"),
            completed_at=entry.get("completed_at"),
            attempt=attempt,
            correlation_id=correlation_id,
        )

    def _graph(self, project_id: str) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
        children: dict[str, list[str]] = defaultdict(list)
        parents: dict[str, list[str]] = defaultdict(list)
        edges = self._db.execute(
            select(TaskDependency.parent_task_id, TaskDependency.child_task_id)
            .join(TaskModel, TaskModel.id == TaskDependency.child_task_id)
            .where(TaskModel.project_id == project_id)
        ).all()
        for parent_id, child_id in edges:
            children[parent_id].append(child_id)
            parents[child_id].append(parent_id)
        return children, parents

    def _parents_not_completed(self, task: TaskModel) -> list[str]:
        _, parents = self._graph(task.project_id)
        return [
            parent_id
            for parent_id in parents.get(task.id, [])
            if (parent := self._db.get(TaskModel, parent_id)) is None or parent.status != TaskStatus.COMPLETED
        ]

    def _unblockable(self, task: TaskModel) -> bool:
        """¿Puede una tarea BLOQUEADA volver a PENDING? Dependencias completadas y agente ausente o conocido."""
        if self._parents_not_completed(task):
            return False
        assigned = task.assigned_agent_id
        return assigned is None or assigned in self._manager.agent_ids()

    def _audit(
        self, actor: str, action: str, task: TaskModel, *, before: dict | None, after: dict, correlation_id: str
    ) -> None:
        self._db.add(
            AuditLog(
                actor=actor,
                action=action,
                resource=f"task:{task.id}",
                before=before,
                after=after,
                correlation_id=correlation_id,
            )
        )
        self._db.flush()
