"""La relación TAREA ↔ AGENTE (M48, Commit 7): asignación, ejecución y lo que pasó entre una y otra.

ASIGNACIÓN ≠ EJECUCIÓN. Una tarea puede estar sin asignar, asignada y sin ejecutar, ejecutada por el agente asignado,
ejecutada por otro o ser del orquestador, y esos casos no se funden en un campo ambiguo. Aquí viven las tres piezas
de esa relación:

- **Dónde está cada cosa.** La asignación VIGENTE es `tasks.assigned_agent_id`. Cada ejecución es una fila de
  `agent_execution_log` con su `task_id`, la FOTO de la asignación de ese momento, el intento y las horas. Lo que
  ocurrió en medio (asignar, reasignar, ejecutar con otro agente) está en el `audit_log`, que solo se añade:
  `task.assigned`, `task.reassigned`, `task.executed_by_other_agent`.
- **Quién existe.** El REGISTRO de agentes (`AgentRegistry`), en el código. La tabla `agents` no lo es (no se
  puebla). Un id que el registro no conoce no se puede asignar, y si aparece en un dato ya guardado sale como
  «agente desconocido», nunca como disponible ni como sin asignar.
- **Qué NO se hace jamás:** inferir el agente de la capacidad, del nombre de la tarea, del orden o de la
  correlación. Una tarea sin asignación y sin ejecución propia dice «sin asignar», aunque exista un agente para su
  capacidad.

`decision_synthesis` es del ORQUESTADOR (el CEO la resuelve él mismo en `CEOOrchestrator._execute_tasks`, sin agente,
sin ejecución y sin evento de auditoría): no se asigna a ningún agente y se lee como `ORCHESTRATOR`, no como «sin
asignar».

Lo anterior a este commit (las misiones de octubre) no tiene asignación ni `task_id` en el log. Se lee desde su
evento `task.completed` (actor = el agente, recurso = la tarea: un vínculo explícito de la auditoría) y se rotula
«ejecutada · sin asignación registrada». No se escribe nada a posteriori: una asignación que nunca se hizo no se
fabrica.
"""

import datetime
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AuthorityError, ValidationError
from app.db.models.agent_execution_log import AgentExecutionLog
from app.db.models.audit import AuditLog
from app.db.models.task import Task as TaskModel

#: Las capacidades que resuelve el orquestador y NO un agente. Es la misma que el orquestador comprueba antes de
#: ejecutar: una sola definición. Una tarea de estas no se asigna a ningún agente.
ORCHESTRATOR_CAPABILITIES: frozenset[str] = frozenset({"decision_synthesis"})

ACTION_ASSIGNED = "task.assigned"
ACTION_REASSIGNED = "task.reassigned"
ACTION_OTHER_AGENT = "task.executed_by_other_agent"

#: Los eventos que la auditoría ya guardaba de la ejecución de una tarea (actor = agente, recurso = `task:<id>`).
_LEGACY_EXECUTION_ACTIONS = {"task.completed": True, "task.failed": False, "task.retried": False}


class AssignmentStatus(StrEnum):
    """La relación de una tarea con su agente, en una palabra. Ninguno de los casos se funde con otro."""

    #: La resuelve el orquestador, no un agente (`decision_synthesis`).
    ORCHESTRATOR = "ORCHESTRATOR"
    #: Tarea de agente sin asignación y sin ejecución.
    UNASSIGNED = "UNASSIGNED"
    #: Asignada a un agente que existe y todavía sin ejecutar.
    ASSIGNED = "ASSIGNED"
    #: La última ejecución fue del agente asignado.
    MATCH = "MATCH"
    #: La última ejecución fue de un agente DISTINTO del asignado: una desviación, a la vista.
    MISMATCH = "MISMATCH"
    #: Ejecutada por un agente sin ninguna asignación registrada (lo anterior a este commit).
    EXECUTED_UNASSIGNED = "EXECUTED_UNASSIGNED"
    #: El agente asignado (o el que ejecutó) no está en el registro.
    UNKNOWN_AGENT = "UNKNOWN_AGENT"
    #: Los datos no cuadran: una tarea completada sin rastro de ejecución, o una del orquestador con un agente.
    INCONSISTENT = "INCONSISTENT"


