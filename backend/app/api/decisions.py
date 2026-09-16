from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.db.models.decision import Decision as DecisionModel
from app.db.models.decision import DecisionEvidence as DecisionEvidenceModel
from app.db.session import get_db

router = APIRouter(prefix="/api/decisions", tags=["decisions"])


class DecisionEvidenceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    source: str
    summary: str
    data: dict | None


class DecisionDetailOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    status: str
    opportunity_score: float | None
    confidence: float | None
    rationale: str | None
    correlation_id: str
    evidence: list[DecisionEvidenceOut]


def _to_detail(decision: DecisionModel, db: Session) -> DecisionDetailOut:
    evidence = db.query(DecisionEvidenceModel).filter(DecisionEvidenceModel.decision_id == decision.id).all()
    return DecisionDetailOut(
        id=decision.id,
        project_id=decision.project_id,
        status=decision.status,
        opportunity_score=decision.opportunity_score,
        confidence=decision.confidence,
        rationale=decision.rationale,
        correlation_id=decision.correlation_id,
        evidence=[DecisionEvidenceOut.model_validate(e) for e in evidence],
    )


@router.get("", response_model=list[DecisionDetailOut])
def list_decisions(project_id: str, db: Session = Depends(get_db)) -> list[DecisionDetailOut]:
    decisions = db.query(DecisionModel).filter(DecisionModel.project_id == project_id).all()
    return [_to_detail(d, db) for d in decisions]


@router.get("/{decision_id}", response_model=DecisionDetailOut)
def get_decision(decision_id: str, db: Session = Depends(get_db)) -> DecisionDetailOut:
    decision = db.get(DecisionModel, decision_id)
    if decision is None:
        raise NotFoundError(f"decision {decision_id} not found")
    return _to_detail(decision, db)
