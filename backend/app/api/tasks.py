import datetime

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.agents.manager import AgentManager
from app.agents.registry import build_default_agent_manager
from app.auth.actor import Actor
from app.auth.dependencies import authorize
from app.core.config import Settings, get_settings
from app.core.errors import NotFoundError
from app.db.models.task import Task as TaskModel
from app.db.models.task import TaskDependency as TaskDependencyModel
from app.db.session import get_db
from app.idempotency.service import IdempotencyKeyHeader, run_idempotent
from app.permissions.policies import ApiAction
from app.tasks.assignment import TaskAgentRelation, load_relations
from app.tasks.recovery import TaskRecovery, TaskRecoveryService, describe_recovery

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


def get_agent_manager() -> AgentManager:
    """El registro y el manager de agentes del sistema. Una dependencia para que las pruebas puedan sustituirlos; la
    lectura de la relación tarea ↔ agente y las operaciones de recuperación usan el MISMO registro."""
    return build_default_agent_manager()[1]


class ExecutionTraceOut(BaseModel):
    # : De dónde sale: `execution_log` (con `task_id`, lo explícito) o `audit` (el evento `task.completed` de una
    # misión anterior).
    source: str
    execution_id: str | None
    agent_id: str
    #: `False` = el registro de agentes no conoce a este agente.
    agent_known: bool
    success: bool | None
    attempt: int | None
    #: La asignación vigente cuando se ejecutó (la foto). `None` = no había, o es una ejecución anterior al vínculo.
    assigned_agent_id: str | None
    started_at: datetime.datetime | None
    completed_at: datetime.datetime | None
    created_at: datetime.datetime


class AgentRelationOut(BaseModel):
    """ASIGNACIÓN ≠ EJECUCIÓN (M48, Commit 7): quién debía ejecutar la tarea, quién la ejecutó y qué decir de ello."""

    #: ORCHESTRATOR · UNASSIGNED · ASSIGNED · MATCH · MISMATCH · EXECUTED_UNASSIGNED · UNKNOWN_AGENT · INCONSISTENT
    status: str
    assigned_agent_id: str | None
    #: `None` sin asignación; `False` si el registro no conoce al agente asignado.
    assigned_agent_known: bool | None
    executed_by_agent_id: str | None
    reassigned: bool
    executions: list[ExecutionTraceOut]


class RecoveryOut(BaseModel):
    """Qué clase de situación es la de la tarea y qué se puede hacer con ella (M49, Commit 8). Solo lectura."""

    #: none · recoverable · reassign_required · definitive · unknown_agent · mismatch · blocked
    kind: str
    can_retry: bool
    attempts_current_assignment: int
    max_attempts_per_assignment: int
    attempts_total: int
    max_attempts_per_task: int
    #: El número que tendría el próximo intento.
    next_attempt: int


class TaskOut(BaseModel):
    id: str
    project_id: str
    name: str
    capability: str
    status: str
    input: dict | None
    output: dict | None
    error: str | None
    depends_on: list[str]
    #: La asignación vigente (campos nuevos: aditivos, ninguno de los anteriores cambia).
    assigned_agent_id: str | None
    agent_relation: AgentRelationOut
    #: Campo nuevo y aditivo (Commit 8).
    recovery: RecoveryOut


def _relation_out(relation: TaskAgentRelation, known: frozenset[str]) -> AgentRelationOut:
    return AgentRelationOut(
        status=relation.status.value,
        assigned_agent_id=relation.assigned_agent_id,
        assigned_agent_known=relation.assigned_agent_known,
        executed_by_agent_id=relation.executed_by_agent_id,
        reassigned=relation.reassigned,
        executions=[
            ExecutionTraceOut(
                source=item.source,
                execution_id=item.execution_id,
                agent_id=item.agent_id,
                agent_known=item.agent_id in known,
                success=item.success,
                attempt=item.attempt,
                assigned_agent_id=item.assigned_agent_id,
                started_at=item.started_at,
                completed_at=item.completed_at,
                created_at=item.created_at,
            )
            for item in relation.executions
        ],
    )


def _recovery_out(recovery: TaskRecovery) -> RecoveryOut:
    return RecoveryOut(
        kind=recovery.kind.value,
        can_retry=recovery.can_retry,
        attempts_current_assignment=recovery.attempts_current_assignment,
        max_attempts_per_assignment=recovery.max_attempts_per_assignment,
        attempts_total=recovery.attempts_total,
        max_attempts_per_task=recovery.max_attempts_per_task,
        next_attempt=recovery.next_attempt,
    )


def _task_out(task: TaskModel, depends_on: list[str], relation: TaskAgentRelation, known: frozenset[str]) -> TaskOut:
    return TaskOut(
        id=task.id,
        project_id=task.project_id,
        name=task.name,
        capability=task.capability,
        status=task.status,
        input=task.input,
        output=task.output,
        error=task.error,
        depends_on=depends_on,
        assigned_agent_id=task.assigned_agent_id,
        agent_relation=_relation_out(relation, known),
        recovery=_recovery_out(
            describe_recovery(
                task_status=task.status,
                assigned_agent_id=task.assigned_agent_id,
                known_agent_ids=known,
                traces=relation.executions,
                relation_status=relation.status,
            )
        ),
    )


