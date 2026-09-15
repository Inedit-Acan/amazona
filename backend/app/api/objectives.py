from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.ceo.orchestrator import CEOOrchestrator
from app.db.models.objective import Objective as ObjectiveModel
from app.db.session import get_db

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
def create_objective(payload: ObjectiveCreate, db: Session = Depends(get_db)) -> ObjectiveModel:
    objective = ObjectiveModel(
        title=payload.title,
        description=payload.description,
        created_by=payload.created_by,
        context=payload.context,
        status="RECEIVED",
    )
    db.add(objective)
    db.commit()
    db.refresh(objective)
    return objective


@router.post("/{objective_id}/run", response_model=DecisionOut)
def run_objective(objective_id: str, db: Session = Depends(get_db)) -> DecisionOut:
    orchestrator = CEOOrchestrator(db)
    decision = orchestrator.run_objective(objective_id)
    return DecisionOut(
        id=decision.id,
        project_id=decision.project_id,
        status=decision.status,
        opportunity_score=decision.opportunity_score,
        confidence=decision.confidence,
        rationale=decision.rationale,
        correlation_id=decision.correlation_id,
    )
