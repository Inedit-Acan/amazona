from app.agents.base import AgentResultStatus
from app.agents.ecommerce_storefront import EcommerceStorefrontAgent


def _base_input(**overrides):
    payload = {
        "product_id": "prod-1234abcd",
        "product_name": "Travel cable organizer",
        "category": "accessories",
        "market": "us",
        "sale_price": 20.0,
        "margin_percent": 0.6,
        "economic_recommendation": "GO",
        "legal_recommendation": "GO",
        "restricted": False,
        "lead_time_days": 20,
        "competition_level": "low",
    }
    payload.update(overrides)
    return payload


def test_healthy_priors_produce_a_ready_storefront():
    agent = EcommerceStorefrontAgent()

    result = agent.run(_base_input())

    assert result.status == AgentResultStatus.COMPLETED
    assert result.recommendation == "GO"
    assert result.data["launch_status"] == "READY"
    assert result.data["landing_page_copy"]["price_display"] == "$20.00"
    assert result.data["payment_gateway_plan"]["requires_human_approval"] is True
    assert result.data["catalog_entry"]["lead_time_days"] == 20
    assert result.data["conversion_tips"]


def test_economic_no_go_blocks_the_storefront():
    agent = EcommerceStorefrontAgent()

    result = agent.run(_base_input(economic_recommendation="NO_GO"))

    assert result.data["launch_status"] == "BLOCKED"
    assert result.recommendation == "NO_GO"
    assert any("economic" in risk.lower() for risk in result.risks)


def test_legal_no_go_blocks_the_storefront():
    agent = EcommerceStorefrontAgent()

    result = agent.run(_base_input(legal_recommendation="NO_GO", restricted=True))

    assert result.data["launch_status"] == "BLOCKED"
    assert result.recommendation == "NO_GO"
    assert any("legal" in risk.lower() for risk in result.risks)


def test_review_recommendation_needs_review_not_blocked():
    agent = EcommerceStorefrontAgent()

    result = agent.run(_base_input(economic_recommendation="REVIEW"))

    assert result.data["launch_status"] == "NEEDS_REVIEW"
    assert result.recommendation == "REVIEW"


def test_missing_prior_analyses_needs_review_with_insufficient_data_risk():
    agent = EcommerceStorefrontAgent()

    result = agent.run(
        _base_input(economic_recommendation=None, legal_recommendation=None, sale_price=None, margin_percent=None)
    )

    assert result.status == AgentResultStatus.COMPLETED
    assert result.data["launch_status"] == "NEEDS_REVIEW"
    assert result.recommendation == "REVIEW"
    assert result.risks


def test_catalog_entry_uses_real_values_not_defaults():
    agent = EcommerceStorefrontAgent()

    result = agent.run(_base_input(sale_price=42.5, lead_time_days=33))

    assert result.data["catalog_entry"]["price"] == 42.5
    assert result.data["catalog_entry"]["lead_time_days"] == 33
