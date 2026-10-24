from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.agents.manager import AgentManager
from app.api.tasks import get_agent_manager
from app.auth.actor import Actor
from app.auth.dependencies import actor_name, authorize
from app.ceo.mission import load_mission, resolve_project_id
from app.ceo.orchestrator import CEOOrchestrator
from app.core.config import Settings, get_settings
from app.db.models.objective import Objective as ObjectiveModel
from app.db.session import get_db
from app.idempotency.service import IdempotencyKeyHeader, run_idempotent
from app.permissions.policies import ApiAction

router = APIRouter(prefix="/api/objectives", tags=["objectives"])


class ObjectiveCreate(BaseModel):
    title: str
    description: str | None = None
    created_by: str
    context: dict = Field(default_factory=dict)


class ObjectiveOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    description: str | None
    created_by: str
    status: str
    context: dict | None


class DecisionOut(BaseModel):
    id: str
    project_id: str
    status: str
    opportunity_score: float | None
    confidence: float | None
    rationale: str | None
    correlation_id: str


@router.post("", response_model=ObjectiveOut, status_code=201)
def create_objective(
    payload: ObjectiveCreate,
    db: Session = Depends(get_db),
    identity: Actor = Depends(authorize(ApiAction.OBJECTIVE_WRITE)),
    settings: Settings = Depends(get_settings),
) -> ObjectiveModel:
    objective = ObjectiveModel(
        title=payload.title,
        description=payload.description,
        created_by=actor_name(identity, payload.created_by, settings),
        context=payload.context,
        status="RECEIVED",
    )
    db.add(objective)
    db.commit()
    db.refresh(objective)
    return objective


@router.post("/{objective_id}/run", response_model=DecisionOut)
def run_objective(
    objective_id: str,
    response: Response,
    db: Session = Depends(get_db),
    identity: Actor = Depends(authorize(ApiAction.OBJECTIVE_WRITE)),
    settings: Settings = Depends(get_settings),
    idempotency_key: IdempotencyKeyHeader = None,
) -> DecisionOut:
    """Con `Idempotency-Key`, repetir la petición devuelve la decisión original sin volver a ejecutar el
    objetivo: decidir reserva presupuesto y abre aprobaciones, y hacerlo dos veces no es un detalle."""

    def work() -> DecisionOut:
        decision = CEOOrchestrator(db).run_objective(objective_id)
        return DecisionOut(
            id=decision.id,
            project_id=decision.project_id,
            status=decision.status,
            opportunity_score=decision.opportunity_score,
            confidence=decision.confidence,
            rationale=decision.rationale,
            correlation_id=decision.correlation_id,
        )

    return run_idempotent(
        db,
        scope="objectives.run",
        identity=identity,
        client_key=idempotency_key,
        settings=settings,
        payload={"objective_id": objective_id},
        response=response,
        status_code=200,
        response_model=DecisionOut,
        work=work,
    )


class ResumeIn(BaseModel):
    """Reanudar la misión del objetivo tras la decisión `after_decision_id` (la última que el cliente vio). Nombrarla
    es lo que evita que dos peticiones iguales ejecuten dos veces: la segunda ve una decisión posterior y se rechaza."""

    model_config = ConfigDict(extra="forbid")

    after_decision_id: str = Field(min_length=1, max_length=36)
    #: Solo hace falta si el objetivo tiene más de un proyecto (se ejecutó más de una vez): no se adivina cuál.
    project_id: str | None = Field(default=None, min_length=1, max_length=36)
    reason: str | None = Field(default=None, max_length=500)


class ResumeOut(DecisionOut):
    objective_id: str
    #: La decisión que esta sustituye en vigencia. Sigue guardada, sin cambios.
    previous_decision_id: str
    #: Las tareas que esta reanudación ejecutó, por orden. Las que ya estaban COMPLETED no aparecen: no se repiten.
    executed_tasks: list[str]
    #: Cómo quedó la misión: `complete`, o `recovery_pending` si una tarea volvió a fallar.
    state: str


@router.post("/{objective_id}/resume", response_model=ResumeOut)
def resume_objective(
    objective_id: str,
    payload: ResumeIn,
    response: Response,
    db: Session = Depends(get_db),
    manager: AgentManager = Depends(get_agent_manager),
    identity: Actor = Depends(authorize(ApiAction.TASK_RECOVER)),
    settings: Settings = Depends(get_settings),
    idempotency_key: IdempotencyKeyHeader = None,
) -> ResumeOut:
    """Reanuda una misión INCOMPLETA después de recuperar sus tareas: ejecuta solo lo pendiente y desbloqueable,
    escribe una decisión nueva y deja la anterior intacta. 200 aunque una tarea vuelva a fallar (la decisión nueva es
    entonces un REVIEW incompleto y `state` lo dice). 409 si no se puede: misión completa o cancelada, una tarea FAILED
    o con agente desconocido sin resolver, ya en curso, o una decisión obsoleta. Con `Idempotency-Key`, repetir la
    petición devuelve lo mismo sin ejecutar otra vez; en producción es obligatoria."""

    def work() -> ResumeOut:
        project_id = resolve_project_id(db, objective_id, payload.project_id)
        result = CEOOrchestrator(db, agent_manager=manager).resume_mission(
            project_id, actor=identity.subject, after_decision_id=payload.after_decision_id, reason=payload.reason
        )
        decision = result.decision
        view = load_mission(db, manager, project_id)
        return ResumeOut(
            id=decision.id,
            project_id=decision.project_id,
            status=decision.status,
            opportunity_score=decision.opportunity_score,
            confidence=decision.confidence,
            rationale=decision.rationale,
            correlation_id=decision.correlation_id,
            objective_id=objective_id,
            previous_decision_id=result.previous_decision_id,
            executed_tasks=list(result.executed_tasks),
            state=view.state.value,
        )

    return run_idempotent(
        db,
        scope="objectives.resume",
        identity=identity,
        client_key=idempotency_key,
        settings=settings,
        payload={"objective_id": objective_id, **payload.model_dump()},
        response=response,
        status_code=200,
        response_model=ResumeOut,
        work=work,
    )
