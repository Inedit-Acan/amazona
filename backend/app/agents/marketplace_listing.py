from pydantic import BaseModel

from app.agents.base import Agent, AgentResult, AgentResultStatus
from app.ai.mock_marketplace_directory import MockMarketplaceDirectory
from app.marketplace.listing_content import generate_listing_content


class MarketplaceListingInput(BaseModel):
    product_name: str
    category: str
    market: str
    platform: str = "amazon"
    sale_price: float | None = None
    unit_landed_cost: float | None = None
    economic_recommendation: str | None = None
    legal_recommendation: str | None = None
    competition_level: str | None = None


class MarketplaceListingAgent(Agent):
    """Fase 3, Agente 6: creates/optimizes a marketplace listing draft,
    a simulated competition analysis, a real commission/net-margin
    breakdown, and an informational (no real stock) inventory policy,
    for an already-researched, sourced, priced, and legally-screened
    product. Like Agent 5, there is no Milestone 1 "validate-one"
    sibling — marketplaces didn't exist before Fase 3. See ADR 0004 for
    the general capability-pair convention this agent still follows in
    spirit. Consumes real data resolved by MarketplaceListingService;
    it never touches the DB itself.

    Amazon SP-API data policy (README.md): this agent never calls
    SP-API. Its competition data comes from MockMarketplaceDirectory,
    which tags every block data_origin="simulated_not_sp_api" — see
    that module's docstring."""

    capability = "marketplace_listing_optimization"
    input_schema = MarketplaceListingInput

    def __init__(self, directory: MockMarketplaceDirectory | None = None) -> None:
        self._directory = directory or MockMarketplaceDirectory()

    def run(self, task_input: dict) -> AgentResult:
        params = MarketplaceListingInput.model_validate(task_input)
        marketplace_data = self._directory.get_marketplace_data(
            category=params.category, platform=params.platform
        )

        if marketplace_data is None:
            return AgentResult(
                status=AgentResultStatus.COMPLETED,
                recommendation="REVIEW",
                confidence=0.3,
                evidence=[],
                risks=[
                    f"insufficient marketplace data for category {params.category!r} "
                    f"on platform {params.platform!r}"
                ],
                assumptions=[],
                data={"listing_status": "NEEDS_REVIEW"},
            )

        commission = marketplace_data["commission"]
        competition = marketplace_data["competition"]
        policy = marketplace_data["policy"]

        net_margin_per_unit = None
        if params.sale_price is not None and params.unit_landed_cost is not None:
            referral_fee = params.sale_price * commission["referral_fee_percent"]
            net_margin_per_unit = (
                params.sale_price
                - params.unit_landed_cost
                - referral_fee
                - commission["fulfillment_fee_per_unit"]
            )

        risks: list[str] = list(policy["notes"])
        if params.economic_recommendation == "NO_GO":
            risks.append("blocked: economic analysis recommends NO_GO")
        if params.legal_recommendation == "NO_GO":
            risks.append("blocked: legal analysis recommends NO_GO")
        if policy["prohibited"]:
            risks.append("blocked: category is prohibited on this platform")
        if net_margin_per_unit is not None and net_margin_per_unit < 0:
            risks.append("blocked: marketplace commissions exceed the product's margin")
        if competition["buy_box_difficulty"] == "high":
            risks.append("high buy-box competition on this platform")

        blocked = (
            params.economic_recommendation == "NO_GO"
            or params.legal_recommendation == "NO_GO"
            or policy["prohibited"]
            or (net_margin_per_unit is not None and net_margin_per_unit < 0)
        )
        needs_review = (
            policy["approval_required"]
            or params.economic_recommendation is None
            or params.legal_recommendation is None
            or params.economic_recommendation == "REVIEW"
            or params.legal_recommendation == "REVIEW"
        )

        if blocked:
            listing_status = "BLOCKED"
            recommendation = "NO_GO"
            confidence = 0.9
        elif needs_review:
            listing_status = "NEEDS_REVIEW"
            recommendation = "REVIEW"
            confidence = 0.4
        else:
            listing_status = "READY"
            recommendation = "GO"
            confidence = 0.85

        return AgentResult(
            status=AgentResultStatus.COMPLETED,
            recommendation=recommendation,
            confidence=confidence,
            evidence=[f"listing_status={listing_status} on {params.platform}/{params.market}"],
            risks=risks,
            assumptions=[
                "listing content, competition analysis, and commission figures are simulated "
                "placeholders — no real marketplace-seller-API integration"
            ],
            data={
                "listing_status": listing_status,
                "listing_content": generate_listing_content(
                    product_name=params.product_name,
                    category=params.category,
                    sale_price=params.sale_price,
                    competition_level=params.competition_level,
                ),
                "competition_analysis": competition,
                "commission_breakdown": {
                    "referral_fee_percent": commission["referral_fee_percent"],
                    "fulfillment_fee_per_unit": commission["fulfillment_fee_per_unit"],
                    "net_margin_per_unit": net_margin_per_unit,
                },
                "inventory_policy": {
                    "tracking_enabled": False,
                    "fulfillment_method": "simulated FBM — no real stock tracked",
                },
                "policy": policy,
            },
        )
