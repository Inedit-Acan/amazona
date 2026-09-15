from pydantic import BaseModel, Field

from app.ceo.schemas import DecisionStatus

GO_OPPORTUNITY_THRESHOLD = 0.5
GO_CONFIDENCE_THRESHOLD = 0.5


class DecisionInput(BaseModel):
    opportunity_score: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    legal_status: str = "CLEAR"
    finance_veto: bool = False
    security_veto: bool = False
    requires_human_approval: bool = False
    human_stop: bool = False


def evaluate_decision(decision_input: DecisionInput) -> DecisionStatus:
    """Deterministic CEO decision rules. No LLM involved: vetoes and human
    stop always win, and a high opportunity score can never bypass them.
    """
    if decision_input.human_stop:
        return DecisionStatus.NO_GO

    if decision_input.legal_status == "BLOCKED":
        return DecisionStatus.NO_GO

    if decision_input.finance_veto:
        return DecisionStatus.NO_GO

    if decision_input.security_veto:
        return DecisionStatus.NO_GO

    if decision_input.confidence < GO_CONFIDENCE_THRESHOLD:
        return DecisionStatus.REVIEW

    if decision_input.opportunity_score < GO_OPPORTUNITY_THRESHOLD:
        return DecisionStatus.REVIEW

    if decision_input.requires_human_approval:
        return DecisionStatus.HUMAN_APPROVAL

    return DecisionStatus.GO