def _depends_on(db: Session, task_ids: list[str]) -> dict[str, list[str]]:
    dependencies = db.query(TaskDependencyModel).filter(TaskDependencyModel.child_task_id.in_(task_ids)).all()
    depends_on_by_task: dict[str, list[str]] = {}
    for dep in dependencies:
        depends_on_by_task.setdefault(dep.child_task_id, []).append(dep.parent_task_id)
    return depends_on_by_task


@router.get("", response_model=list[TaskOut])
def list_tasks(
    project_id: str, db: Session = Depends(get_db), manager: AgentManager = Depends(get_agent_manager)
) -> list[TaskOut]:
    tasks = db.query(TaskModel).filter(TaskModel.project_id == project_id).all()
    depends_on_by_task = _depends_on(db, [t.id for t in tasks])
    known = manager.agent_ids()
    relations = load_relations(db, tasks, known)
    return [_task_out(t, depends_on_by_task.get(t.id, []), relations[t.id], known) for t in tasks]


def _one(db: Session, manager: AgentManager, task_id: str) -> TaskOut:
    task = db.get(TaskModel, task_id)
    if task is None:
        raise NotFoundError(f"task {task_id} not found")
    known = manager.agent_ids()
    relation = load_relations(db, [task], known)[task.id]
    return _task_out(task, _depends_on(db, [task.id]).get(task.id, []), relation, known)


class RetryIn(BaseModel):
    """Repetir la tarea tras el intento `after_attempt` (el último que falló). Nombrarlo es lo que evita que dos
    peticiones iguales ejecuten dos veces: la segunda ve un intento posterior y se rechaza."""

    model_config = ConfigDict(extra="forbid")

    after_attempt: int = Field(ge=1)
    reason: str | None = Field(default=None, max_length=500)


class ReassignIn(BaseModel):
    """Pasar la tarea a otro agente DEL REGISTRO que tenga su capacidad. No ejecuta nada."""

    model_config = ConfigDict(extra="forbid")

    agent_id: str = Field(min_length=1, max_length=64)
    reason: str = Field(min_length=3, max_length=500)


@router.post("/{task_id}/retry", response_model=TaskOut)
def retry_task(
    task_id: str,
    payload: RetryIn,
    response: Response,
    db: Session = Depends(get_db),
    manager: AgentManager = Depends(get_agent_manager),
    identity: Actor = Depends(authorize(ApiAction.TASK_RECOVER)),
    settings: Settings = Depends(get_settings),
    idempotency_key: IdempotencyKeyHeader = None,
) -> TaskOut:
    """Reintenta UNA vez una tarea FAILED con su agente asignado (intento siguiente, ejecución nueva). 200 aunque el
    intento vuelva a fallar: lo que se pidió, un intento, se hizo y el cuerpo dice cómo acabó. Con
    `Idempotency-Key`, repetir la petición devuelve lo mismo sin ejecutar otro intento."""

    def work() -> TaskOut:
        TaskRecoveryService(db, manager).retry(
            task_id, actor=identity.subject, after_attempt=payload.after_attempt, reason=payload.reason
        )
        db.commit()
        return _one(db, manager, task_id)

    return run_idempotent(
        db,
        scope="tasks.retry",
        identity=identity,
        client_key=idempotency_key,
        settings=settings,
        payload={"task_id": task_id, **payload.model_dump()},
        response=response,
        status_code=200,
        response_model=TaskOut,
        work=work,
    )


@router.post("/{task_id}/reassign", response_model=TaskOut)
def reassign_task(
    task_id: str,
    payload: ReassignIn,
    response: Response,
    db: Session = Depends(get_db),
    manager: AgentManager = Depends(get_agent_manager),
    identity: Actor = Depends(authorize(ApiAction.TASK_RECOVER)),
    settings: Settings = Depends(get_settings),
    idempotency_key: IdempotencyKeyHeader = None,
) -> TaskOut:
    """Cambia el agente asignado a una tarea FAILED, BLOQUEADA o PENDIENTE y lo deja en la auditoría (`task.reassigned`,
    con la asignación anterior). No ejecuta nada: reintentar es otra petición."""

    def work() -> TaskOut:
        TaskRecoveryService(db, manager).reassign(
            task_id, agent_id=payload.agent_id, actor=identity.subject, reason=payload.reason
        )
        db.commit()
        return _one(db, manager, task_id)

    return run_idempotent(
        db,
        scope="tasks.reassign",
        identity=identity,
        client_key=idempotency_key,
        settings=settings,
        payload={"task_id": task_id, **payload.model_dump()},
        response=response,
        status_code=200,
        response_model=TaskOut,
        work=work,
    )
