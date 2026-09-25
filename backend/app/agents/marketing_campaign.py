from typing import cast

from pydantic import BaseModel

from app.agents.base import Agent, AgentResult, AgentResultStatus
from app.integrations.ports import AdPerformanceDirectory, IntegrationDomain
from app.integrations.registry import ProviderRegistry
from app.marketing.creative import generate_ad_creative, generate_audience_segments, recommend_budget_action

_WEAK_ROAS_THRESHOLD = 1.0
_MAX_ACCEPTABLE_LEAD_TIME_DAYS = 45


class MarketingCampaignInput(BaseModel):
    product_name: str
    category: str
    market: str
    platform: str = "meta"
    daily_budget: float = 20.0
    sale_price: float | None = None
    economic_recommendation: str | None = None
    legal_recommendation: str | None = None
    marketplace_listing_status: str | None = None
    lead_time_days: int | None = None
    competition_level: str | None = None


class MarketingCampaignAgent(Agent):
    """Fase 3, Agente 7: designs a campaign proposal (audience segments,
    ad creative with a text-only image brief, simulated performance
    estimate, budget recommendation) for an already-researched, sourced,
    priced, legally-screened, and listed product. Like Agents 5 and 6,
    there is no Milestone 1 "validate-one" sibling — marketing didn't
    exist as an agent before Fase 3 (only a placeholder spend_action
    string in the CEO's example context, which this agent's real
    daily_budget recommendation now replaces via the same query-param
    handoff mechanism as prior milestones). Consumes real data resolved
    by MarketingCampaignService; it never touches the DB itself.

    All ad performance data is simulated — no real Meta/Google/TikTok
    Ads API integration — and tagged accordingly by
    MockAdPerformanceDirectory."""

    capability = "marketing_campaign_planning"
    input_schema = MarketingCampaignInput

    def __init__(self, directory: AdPerformanceDirectory | None = None) -> None:
        self._directory: AdPerformanceDirectory = directory or cast(
            AdPerformanceDirectory, ProviderRegistry().resolve(IntegrationDomain.ADS)
        )

    def run(self, task_input: dict) -> AgentResult:
        params = MarketingCampaignInput.model_validate(task_input)
        performance = self._directory.get_performance_estimate(
            category=params.category, platform=params.platform
        )

        if performance is None:
            return AgentResult(
                status=AgentResultStatus.COMPLETED,
                recommendation="REVIEW",
                confidence=0.3,
                evidence=[],
                risks=[
                    f"insufficient ad performance data for category {params.category!r} "
                    f"on platform {params.platform!r}"
                ],
                assumptions=[],
                data={"campaign_status": "NEEDS_REVIEW"},
            )

        projected_roas = None
        if params.sale_price is not None:
            projected_roas = (
                performance["conversion_rate"] * params.sale_price / performance["avg_cpc"]
            )

        risks: list[str] = []
        if params.economic_recommendation is None:
            risks.append("insufficient data: no economic analysis found for this product")
        if params.legal_recommendation is None:
            risks.append("insufficient data: no legal analysis found for this product/market")
        if params.economic_recommendation == "NO_GO":
            risks.append("blocked: economic analysis recommends NO_GO")
        if params.legal_recommendation == "NO_GO":
            risks.append("blocked: legal analysis recommends NO_GO")
        if projected_roas is not None and projected_roas < _WEAK_ROAS_THRESHOLD:
            risks.append(f"blocked: projected ROAS {projected_roas:.2f} is below break-even")
        if params.marketplace_listing_status == "BLOCKED":
            risks.append("marketplace listing is blocked — resolve before scaling ad spend")
        if params.lead_time_days is not None and params.lead_time_days > _MAX_ACCEPTABLE_LEAD_TIME_DAYS:
            risks.append(
                f"long supplier lead time ({params.lead_time_days} days) — ensure inventory "
                "readiness before scaling ad spend"
            )

        blocked = (
            params.economic_recommendation == "NO_GO"
            or params.legal_recommendation == "NO_GO"
            or (projected_roas is not None and projected_roas < _WEAK_ROAS_THRESHOLD)
        )
        needs_review = (
            params.economic_recommendation is None
            or params.legal_recommendation is None
            or params.economic_recommendation == "REVIEW"
            or params.legal_recommendation == "REVIEW"
        )

        if blocked:
            campaign_status = "BLOCKED"
            recommendation = "NO_GO"
            confidence = 0.9
        elif needs_review:
            campaign_status = "NEEDS_REVIEW"
            recommendation = "REVIEW"
            confidence = 0.4
        else:
            campaign_status = "READY"
            recommendation = "GO"
            confidence = 0.85

        return AgentResult(
            status=AgentResultStatus.COMPLETED,
            recommendation=recommendation,
            confidence=confidence,
            evidence=[f"campaign_status={campaign_status} on {params.platform}/{params.market}"],
            risks=risks,
            assumptions=[
                "audience segments, ad creative, and performance estimates are simulated placeholders — "
                "no real ad spend or ad-platform integration"
            ],
            data={
                "campaign_status": campaign_status,
                "daily_budget": params.daily_budget,
                "audience_segments": generate_audience_segments(
                    category=params.category, competition_level=params.competition_level
                ),
                "ad_creative": generate_ad_creative(
                    product_name=params.product_name, category=params.category, sale_price=params.sale_price
                ),
                "performance_estimate": {**performance, "projected_roas": projected_roas},
                "budget_recommendation": recommend_budget_action(projected_roas=projected_roas),
            },
        )
