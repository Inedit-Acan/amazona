"""Estado de una misión y versión de sus decisiones (M50, Commit 9).

Una MISIÓN es un objetivo con su proyecto, sus tareas y sus decisiones. Aquí se responde, sin ejecutar nada, a «¿en qué
punto está?»:

- **Completa**: la tarea de síntesis está COMPLETED. Solo se completa cuando las cuatro especialistas lo estaban, así
  que es una sola señal y no hace falta interpretar el texto de ninguna decisión.
- **Incompleta**, que se reparte en dos:
  - **Lista para reanudar**: lo que falta está PENDING, o BLOQUEADO solo por algo que aún se va a ejecutar. Nada
    atascado.
  - **Recuperación pendiente**: hay algo atascado que alguien con autoridad tiene que resolver ANTES (una tarea
    FAILED, un agente que el registro ya no conoce, una desviación sin resolver, ningún agente disponible). Reanudar
    no reintenta ni reasigna: eso es de `TaskRecoveryService` (Commit 8).
- **Reanudándose** (una tarea RUNNING), **Cancelada** e **Inconsistente** (al plan le falta una tarea requerida) no se
  reanudan.

Las decisiones de un proyecto se ORDENAN por `(created_at, id)`: la última es la vigente y la versión es su
posición. No hay columna de versión (no hace falta migración): cada reanudación escribe una decisión nueva, nunca
actualiza la anterior.

Este módulo no hace `commit` y no escribe: lee.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.manager import AgentManager
from app.core.errors import ConflictError, NoAgentAvailableError, NotFoundError
from app.db.models.decision import Decision
from app.db.models.objective import Objective
from app.db.models.project import Project
from app.db.models.task import Task as TaskModel
from app.tasks.assignment import ORCHESTRATOR_CAPABILITIES, load_relations
from app.tasks.recovery import RecoveryKind, describe_recovery
from app.tasks.schemas import TaskStatus

#: Las tareas del plan, en su orden. La síntesis es la última y la que cierra la misión.
PLAN_ORDER: tuple[str, ...] = (
    "product_validation",
    "supplier_sourcing",
    "legal_validation",
    "finance_validation",
    "decision_synthesis",
)
SYNTHESIS = "decision_synthesis"

#: Estados de proyecto/objetivo que cierran una misión.
_CANCELLED_STATUSES = frozenset({"CANCELLED"})


class MissionState(StrEnum):
    COMPLETE = "complete"
    READY_TO_RESUME = "ready_to_resume"
    RECOVERY_PENDING = "recovery_pending"
    RESUMING = "resuming"
    CANCELLED = "cancelled"
    INCONSISTENT = "inconsistent"


class BlockerReason(StrEnum):
    FAILED_RECOVERABLE = "failed_recoverable"
    FAILED_REASSIGN_REQUIRED = "failed_reassign_required"
    FAILED_DEFINITIVE = "failed_definitive"
    UNKNOWN_AGENT = "unknown_agent"
    MISMATCH = "mismatch"
    NO_AGENT_AVAILABLE = "no_agent_available"
    RUNNING = "running"


@dataclass(frozen=True)
class TaskFact:
    """Lo que hace falta saber de una tarea para clasificar la misión (todo ya calculado: la función es pura)."""

    id: str
    name: str
    capability: str
    status: str
    assigned_agent_id: str | None
    #: El agente asignado (si lo hay) está en el registro.
    agent_known: bool
    #: Puede ejecutarse ahora: el asignado sigue disponible, o el registro elige otro por la capacidad.
    agent_available: bool
    #: `RecoveryKind` de la tarea, en texto.
    recovery_kind: str


@dataclass(frozen=True)
class Blocker:
    task_id: str
    task_name: str
    reason: BlockerReason

    def as_audit(self) -> dict[str, str]:
        return {"task": self.task_name, "reason": self.reason.value}


@dataclass(frozen=True)
class MissionView:
    state: MissionState
    #: Más de una decisión en el proyecto: la misión se reanudó al menos una vez.
    resumed: bool
    blockers: tuple[Blocker, ...]
    #: Las tareas que aún no están COMPLETED, en el orden del plan.
    pending_tasks: tuple[str, ...]
    completed_tasks: tuple[str, ...]
    current_decision_id: str | None
    decisions: int

    @property
    def resumable(self) -> bool:
        return self.state is MissionState.READY_TO_RESUME


def _blocker_for(task: TaskFact) -> BlockerReason | None:
    if task.status == TaskStatus.RUNNING:
        return BlockerReason.RUNNING
    if not task.agent_known or task.recovery_kind == RecoveryKind.UNKNOWN_AGENT:
        return BlockerReason.UNKNOWN_AGENT
    if task.recovery_kind == RecoveryKind.MISMATCH:
        return BlockerReason.MISMATCH
    if task.status == TaskStatus.FAILED:
        if task.recovery_kind == RecoveryKind.DEFINITIVE:
            return BlockerReason.FAILED_DEFINITIVE
        if task.recovery_kind == RecoveryKind.REASSIGN_REQUIRED:
            return BlockerReason.FAILED_REASSIGN_REQUIRED
        return BlockerReason.FAILED_RECOVERABLE
    if task.status in (TaskStatus.PENDING, TaskStatus.BLOCKED) and not task.agent_available:
        return BlockerReason.NO_AGENT_AVAILABLE
    return None


def describe_mission(tasks: Sequence[TaskFact], *, decision_ids: Sequence[str], cancelled: bool = False) -> MissionView:
    """Clasifica una misión a partir de sus tareas. Función pura: el orden de precedencia es el de este código."""
    by_name = {task.name: task for task in tasks}
    ordered = [by_name[name] for name in PLAN_ORDER if name in by_name]
    current = decision_ids[-1] if decision_ids else None
    pending = tuple(task.name for task in ordered if task.status != TaskStatus.COMPLETED)
    completed = tuple(task.name for task in ordered if task.status == TaskStatus.COMPLETED)

    def view(state: MissionState, blockers: tuple[Blocker, ...] = ()) -> MissionView:
        return MissionView(
            state=state,
            resumed=len(decision_ids) > 1,
            blockers=blockers,
            pending_tasks=pending,
            completed_tasks=completed,
            current_decision_id=current,
            decisions=len(decision_ids),
        )

    if len(tasks) != len(PLAN_ORDER) or len(by_name) != len(PLAN_ORDER) or set(by_name) != set(PLAN_ORDER):
        return view(MissionState.INCONSISTENT)
    if cancelled or any(task.status == TaskStatus.CANCELLED for task in ordered):
        return view(MissionState.CANCELLED)
    if by_name[SYNTHESIS].status == TaskStatus.COMPLETED:
        return view(MissionState.COMPLETE)

    blockers: list[Blocker] = []
    for task in ordered:
        if task.status == TaskStatus.COMPLETED:
            continue
        reason = _blocker_for(task)
        if reason is not None:
            blockers.append(Blocker(task.id, task.name, reason))
    if any(blocker.reason is BlockerReason.RUNNING for blocker in blockers):
        return view(MissionState.RESUMING, tuple(blockers))
    if blockers:
        return view(MissionState.RECOVERY_PENDING, tuple(blockers))
    return view(MissionState.READY_TO_RESUME)


# --- lectura de la base de datos ------------------------------------------------------------------------------------


def ordered_decisions(db: Session, project_id: str) -> list[Decision]:
    """Las decisiones del proyecto, de la más antigua a la vigente. Siempre las filas de ahora (no las del mapa de
    identidad): quien lee tras esperar un bloqueo tiene que ver lo que el otro confirmó."""
    return list(
        db.scalars(
            select(Decision)
            .where(Decision.project_id == project_id)
            .order_by(Decision.created_at, Decision.id)
            .execution_options(populate_existing=True)
        ).all()
    )


@dataclass(frozen=True)
class DecisionVersion:
    version: int
    is_current: bool
    supersedes_decision_id: str | None


def decision_versions(decisions: Sequence[Decision]) -> dict[str, DecisionVersion]:
    return {
        decision.id: DecisionVersion(
            version=index + 1,
            is_current=index == len(decisions) - 1,
            supersedes_decision_id=decisions[index - 1].id if index else None,
        )
        for index, decision in enumerate(decisions)
    }


def _can_execute(manager: AgentManager, task: TaskModel) -> bool:
    """¿Puede ejecutarse esta tarea ahora? Las del orquestador sí. Una de agente, si el asignado sigue disponible o el
    registro elige a otro por la capacidad (lo mismo que hará el orquestador al ejecutarla)."""
    if task.capability in ORCHESTRATOR_CAPABILITIES:
        return True
    if task.assigned_agent_id is not None and manager.is_routable(task.assigned_agent_id, task.capability):
        return True
    try:
        manager.select_agent(task.capability)
    except NoAgentAvailableError:
        return False
    return True


def load_mission(db: Session, manager: AgentManager, project_id: str) -> MissionView:
    project = db.get(Project, project_id)
    if project is None:
        raise NotFoundError(f"project {project_id} not found")
    objective = db.get(Objective, project.objective_id)
    tasks = list(
        db.scalars(
            select(TaskModel).where(TaskModel.project_id == project_id).execution_options(populate_existing=True)
        ).all()
    )
    known = manager.agent_ids()
    relations = load_relations(db, tasks, known)
    facts = []
    for task in tasks:
        relation = relations[task.id]
        recovery = describe_recovery(
            task_status=task.status,
            assigned_agent_id=task.assigned_agent_id,
            known_agent_ids=known,
            traces=relation.executions,
            relation_status=relation.status,
        )
        facts.append(
            TaskFact(
                id=task.id,
                name=task.name,
                capability=task.capability,
                status=task.status,
                assigned_agent_id=task.assigned_agent_id,
                agent_known=task.assigned_agent_id is None or task.assigned_agent_id in known,
                agent_available=_can_execute(manager, task),
                recovery_kind=recovery.kind.value,
            )
        )
    cancelled = project.status in _CANCELLED_STATUSES or (
        objective is not None and objective.status in _CANCELLED_STATUSES
    )
    decisions = ordered_decisions(db, project_id)
    return describe_mission(facts, decision_ids=[d.id for d in decisions], cancelled=cancelled)


def resolve_project_id(db: Session, objective_id: str, project_id: str | None) -> str:
    """El proyecto que se reanuda: el que el cliente nombra (tiene que ser del objetivo) o, si no nombra ninguno, el
    ÚNICO que tiene el objetivo. Con dos o más no se adivina cuál."""
    if db.get(Objective, objective_id) is None:
        raise NotFoundError(f"objective {objective_id} not found")
    projects = list(db.scalars(select(Project).where(Project.objective_id == objective_id)).all())
    if project_id is not None:
        if all(project.id != project_id for project in projects):
            raise NotFoundError(f"project {project_id} does not belong to objective {objective_id}")
        return project_id
    if not projects:
        raise ConflictError(f"objective {objective_id} has never been run: there is no mission to resume")
    if len(projects) > 1:
        raise ConflictError(
            f"objective {objective_id} has {len(projects)} projects: name the one to resume with project_id"
        )
    return projects[0].id
