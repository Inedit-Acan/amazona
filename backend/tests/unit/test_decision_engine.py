from app.ceo.decision_engine import DecisionInput, evaluate_decision
from app.ceo.schemas import DecisionStatus


def base_input(**overrides) -> DecisionInput:
    defaults = dict(
        opportunity_score=0.9,
        confidence=0.9,
        legal_status="CLEAR",
        finance_veto=False,
        security_veto=False,
        requires_human_approval=False,
        human_stop=False,
    )
    defaults.update(overrides)
    return DecisionInput(**defaults)


def test_go_for_a_strong_opportunity_with_no_vetoes():
    assert evaluate_decision(base_input()) == DecisionStatus.GO


def test_legal_blocked_forces_no_go_even_with_a_perfect_score():
    result = evaluate_decision(base_input(opportunity_score=1.0, confidence=1.0, legal_status="BLOCKED"))

    assert result == DecisionStatus.NO_GO


def test_finance_veto_forces_no_go_even_with_a_perfect_score():
    result = evaluate_decision(base_input(opportunity_score=1.0, confidence=1.0, finance_veto=True))

    assert result == DecisionStatus.NO_GO


def test_security_veto_forces_no_go_even_with_a_perfect_score():
    result = evaluate_decision(base_input(opportunity_score=1.0, confidence=1.0, security_veto=True))

    assert result == DecisionStatus.NO_GO


def test_human_stop_forces_no_go_even_when_human_approval_would_otherwise_apply():
    result = evaluate_decision(base_input(requires_human_approval=True, human_stop=True))

    assert result == DecisionStatus.NO_GO


def test_low_confidence_yields_review_insufficient_data():
    result = evaluate_decision(base_input(confidence=0.3, opportunity_score=0.9))

    assert result == DecisionStatus.REVIEW


def test_low_opportunity_score_yields_review():
    result = evaluate_decision(base_input(opportunity_score=0.2, confidence=0.9))

    assert result == DecisionStatus.REVIEW


def test_simulated_external_spend_requires_human_approval():
    result = evaluate_decision(base_input(requires_human_approval=True))

    assert result == DecisionStatus.HUMAN_APPROVAL


def test_human_approval_does_not_override_a_legal_veto():
    result = evaluate_decision(base_input(legal_status="BLOCKED", requires_human_approval=True))

    assert result == DecisionStatus.NO_GO


def test_human_approval_does_not_override_a_finance_veto():
    result = evaluate_decision(base_input(finance_veto=True, requires_human_approval=True))

    assert result == DecisionStatus.NO_GO
