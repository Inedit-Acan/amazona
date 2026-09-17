from pydantic import BaseModel

from app.agents.base import Agent, AgentResult, AgentResultStatus
from app.ecommerce.content import (
    generate_conversion_tips,
    generate_landing_page_copy,
    generate_payment_gateway_plan,
    generate_store_slug,
)


class EcommerceStorefrontInput(BaseModel):
    product_id: str = "unknown"
    product_name: str
    category: str
    market: str
    sale_price: float | None = None
    margin_percent: float | None = None
    economic_recommendation: str | None = None
    legal_recommendation: str | None = None
    restricted: bool | None = None
    lead_time_days: int | None = None
    competition_level: str | None = None


class EcommerceStorefrontAgent(Agent):
    """Fase 3, Agente 5: generates a storefront draft (landing page copy,
    simulated payment gateway plan, catalog entry, conversion tips) for
    an already-researched, sourced, priced, and legally-screened product.
    Unlike Agents 2-4, there is no Milestone 1 "validate-one" sibling to
    coexist with — e-commerce didn't exist before Fase 3. Launch
    readiness is gated on the most recent economic and legal
    recommendations: a NO_GO from either blocks the storefront, exactly
    like a real business would never launch on an unviable or legally
    blocked product. Consumes real data resolved by
    EcommerceStorefrontService; it never touches the DB itself."""

    capability = "ecommerce_storefront_generation"
    input_schema = EcommerceStorefrontInput

    def run(self, task_input: dict) -> AgentResult:
        params = EcommerceStorefrontInput.model_validate(task_input)

        risks: list[str] = []
        if params.economic_recommendation is None:
            risks.append("insufficient data: no economic analysis found for this product")
        if params.legal_recommendation is None:
            risks.append("insufficient data: no legal analysis found for this product/market")

        if params.economic_recommendation == "NO_GO":
            risks.append("blocked: economic analysis recommends NO_GO")
        if params.legal_recommendation == "NO_GO":
            risks.append("blocked: legal analysis recommends NO_GO")

        blocked = params.economic_recommendation == "NO_GO" or params.legal_recommendation == "NO_GO"
        missing_priors = params.economic_recommendation is None or params.legal_recommendation is None
        needs_review = (
            params.economic_recommendation == "REVIEW" or params.legal_recommendation == "REVIEW"
        )

        if blocked:
            launch_status = "BLOCKED"
            recommendation = "NO_GO"
            confidence = 0.9
        elif missing_priors or needs_review:
            launch_status = "NEEDS_REVIEW"
            recommendation = "REVIEW"
            confidence = 0.4
        else:
            launch_status = "READY"
            recommendation = "GO"
            confidence = 0.85

        landing_page_copy = generate_landing_page_copy(
            product_name=params.product_name,
            category=params.category,
            sale_price=params.sale_price,
            competition_level=params.competition_level,
        )
        payment_gateway_plan = generate_payment_gateway_plan(params.market)
        conversion_tips = generate_conversion_tips(
            margin_percent=params.margin_percent, competition_level=params.competition_level
        )
        store_slug = generate_store_slug(params.product_name, params.product_id)
        catalog_entry = {
            "sku": store_slug,
            "price": params.sale_price,
            "category": params.category,
            "market": params.market,
            "restricted": params.restricted,
            "lead_time_days": params.lead_time_days,
        }

        return AgentResult(
            status=AgentResultStatus.COMPLETED,
            recommendation=recommendation,
            confidence=confidence,
            evidence=[f"launch_status={launch_status} for market {params.market}"],
            risks=risks,
            assumptions=[
                "landing page copy, payment gateway plan, and conversion tips are simulated placeholders, "
                "not a live store or a real payment integration"
            ],
            data={
                "launch_status": launch_status,
                "store_slug": store_slug,
                "landing_page_copy": landing_page_copy,
                "payment_gateway_plan": payment_gateway_plan,
                "catalog_entry": catalog_entry,
                "conversion_tips": conversion_tips,
            },
        )
