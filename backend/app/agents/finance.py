from app.agents.base import Agent, AgentResult, AgentResultStatus


class FinanceAgent(Agent):
    """V1: deterministic financial validation from structured input
    fixtures. No live accounting/tax integration; all figures simulated."""

    capability = "financial_validation"

    def run(self, task_input: dict) -> AgentResult:
        unit_cost = task_input.get("unit_cost")
        sale_price = task_input.get("sale_price")

        if unit_cost is None or not sale_price:
            return AgentResult(
                status=AgentResultStatus.COMPLETED,
                recommendation="REVIEW",
                confidence=0.3,
                evidence=[],
                risks=["missing financial data"],
                assumptions=[],
                data={"finance_veto": False},
            )

        monthly_unit_sales = task_input.get("monthly_unit_sales", 0)
        monthly_fixed_costs = task_input.get("monthly_fixed_costs", 0.0)

        margin = (sale_price - unit_cost) / sale_price
        monthly_profit = (sale_price - unit_cost) * monthly_unit_sales - monthly_fixed_costs
        finance_veto = margin < 0

        if finance_veto:
            recommendation = "NO_GO"
        elif monthly_profit > 0:
            recommendation = "GO"
        else:
            recommendation = "REVIEW"

        return AgentResult(
            status=AgentResultStatus.COMPLETED,
            recommendation=recommendation,
            confidence=0.9 if monthly_unit_sales > 0 else 0.4,
            evidence=[
                f"margin {margin:.2%}",
                f"projected monthly profit {monthly_profit:.2f}",
            ],
            risks=["negative margin"] if finance_veto else [],
            assumptions=["monthly fixed costs held constant"],
            data={"margin": margin, "monthly_profit": monthly_profit, "finance_veto": finance_veto},
        )
