from app.agents.base import AgentResultStatus
from app.agents.cfo import CFOAgent


def _base_input(**overrides):
    payload = {
        "total_products_analyzed": 10,
        "go_count": 8,
        "review_count": 1,
        "no_go_count": 1,
        "total_campaigns": 5,
        "active_campaigns": 4,
        "total_daily_budget": 200.0,
        "total_budget_hard_limit": 1000.0,
        "total_reserved": 100.0,
        "total_committed": 50.0,
        "total_spent": 50.0,
    }
    payload.update(overrides)
    return payload


def test_empty_catalog_needs_review():
    agent = CFOAgent()

    result = agent.run(_base_input(total_products_analyzed=0, go_count=0, review_count=0, no_go_count=0))

    assert result.status == AgentResultStatus.COMPLETED
    assert result.data["financial_health_status"] == "NEEDS_REVIEW"
    assert result.recommendation == "REVIEW"
    assert any("insufficient data" in risk for risk in result.risks)


def test_healthy_mix_is_healthy():
    agent = CFOAgent()

    result = agent.run(_base_input())

    assert result.data["financial_health_status"] == "HEALTHY"
    assert result.recommendation == "GO"


def test_majority_no_go_is_critical():
    agent = CFOAgent()

    result = agent.run(_base_input(total_products_analyzed=10, go_count=2, review_count=2, no_go_count=6))

    assert result.data["financial_health_status"] == "CRITICAL"
    assert result.recommendation == "NO_GO"
    assert any("risk concentration" in risk for risk in result.risks)


def test_elevated_no_go_ratio_is_at_risk():
    agent = CFOAgent()

    result = agent.run(_base_input(total_products_analyzed=10, go_count=6, review_count=1, no_go_count=3))

    assert result.data["financial_health_status"] == "AT_RISK"
    assert result.recommendation == "REVIEW"


def test_high_budget_utilization_is_at_risk():
    agent = CFOAgent()

    result = agent.run(
        _base_input(total_reserved=500.0, total_committed=300.0, total_spent=150.0, total_budget_hard_limit=1000.0)
    )

    assert result.data["financial_health_status"] == "AT_RISK"
    assert any("budget utilization" in risk for risk in result.risks)


def test_no_budget_recorded_flags_the_assumption():
    agent = CFOAgent()

    result = agent.run(_base_input(total_budget_hard_limit=0, total_reserved=0, total_committed=0, total_spent=0))

    assert result.data["budget_utilization"] is None
    assert any("no budget reservations recorded" in risk for risk in result.risks)
