from app.agents.base import AgentResultStatus
from app.agents.marketing_campaign import MarketingCampaignAgent


def _base_input(**overrides):
    payload = {
        "product_name": "Silicone kitchen organizer",
        "category": "home",
        "market": "us",
        "platform": "google",
        "daily_budget": 20.0,
        "sale_price": 50.0,
        "economic_recommendation": "GO",
        "legal_recommendation": "GO",
        "marketplace_listing_status": "READY",
        "lead_time_days": 20,
        "competition_level": "low",
    }
    payload.update(overrides)
    return payload


def test_healthy_priors_and_strong_roas_produce_a_ready_campaign():
    agent = MarketingCampaignAgent()

    result = agent.run(_base_input())

    assert result.status == AgentResultStatus.COMPLETED
    assert result.recommendation == "GO"
    assert result.data["campaign_status"] == "READY"
    assert result.data["audience_segments"]
    assert result.data["ad_creative"]["image_brief"]
    assert result.data["performance_estimate"]["data_origin"] == "simulated_ad_performance_estimate"
    assert result.data["performance_estimate"]["projected_roas"] >= 2.0
    assert result.data["budget_recommendation"]


def test_economic_no_go_blocks_the_campaign():
    agent = MarketingCampaignAgent()

    result = agent.run(_base_input(economic_recommendation="NO_GO"))

    assert result.data["campaign_status"] == "BLOCKED"
    assert result.recommendation == "NO_GO"
    assert any("economic" in risk.lower() for risk in result.risks)


def test_legal_no_go_blocks_the_campaign():
    agent = MarketingCampaignAgent()

    result = agent.run(_base_input(legal_recommendation="NO_GO"))

    assert result.data["campaign_status"] == "BLOCKED"
    assert result.recommendation == "NO_GO"


def test_weak_projected_roas_blocks_the_campaign():
    agent = MarketingCampaignAgent()

    # accessories/meta: conversion_rate 0.02, avg_cpc 0.40 -> roas = 0.02*price/0.40.
    # price=5.0 -> roas=0.25, well under 1.0.
    result = agent.run(
        _base_input(category="accessories", platform="meta", sale_price=5.0)
    )

    assert result.data["campaign_status"] == "BLOCKED"
    assert result.recommendation == "NO_GO"
    assert any("roas" in risk.lower() for risk in result.risks)


def test_missing_prior_analyses_needs_review():
    agent = MarketingCampaignAgent()

    result = agent.run(_base_input(economic_recommendation=None, legal_recommendation=None))

    assert result.data["campaign_status"] == "NEEDS_REVIEW"
    assert result.recommendation == "REVIEW"
    assert result.risks


def test_blocked_marketplace_listing_is_a_risk_but_does_not_block_the_campaign():
    agent = MarketingCampaignAgent()

    result = agent.run(_base_input(marketplace_listing_status="BLOCKED"))

    assert result.data["campaign_status"] == "READY"
    assert any("marketplace" in risk.lower() for risk in result.risks)


def test_long_lead_time_generates_an_inventory_readiness_risk():
    agent = MarketingCampaignAgent()

    result = agent.run(_base_input(lead_time_days=60))

    assert any("lead time" in risk.lower() or "inventory" in risk.lower() for risk in result.risks)


def test_unknown_category_platform_pair_returns_review_with_insufficient_data_risk():
    agent = MarketingCampaignAgent()

    result = agent.run(_base_input(category="does-not-exist"))

    assert result.status == AgentResultStatus.COMPLETED
    assert result.data["campaign_status"] == "NEEDS_REVIEW"
    assert result.recommendation == "REVIEW"
    assert result.risks


def test_missing_price_leaves_roas_none_without_crashing():
    agent = MarketingCampaignAgent()

    result = agent.run(_base_input(sale_price=None))

    assert result.status == AgentResultStatus.COMPLETED
    assert result.data["performance_estimate"]["projected_roas"] is None
