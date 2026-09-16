from app.agents.base import Agent, AgentResult, AgentResultStatus

_MAX_ACCEPTABLE_LEAD_TIME_DAYS = 45


class SupplierAgent(Agent):
    """V1: deterministic supplier sourcing from structured input fixtures.
    No live supplier directory access."""

    capability = "supplier_sourcing"

    def run(self, task_input: dict) -> AgentResult:
        unit_cost = task_input.get("unit_cost")
        lead_time_days = task_input.get("lead_time_days")
        verified = bool(task_input.get("supplier_verified", False))

        if unit_cost is None or lead_time_days is None:
            return AgentResult(
                status=AgentResultStatus.COMPLETED,
                recommendation="REVIEW",
                confidence=0.3,
                evidence=[],
                risks=["missing supplier data"],
                assumptions=[],
                data={},
            )

        risks: list[str] = []
        if not verified:
            risks.append("supplier not verified")
        if lead_time_days > _MAX_ACCEPTABLE_LEAD_TIME_DAYS:
            risks.append("long lead time")

        if verified and lead_time_days <= _MAX_ACCEPTABLE_LEAD_TIME_DAYS:
            recommendation = "GO"
        elif verified:
            recommendation = "REVIEW"
        else:
            recommendation = "NO_GO"

        return AgentResult(
            status=AgentResultStatus.COMPLETED,
            recommendation=recommendation,
            confidence=0.85 if verified else 0.4,
            evidence=[f"unit cost {unit_cost}", f"lead time {lead_time_days} days"],
            risks=risks,
            assumptions=["quoted unit cost is FOB origin"],
            data={"unit_cost": unit_cost, "lead_time_days": lead_time_days, "supplier_verified": verified},
        )
