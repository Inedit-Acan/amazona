"""Deterministic, fixture-driven trend/niche signals. No network access —
this is a stand-in for a future real trends/search API, used only to give
the Product Research agent (Fase 3, Agent 1) something to rank.

Three axes added alongside the original demand_signal/competition_level
(same fixture pattern, still zero external calls — see docs/design/
AMAZONA_handoff_backend_paneles_pendientes.md §3):
- future_outlook_signal: 0-1, higher = stronger growth trajectory.
- regulatory_risk_signal: 0-1, higher = MORE regulatory risk (certs,
  safety/shipping restrictions) — inverted to a favorability score by
  the radar chart, not here, so this field keeps its literal meaning.
- scalability_signal: 0-1, higher = easier to scale manufacturing/
  fulfillment for this product.
"""

_TREND_DATASET: dict[str, list[dict]] = {
    "electronics": [
        {
            "name": "Wireless earbuds pro",
            "demand_signal": 0.82,
            "competition_level": "medium",
            "future_outlook_signal": 0.78,
            "regulatory_risk_signal": 0.35,
            "scalability_signal": 0.75,
            "niche_rationale": "High search volume for wireless earbuds with active noise cancellation.",
        },
        {
            "name": "Smart water bottle",
            "demand_signal": 0.65,
            "competition_level": "low",
            "future_outlook_signal": 0.70,
            "regulatory_risk_signal": 0.30,
            "scalability_signal": 0.60,
            "niche_rationale": "Growing interest in hydration tracking, few established brands.",
        },
        {
            "name": "Portable phone charger",
            "demand_signal": 0.58,
            "competition_level": "high",
            "future_outlook_signal": 0.45,
            "regulatory_risk_signal": 0.50,
            "scalability_signal": 0.80,
            "niche_rationale": "Steady evergreen demand but a saturated, price-competitive category.",
        },
        {
            "name": "Mini projector",
            "demand_signal": 0.41,
            "competition_level": "medium",
            "future_outlook_signal": 0.55,
            "regulatory_risk_signal": 0.40,
            "scalability_signal": 0.50,
            "niche_rationale": "Seasonal spikes around home entertainment, moderate competition.",
        },
    ],
    "home": [
        {
            "name": "Silicone kitchen organizer",
            "demand_signal": 0.71,
            "competition_level": "low",
            "future_outlook_signal": 0.60,
            "regulatory_risk_signal": 0.20,
            "scalability_signal": 0.85,
            "niche_rationale": "Consistent demand for kitchen storage solutions, fragmented competition.",
        },
        {
            "name": "LED strip lights",
            "demand_signal": 0.69,
            "competition_level": "high",
            "future_outlook_signal": 0.65,
            "regulatory_risk_signal": 0.45,
            "scalability_signal": 0.80,
            "niche_rationale": "Popular ambient lighting category, many established sellers.",
        },
        {
            "name": "Collapsible laundry basket",
            "demand_signal": 0.44,
            "competition_level": "low",
            "future_outlook_signal": 0.40,
            "regulatory_risk_signal": 0.15,
            "scalability_signal": 0.70,
            "niche_rationale": "Niche but steady demand for space-saving home goods.",
        },
    ],
    "accessories": [
        {
            "name": "Minimalist phone case",
            "demand_signal": 0.55,
            "competition_level": "high",
            "future_outlook_signal": 0.50,
            "regulatory_risk_signal": 0.15,
            "scalability_signal": 0.90,
            "niche_rationale": "Evergreen accessory category, differentiation mostly on design.",
        },
        {
            "name": "Travel cable organizer",
            "demand_signal": 0.48,
            "competition_level": "low",
            "future_outlook_signal": 0.62,
            "regulatory_risk_signal": 0.15,
            "scalability_signal": 0.75,
            "niche_rationale": "Growing with remote work/travel trends, few dedicated brands.",
        },
    ],
}


class MockTrendsProvider:
    """V1 stand-in for a real trends/search data source. Deterministic:
    the same (category, keywords, max_results) always returns the same
    result, ordered by demand_signal descending."""

    def get_candidates(
        self,
        *,
        category: str,
        keywords: list[str] | None = None,
        max_results: int = 5,
    ) -> list[dict]:
        pool = _TREND_DATASET.get(category.lower(), [])

        if keywords:
            lowered_keywords = [k.lower() for k in keywords]
            matching = [
                candidate
                for candidate in pool
                if any(
                    kw in candidate["name"].lower() or kw in candidate["niche_rationale"].lower()
                    for kw in lowered_keywords
                )
            ]
            if matching:
                pool = matching

        ranked = sorted(pool, key=lambda c: c["demand_signal"], reverse=True)
        return ranked[:max_results]
