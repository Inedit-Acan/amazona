from app.agents.base import AgentResultStatus
from app.agents.operations import OperationsAgent


def _base_input(**overrides):
    payload = {
        "product_name": "Silicone kitchen organizer",
        "category": "home",
        "market": "us",
        "sale_price": 50.0,
        "lead_time_days": 20,
        "supplier_verified": True,
        "economic_recommendation": "GO",
        "legal_recommendation": "GO",
        "restricted": False,
    }
    payload.update(overrides)
    return payload


def test_healthy_priors_produce_a_ready_operations_report():
    agent = OperationsAgent()

    result = agent.run(_base_input())

    assert result.status == AgentResultStatus.COMPLETED
    assert result.recommendation == "GO"
    assert result.data["operations_status"] == "READY"
    assert result.data["order"]["tracking"]["stages"]
    assert result.data["return_policy"]["refund_estimate"] is not None
    assert result.data["support_ticket_example"]["ai_resolvable"] is True


def test_economic_no_go_blocks_operations():
    agent = OperationsAgent()

    result = agent.run(_base_input(economic_recommendation="NO_GO"))

    assert result.data["operations_status"] == "BLOCKED"
    assert result.recommendation == "NO_GO"
    assert any("economic" in risk.lower() for risk in result.risks)


def test_legal_no_go_blocks_operations():
    agent = OperationsAgent()

    result = agent.run(_base_input(legal_recommendation="NO_GO"))

    assert result.data["operations_status"] == "BLOCKED"
    assert result.recommendation == "NO_GO"


def test_missing_prior_analyses_needs_review():
    agent = OperationsAgent()

    result = agent.run(_base_input(economic_recommendation=None, legal_recommendation=None))

    assert result.data["operations_status"] == "NEEDS_REVIEW"
    assert result.recommendation == "REVIEW"
    assert result.risks


def test_unverified_supplier_generates_a_coordination_risk():
    agent = OperationsAgent()

    result = agent.run(_base_input(supplier_verified=False))

    assert any("supplier" in risk.lower() for risk in result.risks)
    assert result.data["supplier_coordination"]["supplier_verified"] is False


def test_restricted_category_escalates_the_support_ticket_to_a_human():
    agent = OperationsAgent()

    result = agent.run(_base_input(restricted=True, legal_recommendation="NO_GO"))

    assert result.data["support_ticket_example"]["ai_resolvable"] is False
    assert result.data["support_ticket_example"]["escalation_reason"]


def test_order_tracking_reflects_the_real_lead_time():
    agent = OperationsAgent()

    result = agent.run(_base_input(lead_time_days=60))

    assert result.data["order"]["tracking"]["lead_time_days_used"] == 60
