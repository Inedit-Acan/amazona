from app.agents.base import Agent, AgentResult

_COMPETITION_FACTOR = {"low": 1.0, "medium": 0.6, "high": 0.3}


class ProductAgent(Agent):
    """V1: deterministic market validation from structured input fixtures.
    No live web/search access."""

    capability = "market_validation"

    def run(self, task_input: dict) -> AgentResult:
        monthly_searches = task_input.get("estimated_monthly_searches")
        competition = task_input.get("competition_level")

        if not monthly_searches or competition not in _COMPETITION_FACTOR:
            return AgentResult(
                status="COMPLETED",
                recommendation="REVIEW",
                confidence=0.3,
                evidence=[],
                risks=["insufficient market data"],
                assumptions=[],
                data={"opportunity_score": 0.0},
            )

        competition_factor = _COMPETITION_FACTOR[competition]
        opportunity_score = round(min(1.0, (monthly_searches / 10000) * competition_factor), 4)
        confidence = 0.9 if monthly_searches >= 1000 else 0.5

        if opportunity_score >= 0.5:
            recommendation = "GO"
        elif opportunity_score >= 0.2:
            recommendation = "REVIEW"
        else:
            recommendation = "NO_GO"

        return AgentResult(
            status="COMPLETED",
            recommendation=recommendation,
            confidence=confidence,
            evidence=[
                f"estimated {monthly_searches} monthly searches",
                f"competition level: {competition}",
            ],
            risks=[] if competition_factor >= 0.6 else ["high competitive pressure"],
            assumptions=["search volume approximates demand"],
            data={"opportunity_score": opportunity_score},
        )
