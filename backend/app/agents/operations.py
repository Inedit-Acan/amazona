from pydantic import BaseModel

from app.agents.base import Agent, AgentResult, AgentResultStatus
from app.operations.fulfillment import (
    classify_support_ticket,
    generate_order_id,
    generate_order_tracking,
    generate_return_policy,
)


class OperationsInput(BaseModel):
    product_name: str
    category: str
    market: str
    sale_price: float | None = None
    lead_time_days: int | None = None
    supplier_verified: bool | None = None
    economic_recommendation: str | None = None
    legal_recommendation: str | None = None
    restricted: bool | None = None


class OperationsAgent(Agent):
    """Fase 3, Agente 8 (último agente operativo): simulates one sample
    order + tracking timeline, supplier coordination (using real lead
    time/verification), a returns policy, and a support-ticket triage
    that decides AI-resolvable vs human-escalated — for an
    already-researched, sourced, priced, and legally-screened product.
    Like Agents 5-7, there is no Milestone 1 "validate-one" sibling.
    Consumes real data resolved by OperationsService; it never touches
    the DB itself.

    No real orders, customers, CRM, ticketing system, or carrier
    integration — every value here is a deterministic, documented
    placeholder illustrating one example order/ticket."""

    capability = "operations_fulfillment_management"
    input_schema = OperationsInput

    def run(self, task_input: dict) -> AgentResult:
        params = OperationsInput.model_validate(task_input)

        risks: list[str] = []
        if params.economic_recommendation is None:
            risks.append("insufficient data: no economic analysis found for this product")
        if params.legal_recommendation is None:
            risks.append("insufficient data: no legal analysis found for this product/market")
        if params.economic_recommendation == "NO_GO":
            risks.append("blocked: economic analysis recommends NO_GO")
        if params.legal_recommendation == "NO_GO":
            risks.append("blocked: legal analysis recommends NO_GO")
        if params.supplier_verified is False:
            risks.append("supplier not verified — coordinate closely before committing to delivery estimates")

        blocked = params.economic_recommendation == "NO_GO" or params.legal_recommendation == "NO_GO"
        needs_review = (
            params.economic_recommendation is None
            or params.legal_recommendation is None
            or params.economic_recommendation == "REVIEW"
            or params.legal_recommendation == "REVIEW"
        )

        if blocked:
            operations_status = "BLOCKED"
            recommendation = "NO_GO"
            confidence = 0.9
        elif needs_review:
            operations_status = "NEEDS_REVIEW"
            recommendation = "REVIEW"
            confidence = 0.4
        else:
            operations_status = "READY"
            recommendation = "GO"
            confidence = 0.85

        order_id = generate_order_id(product_id=params.product_name, market=params.market)
        tracking = generate_order_tracking(lead_time_days=params.lead_time_days)
        return_policy = generate_return_policy(market=params.market, sale_price=params.sale_price)
        support_ticket = classify_support_ticket(
            restricted=params.restricted, legal_recommendation=params.legal_recommendation
        )

        return AgentResult(
            status=AgentResultStatus.COMPLETED,
            recommendation=recommendation,
            confidence=confidence,
            evidence=[f"operations_status={operations_status} for {params.market}"],
            risks=risks,
            assumptions=[
                "order, tracking, returns, and support ticket are a single simulated illustrative example — "
                "no real orders, customers, CRM, ticketing, or carrier integration"
            ],
            data={
                "operations_status": operations_status,
                "order": {
                    "order_id": order_id,
                    "quantity": 1,
                    "tracking": tracking,
                },
                "supplier_coordination": {
                    "lead_time_days": params.lead_time_days,
                    "supplier_verified": params.supplier_verified,
                },
                "return_policy": return_policy,
                "support_ticket_example": support_ticket,
            },
        )
