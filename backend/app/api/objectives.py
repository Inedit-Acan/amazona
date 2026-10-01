from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.auth.actor import Actor
from app.auth.dependencies import actor_name, authorize
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