@dataclass(frozen=True)
class ExecutionTrace:
    """Un rastro de que un agente ejecutó una tarea. `source` dice de dónde sale: el log de ejecuciones (con
    `task_id`) o, en lo anterior a este commit, el evento de auditoría de la tarea."""

    source: Literal["execution_log", "audit"]
    agent_id: str
    success: bool | None
    attempt: int | None
    execution_id: str | None
    assigned_agent_id: str | None
    started_at: datetime.datetime | None
    completed_at: datetime.datetime | None
    created_at: datetime.datetime


@dataclass(frozen=True)
class TaskAgentRelation:
    status: AssignmentStatus
    assigned_agent_id: str | None
    #: `None` si no hay asignación; `False` si el agente asignado no está en el registro.
    assigned_agent_known: bool | None
    #: El agente de la última ejecución, si la hay.
    executed_by_agent_id: str | None
    #: Todas las ejecuciones, de la primera a la última. Un reintento no borra la anterior.
    executions: tuple[ExecutionTrace, ...]
    #: Hubo al menos una reasignación (`task.reassigned` en la auditoría).
    reassigned: bool


def describe_relation(
    *,
    capability: str,
    task_status: str,
    assigned_agent_id: str | None,
    traces: Sequence[ExecutionTrace],
    known_agent_ids: Collection[str],
    reassigned: bool = False,
) -> TaskAgentRelation:
    """La relación de UNA tarea, a partir de lo que consta (asignación, rastros de ejecución) y de qué agentes existen.
    Función pura."""
    ordered = tuple(sorted(traces, key=lambda item: (item.created_at, item.attempt or 0)))
    latest = ordered[-1] if ordered else None
    assigned_known = None if assigned_agent_id is None else assigned_agent_id in known_agent_ids

    def result(status: AssignmentStatus) -> TaskAgentRelation:
        return TaskAgentRelation(
            status=status,
            assigned_agent_id=assigned_agent_id,
            assigned_agent_known=assigned_known,
            executed_by_agent_id=latest.agent_id if latest is not None else None,
            executions=ordered,
            reassigned=reassigned,
        )

    if capability in ORCHESTRATOR_CAPABILITIES:
        # Del orquestador: ni asignación ni ejecución de un agente. Si las hay, algo ha tocado lo que no debía.
        return result(
            AssignmentStatus.INCONSISTENT if assigned_agent_id is not None or ordered else AssignmentStatus.ORCHESTRATOR
        )
    if assigned_known is False:
        return result(AssignmentStatus.UNKNOWN_AGENT)
    if latest is None:
        if task_status == "COMPLETED":
            return result(AssignmentStatus.INCONSISTENT)  # completada y sin rastro de quién la ejecutó
        return result(AssignmentStatus.UNASSIGNED if assigned_agent_id is None else AssignmentStatus.ASSIGNED)
    # Una ejecución del log lleva la FOTO de la asignación de su momento (M48): lo que se compara es quién
    # ejecutó con quién debía ejecutar ENTONCES. Así una reasignación posterior (tras un fallo) no convierte el
    # intento anterior en una desviación, y una desviación de verdad no desaparece porque luego se reasigne a
    # quien la cometió.
    snapshot = latest.assigned_agent_id if latest.source == "execution_log" else None
    if snapshot is not None:
        if latest.agent_id != snapshot:
            unknown = latest.agent_id not in known_agent_ids
            return result(AssignmentStatus.UNKNOWN_AGENT if unknown else AssignmentStatus.MISMATCH)
        if snapshot != assigned_agent_id:
            # reasignada desde esa ejecución: espera un intento del agente nuevo
            return result(AssignmentStatus.ASSIGNED)
        return result(AssignmentStatus.MATCH)
    if latest.agent_id not in known_agent_ids:
        return result(AssignmentStatus.UNKNOWN_AGENT)
    if assigned_agent_id is None:
        return result(AssignmentStatus.EXECUTED_UNASSIGNED)
    return result(AssignmentStatus.MATCH if latest.agent_id == assigned_agent_id else AssignmentStatus.MISMATCH)


@dataclass(frozen=True)
class AssignmentEvent:
    """Un paso de la historia de asignaciones de una tarea, tal como lo guardó la auditoría."""

    kind: Literal["assigned", "reassigned"]
    agent_id: str
    before_agent_id: str | None
    reason: str | None
    actor: str
    correlation_id: str
    created_at: datetime.datetime


