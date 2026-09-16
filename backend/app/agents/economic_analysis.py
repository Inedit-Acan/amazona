from pydantic import BaseModel

from app.agents.base import Agent, AgentResult, AgentResultStatus
from app.economics.scenarios import build_scenarios, estimate_monthly_unit_sales

_MAX_ACCEPTABLE_LEAD_TIME_DAYS = 45


class EconomicAnalysisInput(BaseModel):
    unit_landed_cost: float
    sale_price: float
    demand_signal: float | None = None
    monthly_unit_sales_base: float | None = None
    monthly_fixed_costs: float = 500.0
    supplier_verified: bool | None = None
    lead_time_days: int | None = None
    competition_level: str | None = None


class EconomicAnalysisAgent(Agent):
    """Fase 3, Agente 3: computes landed cost, margin, three deterministic
    scenarios (conservative/base/optimistic), and risk flags for an
    already-researched product + already-sourced supplier — unlike
    FinanceAgent, which validates a single already-committed financial
    scenario within an objective's task graph. See ADR 0004. Consumes
    real research/sourcing data resolved by EconomicAnalysisService; it
    never touches the DB itself."""

    capability = "economic_risk_analysis"
    input_schema = EconomicAnalysisInput

    def run(self, task_input: dict) -> AgentResult:
        params = EconomicAnalysisInput.model_validate(task_input)

        monthly_unit_sales_base = params.monthly_unit_sales_base
        if monthly_unit_sales_base is None and params.demand_signal is not None:
            monthly_unit_sales_base = estimate_monthly_unit_sales(params.demand_signal)

        if monthly_unit_sales_base is None:
            return AgentResult(
                status=AgentResultStatus.COMPLETED,
                recommendation="REVIEW",
                confidence=0.3,
                evidence=[],
                risks=["insufficient demand data: no demand_signal or monthly_unit_sales_base provided"],
                assumptions=[],
                data={"scenarios": {}},
            )

        scenarios = build_scenarios(
            unit_landed_cost=params.unit_landed_cost,
            sale_price=params.sale_price,
            monthly_unit_sales_base=monthly_unit_sales_base,
            monthly_fixed_costs=params.monthly_fixed_costs,
        )

        margin_percent = scenarios["base"].margin_percent
        if margin_percent < 0:
            recommendation = "NO_GO"
        elif scenarios["base"].monthly_profit < 0:
            recommendation = "NO_GO"
        elif scenarios["conservative"].monthly_profit < 0:
            recommendation = "REVIEW"
        else:
            recommendation = "GO"

        risks: list[str] = []
        if margin_percent < 0:
            risks.append("negative margin")
        if params.supplier_verified is False:
            risks.append("supplier not verified")
        if params.lead_time_days is not None and params.lead_time_days > _MAX_ACCEPTABLE_LEAD_TIME_DAYS:
            risks.append("long lead time")
        if params.competition_level == "high":
            risks.append("high competition")

        return AgentResult(
            status=AgentResultStatus.COMPLETED,
            recommendation=recommendation,
            confidence=0.85 if params.demand_signal is not None or params.monthly_unit_sales_base else 0.5,
            evidence=[
                f"{name}: margin {s.margin_percent:.2%}, monthly profit {s.monthly_profit:.2f}"
                for name, s in scenarios.items()
            ],
            risks=risks,
            assumptions=[
                "demand-to-sales conversion and scenario volume factors are simulated placeholders"
            ],
            data={"scenarios": {name: s.model_dump() for name, s in scenarios.items()}},
        )
