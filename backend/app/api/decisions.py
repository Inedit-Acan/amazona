from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.ceo.mission import DecisionVersion, decision_versions, ordered_decisions
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
    #: Una misión reanudada tiene más de una decisión (M50): la posición de esta entre las del proyecto (1 = la
    #: primera), si es la vigente y a cuál sustituye. La anterior no se modifica nunca: sigue ahí, con su versión.
    version: int
    is_current: bool
    supersedes_decision_id: str | None


def _to_detail(decision: DecisionModel, db: Session, version: DecisionVersion) -> DecisionDetailOut:
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
        version=version.version,
        is_current=version.is_current,
        supersedes_decision_id=version.supersedes_decision_id,
    )


@router.get("", response_model=list[DecisionDetailOut])
def list_decisions(project_id: str, db: Session = Depends(get_db)) -> list[DecisionDetailOut]:
    decisions = ordered_decisions(db, project_id)
    versions = decision_versions(decisions)
    return [_to_detail(d, db, versions[d.id]) for d in decisions]


@router.get("/{decision_id}", response_model=DecisionDetailOut)
def get_decision(decision_id: str, db: Session = Depends(get_db)) -> DecisionDetailOut:
    decision = db.get(DecisionModel, decision_id)
    if decision is None:
        raise NotFoundError(f"decision {decision_id} not found")
    versions = decision_versions(ordered_decisions(db, decision.project_id))
    return _to_detail(decision, db, versions[decision.id])