class TaskAssignmentService:
    """Asigna, reasigna y registra ejecuciones de tareas. Todo cambio de asignación deja su evento de auditoría en la
    MISMA transacción, y ninguno borra lo anterior. No hace `commit`: lo hace quien llama (el orquestador)."""

    def __init__(
        self,
        db: Session,
        known_agent_ids: Collection[str],
        capabilities_by_agent: Mapping[str, Collection[str]] | None = None,
    ) -> None:
        self._db = db
        self._known = frozenset(known_agent_ids)
        #: Si se da, una asignación solo es válida para un agente que declara la capacidad de la tarea (M49, Commit 8).
        self._capabilities = (
            None if capabilities_by_agent is None else {k: frozenset(v) for k, v in capabilities_by_agent.items()}
        )

    # --- asignar ------------------------------------------------------------------------------------------------------

    def assign(self, task: TaskModel, agent_id: str, *, actor: str, reason: str, correlation_id: str) -> bool:
        """Asigna `agent_id` a una tarea sin asignar. Devuelve `False` (y no escribe nada) si ya tenía ESE agente.
        Con otro agente asignado hay que reasignar. Un agente que el registro no conoce, y una tarea del orquestador,
        se rechazan."""
        self.require_authority(actor)
        self._check_assignable(task, agent_id)
        if task.assigned_agent_id == agent_id:
            return False
        if task.assigned_agent_id is not None:
            raise ValidationError(
                f"task {task.id} is already assigned to {task.assigned_agent_id}: "
                "a different agent needs reassign, not assign"
            )
        task.assigned_agent_id = agent_id
        self._audit(
            task,
            ACTION_ASSIGNED,
            actor=actor,
            before=None,
            after={"agent_id": agent_id, "reason": reason},
            correlation_id=correlation_id,
        )
        return True

    def reassign(self, task: TaskModel, agent_id: str, *, actor: str, reason: str, correlation_id: str) -> None:
        """Cambia el agente de una tarea YA asignada. La asignación anterior queda en el evento (`before`)."""
        self.require_authority(actor)
        self._check_assignable(task, agent_id)
        if task.assigned_agent_id is None:
            raise ValidationError(f"task {task.id} is not assigned: assign it first, there is nothing to reassign")
        if task.assigned_agent_id == agent_id:
            raise ValidationError(
                f"task {task.id} is already assigned to {agent_id}: reassigning to the same agent changes nothing"
            )
        previous = task.assigned_agent_id
        task.assigned_agent_id = agent_id
        self._audit(
            task,
            ACTION_REASSIGNED,
            actor=actor,
            before={"agent_id": previous},
            after={"agent_id": agent_id, "reason": reason},
            correlation_id=correlation_id,
        )

    def history(self, task_id: str) -> list[AssignmentEvent]:
        rows = self._db.scalars(
            select(AuditLog)
            .where(AuditLog.resource == f"task:{task_id}", AuditLog.action.in_([ACTION_ASSIGNED, ACTION_REASSIGNED]))
            .order_by(AuditLog.created_at)
        ).all()
        return [
            AssignmentEvent(
                kind="reassigned" if row.action == ACTION_REASSIGNED else "assigned",
                agent_id=(row.after or {}).get("agent_id", ""),
                before_agent_id=(row.before or {}).get("agent_id"),
                reason=(row.after or {}).get("reason"),
                actor=row.actor,
                correlation_id=row.correlation_id,
                created_at=row.created_at,
            )
            for row in rows
        ]

    # --- ejecutar -----------------------------------------------------------------------------------------------------

    def record_execution(
        self,
        task: TaskModel,
        *,
        executing_agent_id: str,
        success: bool,
        duration_ms: float,
        started_at: datetime.datetime | None,
        completed_at: datetime.datetime | None,
        attempt: int,
        correlation_id: str,
    ) -> AgentExecutionLog:
        """Registra una ejecución de `task` por `executing_agent_id`: UNA FILA NUEVA con la tarea, la foto de la
        asignación vigente, el intento y las horas. Nunca sobrescribe una anterior (un reintento es otra fila). Si
        quien ejecuta no es el asignado (o no hay asignado), la desviación queda en la auditoría: no se oculta y no
        se corrige la asignación."""
        if task.id is None or self._db.get(TaskModel, task.id) is None:
            raise ValidationError("an execution needs a task that exists: the task is not in the database")
        row = AgentExecutionLog(
            agent_id=executing_agent_id,
            capability=task.capability,
            duration_ms=duration_ms,
            success=success,
            correlation_id=correlation_id,
            task_id=task.id,
            assigned_agent_id=task.assigned_agent_id,
            attempt=attempt,
            started_at=started_at,
            completed_at=completed_at,
        )
        self._db.add(row)
        self._db.flush()
        if task.assigned_agent_id != executing_agent_id:
            self._audit(
                task,
                ACTION_OTHER_AGENT,
                actor=executing_agent_id,
                before={"assigned_agent_id": task.assigned_agent_id},
                after={"executing_agent_id": executing_agent_id, "execution_id": row.id, "attempt": attempt},
                correlation_id=correlation_id,
            )
        return row

    # --- interno ------------------------------------------------------------------------------------------------------

    def require_authority(self, actor: str) -> None:
        """Asignar y reasignar es del orquestador o de una persona con permiso, nunca de un agente: un agente informa
        de su fallo, pide un reintento o sugiere a otro, pero no decide su propia asignación (ni la de un compañero)."""
        if not actor or not actor.strip():
            raise AuthorityError("an assignment needs an actor: who decided it")
        if actor in self._known:
            raise AuthorityError(
                f"agent {actor!r} cannot assign or reassign tasks: that decision belongs to the orchestrator"
            )

    def _check_assignable(self, task: TaskModel, agent_id: str) -> None:
        if task.capability in ORCHESTRATOR_CAPABILITIES:
            raise ValidationError(
                f"task {task.name!r} ({task.capability}) belongs to the orchestrator and is never assigned to an agent"
            )
        if agent_id not in self._known:
            raise ValidationError(
                f"agent {agent_id!r} is not in the agent registry: a task cannot be assigned to an unknown agent"
            )
        if self._capabilities is not None and task.capability not in self._capabilities.get(agent_id, frozenset()):
            raise ValidationError(
                f"agent {agent_id!r} does not have the capability {task.capability!r}: it cannot be assigned this task"
            )

    def _audit(
        self, task: TaskModel, action: str, *, actor: str, before: dict | None, after: dict, correlation_id: str
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


def load_relations(
    db: Session, tasks: Sequence[TaskModel], known_agent_ids: Collection[str]
) -> dict[str, TaskAgentRelation]:
    """La relación de cada tarea, leída de lo persistido (solo lee). Dos fuentes de ejecuciones, sin mezclarlas ni
    contarlas dos veces:

    1. `agent_execution_log` con `task_id` (lo explícito, desde este commit);
    2. SOLO para una tarea que no tiene ninguna fila vinculada: sus eventos `task.completed|failed|retried` de la
       auditoría (actor = agente, recurso = esa tarea). Una fila del log sin `task_id` NO se vincula a nada, ni
       siquiera si coincide el agente y la capacidad.
    """
    if not tasks:
        return {}
    ids = [task.id for task in tasks]
    resources = [f"task:{task_id}" for task_id in ids]

    linked: dict[str, list[ExecutionTrace]] = {}
    for row in db.scalars(select(AgentExecutionLog).where(AgentExecutionLog.task_id.in_(ids))).all():
        linked.setdefault(row.task_id or "", []).append(
            ExecutionTrace(
                source="execution_log",
                agent_id=row.agent_id,
                success=row.success,
                attempt=row.attempt,
                execution_id=row.id,
                assigned_agent_id=row.assigned_agent_id,
                started_at=row.started_at,
                completed_at=row.completed_at,
                created_at=row.created_at,
            )
        )

    legacy: dict[str, list[ExecutionTrace]] = {}
    reassigned: set[str] = set()
    for event in db.scalars(
        select(AuditLog).where(AuditLog.resource.in_(resources)).order_by(AuditLog.created_at)
    ).all():
        task_id = event.resource.removeprefix("task:")
        if event.action == ACTION_REASSIGNED:
            reassigned.add(task_id)
        elif event.action in _LEGACY_EXECUTION_ACTIONS:
            legacy.setdefault(task_id, []).append(
                ExecutionTrace(
                    source="audit",
                    agent_id=event.actor,
                    success=_LEGACY_EXECUTION_ACTIONS[event.action],
                    attempt=None,
                    execution_id=None,
                    assigned_agent_id=None,
                    started_at=None,
                    completed_at=None,
                    created_at=event.created_at,
                )
            )

    return {
        task.id: describe_relation(
            capability=task.capability,
            task_status=task.status,
            assigned_agent_id=task.assigned_agent_id,
            traces=linked.get(task.id) or legacy.get(task.id, []),
            known_agent_ids=known_agent_ids,
            reassigned=task.id in reassigned,
        )
        for task in tasks
    }
