from pydantic import BaseModel, Field

from app.agents.base import Agent, AgentResult, AgentResultStatus
from app.ai.mock_trends_provider import MockTrendsProvider

_COMPETITION_FACTOR = {"low": 1.0, "medium": 0.6, "high": 0.3}


class ProductResearchInput(BaseModel):
    category: str
    keywords: list[str] = Field(default_factory=list)
    max_results: int = Field(default=5, ge=1, le=20)


class ProductResearchAgent(Agent):
    """Fase 3, Agente 1: discovers and ranks *multiple* candidate products
    for a category/niche (unlike ProductAgent, which validates a single
    given product). V1: MockTrendsProvider only, no live web/search."""

    capability = "product_research"
    input_schema = ProductResearchInput

    def __init__(self, trends_provider: MockTrendsProvider | None = None) -> None:
        self._trends = trends_provider or MockTrendsProvider()

    def run(self, task_input: dict) -> AgentResult:
        params = ProductResearchInput.model_validate(task_input)
        raw_candidates = self._trends.get_candidates(
            category=params.category, keywords=params.keywords, max_results=params.max_results
        )

        if not raw_candidates:
            return AgentResult(
                status=AgentResultStatus.COMPLETED,
                recommendation="REVIEW",
                confidence=0.3,
                evidence=[],
                risks=[f"no trend data available for category {params.category!r}"],
                assumptions=[],
                data={"candidates": []},
            )

        ranked = sorted(
            (
                {
                    "name": c["name"],
                    "category": params.category,
                    "opportunity_score": round(
                        c["demand_signal"] * _COMPETITION_FACTOR.get(c["competition_level"], 0.3), 4
                    ),
                    "demand_signal": c["demand_signal"],
                    "competition_level": c["competition_level"],
                    # 3 additional simulated radar axes (docs/design/
                    # AMAZONA_handoff_backend_paneles_pendientes.md §3) —
                    # informational only, do not feed opportunity_score or
                    # the GO/REVIEW recommendation below.
                    "future_outlook_signal": c["future_outlook_signal"],
                    "regulatory_risk_signal": c["regulatory_risk_signal"],
                    "scalability_signal": c["scalability_signal"],
                    "niche_rationale": c["niche_rationale"],
                }
                for c in raw_candidates
            ),
            key=lambda c: c["opportunity_score"],
            reverse=True,
        )

        top_score = ranked[0]["opportunity_score"]
        recommendation = "GO" if top_score >= 0.5 else "REVIEW"
        confidence = 0.85 if len(ranked) >= 2 else 0.5

        risks = [f"{c['name']}: high competition" for c in ranked if c["competition_level"] == "high"]

        return AgentResult(
            status=AgentResultStatus.COMPLETED,
            recommendation=recommendation,
            confidence=confidence,
            evidence=[f"{c['name']}: opportunity score {c['opportunity_score']}" for c in ranked],
            risks=risks,
            assumptions=["demand_signal approximates real market demand"],
            data={"candidates": ranked},
        )
