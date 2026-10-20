import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.agents.registry import known_agent_ids
from app.db.models.task import Task as TaskModel
from app.db.models.task import TaskDependency as TaskDependencyModel
from app.db.session import get_db
from app.tasks.assignment import TaskAgentRelation, load_relations

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


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


@router.get("", response_model=list[TaskOut])
def list_tasks(project_id: str, db: Session = Depends(get_db)) -> list[TaskOut]:
    tasks = db.query(TaskModel).filter(TaskModel.project_id == project_id).all()
    dependencies = (
        db.query(TaskDependencyModel)
        .filter(TaskDependencyModel.child_task_id.in_([t.id for t in tasks]))
        .all()
    )
    depends_on_by_task: dict[str, list[str]] = {}
    for dep in dependencies:
        depends_on_by_task.setdefault(dep.child_task_id, []).append(dep.parent_task_id)

    known = known_agent_ids()
    relations = load_relations(db, tasks, known)

    return [
        TaskOut(
            id=t.id,
            project_id=t.project_id,
            name=t.name,
            capability=t.capability,
            status=t.status,
            input=t.input,
            output=t.output,
            error=t.error,
            depends_on=depends_on_by_task.get(t.id, []),
            assigned_agent_id=t.assigned_agent_id,
            agent_relation=_relation_out(relations[t.id], known),
        )
        for t in tasks
    ]
