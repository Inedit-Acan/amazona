from pydantic import BaseModel

from app.agents.base import Agent, AgentResult, AgentResultStatus


class CFOReportInput(BaseModel):
    total_products_analyzed: int
    go_count: int
    review_count: int
    no_go_count: int
    total_campaigns: int
    active_campaigns: int
    total_daily_budget: float
    total_budget_hard_limit: float
    total_reserved: float
    total_committed: float
    total_spent: float


class CFOAgent(Agent):
    """Fase 3, Agente CFO: consolidates the real, already-persisted output of
    EconomicAnalysis (Agente 3) and MarketingCampaign (Agente 7) across the
    whole catalog, plus BudgetEngine's reservations (Budget/BudgetAllocation),
    into one aggregate financial-health report. Unlike Agents 3-8, this is
    catalog-wide, not per-product — it has no "validate-one" or "discover-one"
    scope, and no product/market input. Consumes real data resolved by
    CFOService; it never touches the DB itself.

    Never emits invoices — this agent is aggregate reporting only. Real
    billing/invoicing must go through a certified Verifactu-compliant
    third-party system, which is out of scope for this agent entirely."""

    capability = "cfo_financial_health_report"
    input_schema = CFOReportInput

    def run(self, task_input: dict) -> AgentResult:
        params = CFOReportInput.model_validate(task_input)

        risks: list[str] = []
        evidence: list[str] = []

        if params.total_budget_hard_limit > 0:
            budget_utilization = (
                params.total_reserved + params.total_committed + params.total_spent
            ) / params.total_budget_hard_limit
        else:
            budget_utilization = None
            risks.append(
                "no budget reservations recorded yet: BudgetEngine currently authorizes/reserves budget "
                "in-memory per approval and is not yet persisted to budget_allocations/financial_events"
            )

        if params.total_products_analyzed == 0:
            risks.append("insufficient data: no economic analyses found across the catalog yet")
            financial_health_status = "NEEDS_REVIEW"
            recommendation = "REVIEW"
            confidence = 0.3
            no_go_ratio = None
        else:
            no_go_ratio = params.no_go_count / params.total_products_analyzed
            evidence.append(
                f"{params.total_products_analyzed} products analyzed: "
                f"{params.go_count} GO, {params.review_count} REVIEW, {params.no_go_count} NO_GO"
            )

            if no_go_ratio > 0.5:
                risks.append(f"risk concentration: {no_go_ratio:.0%} of analyzed products are NO_GO")
                financial_health_status = "CRITICAL"
                recommendation = "NO_GO"
                confidence = 0.9
            elif no_go_ratio > 0.2 or (budget_utilization is not None and budget_utilization > 0.9):
                if no_go_ratio > 0.2:
                    risks.append(f"elevated risk concentration: {no_go_ratio:.0%} of analyzed products are NO_GO")
                if budget_utilization is not None and budget_utilization > 0.9:
                    risks.append(f"budget utilization is high: {budget_utilization:.0%} of the hard limit")
                financial_health_status = "AT_RISK"
                recommendation = "REVIEW"
                confidence = 0.6
            else:
                financial_health_status = "HEALTHY"
                recommendation = "GO"
                confidence = 0.85

        evidence.append(
            f"{params.active_campaigns}/{params.total_campaigns} campaigns active, "
            f"${params.total_daily_budget:.2f} total daily budget"
        )

        return AgentResult(
            status=AgentResultStatus.COMPLETED,
            recommendation=recommendation,
            confidence=confidence,
            evidence=evidence,
            risks=risks,
            assumptions=[
                "aggregate reporting only — this agent never emits invoices; real billing must go "
                "through a certified Verifactu-compliant third-party system",
                "budget reservation totals reflect budget_allocations/financial_events rows only, "
                "which nothing currently writes to (BudgetEngine's authorize/reserve flow is in-memory "
                "per orchestrator objective)",
            ],
            data={
                "financial_health_status": financial_health_status,
                "no_go_ratio": no_go_ratio,
                "budget_utilization": budget_utilization,
                "total_products_analyzed": params.total_products_analyzed,
                "go_count": params.go_count,
                "review_count": params.review_count,
                "no_go_count": params.no_go_count,
                "total_campaigns": params.total_campaigns,
                "active_campaigns": params.active_campaigns,
                "total_daily_budget": params.total_daily_budget,
                "total_budget_hard_limit": params.total_budget_hard_limit,
                "total_reserved": params.total_reserved,
                "total_committed": params.total_committed,
                "total_spent": params.total_spent,
            },
        )
