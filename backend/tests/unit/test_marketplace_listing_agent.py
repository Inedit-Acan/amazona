from app.agents.base import AgentResultStatus
from app.agents.marketplace_listing import MarketplaceListingAgent


def _base_input(**overrides):
    payload = {
        "product_name": "Travel cable organizer",
        "category": "accessories",
        "market": "us",
        "platform": "amazon",
        "sale_price": 20.0,
        "unit_landed_cost": 1.7,
        "economic_recommendation": "GO",
        "legal_recommendation": "GO",
        "competition_level": "low",
    }
    payload.update(overrides)
    return payload


def test_healthy_priors_and_no_approval_needed_produce_a_ready_listing():
    agent = MarketplaceListingAgent()

    result = agent.run(_base_input())

    assert result.status == AgentResultStatus.COMPLETED
    assert result.recommendation == "GO"
    assert result.data["listing_status"] == "READY"
    assert result.data["listing_content"]["title"]
    assert result.data["competition_analysis"]["data_origin"] == "simulated_not_sp_api"
    assert result.data["commission_breakdown"]["net_margin_per_unit"] is not None
    assert result.data["inventory_policy"]["tracking_enabled"] is False


def test_economic_no_go_blocks_the_listing():
    agent = MarketplaceListingAgent()

    result = agent.run(_base_input(economic_recommendation="NO_GO"))

    assert result.data["listing_status"] == "BLOCKED"
    assert result.recommendation == "NO_GO"
    assert any("economic" in risk.lower() for risk in result.risks)


def test_legal_no_go_blocks_the_listing():
    agent = MarketplaceListingAgent()

    result = agent.run(_base_input(legal_recommendation="NO_GO"))

    assert result.data["listing_status"] == "BLOCKED"
    assert result.recommendation == "NO_GO"


def test_category_requiring_approval_needs_review():
    agent = MarketplaceListingAgent()

    result = agent.run(_base_input(category="electronics"))

    assert result.data["listing_status"] == "NEEDS_REVIEW"
    assert result.recommendation == "REVIEW"


def test_negative_net_margin_after_commissions_blocks_the_listing():
    agent = MarketplaceListingAgent()

    # accessories/amazon: referral 15% + fulfillment 2.8 per unit.
    # sale_price 3.0, landed cost 2.5 -> net margin deeply negative.
    result = agent.run(_base_input(sale_price=3.0, unit_landed_cost=2.5))

    assert result.data["listing_status"] == "BLOCKED"
    assert result.recommendation == "NO_GO"
    assert any("commission" in risk.lower() for risk in result.risks)


def test_unknown_category_platform_pair_returns_review_with_insufficient_data_risk():
    agent = MarketplaceListingAgent()

    result = agent.run(_base_input(category="does-not-exist"))

    assert result.status == AgentResultStatus.COMPLETED
    assert result.data["listing_status"] == "NEEDS_REVIEW"
    assert result.recommendation == "REVIEW"
    assert result.risks


def test_missing_price_data_does_not_crash_and_leaves_net_margin_none():
    agent = MarketplaceListingAgent()

    result = agent.run(_base_input(sale_price=None, unit_landed_cost=None))

    assert result.status == AgentResultStatus.COMPLETED
    assert result.data["commission_breakdown"]["net_margin_per_unit"] is None
