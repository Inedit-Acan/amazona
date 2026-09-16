"""Deterministic marketing creative/audience/budget-tip generators. No
real ad platform integration, no generated images — `image_brief` is a
text specification for a human or design tool to execute, never a
generated bitmap. Same placeholder standard as the rest of the project.
"""

_ROAS_STRONG_THRESHOLD = 2.0
_ROAS_WEAK_THRESHOLD = 1.0


def generate_audience_segments(*, category: str, competition_level: str | None) -> list[dict]:
    base_segments = [
        {
            "name": f"{category.capitalize()} enthusiasts",
            "age_range": "25-44",
            "interests": [category, "online shopping"],
            "estimated_reach": 250000,
        },
        {
            "name": f"{category.capitalize()} gift shoppers",
            "age_range": "35-54",
            "interests": [category, "gifting"],
            "estimated_reach": 120000,
        },
    ]
    if competition_level == "low":
        base_segments.append(
            {
                "name": f"Early adopters — {category}",
                "age_range": "18-34",
                "interests": [category, "new products"],
                "estimated_reach": 80000,
            }
        )
    return base_segments


def generate_ad_creative(*, product_name: str, category: str, sale_price: float | None) -> dict:
    price_display = f"${sale_price:.2f}" if sale_price is not None else "great price"

    return {
        "headline": f"{product_name}: the {category} upgrade you'll actually use",
        "primary_text": (
            f"Meet {product_name} — carefully sourced, priced at {price_display}. "
            "Simulated ad copy draft, not published on any ad platform yet."
        ),
        "cta": "Shop now",
        "image_brief": (
            f"Lifestyle product shot of {product_name} in a clean, well-lit setting typical of the "
            f"{category} category. Square (1:1) and vertical (4:5) crops. Text overlay: none. "
            "This is a text brief for a designer/human — no image has been generated."
        ),
    }


def recommend_budget_action(*, projected_roas: float | None) -> str:
    if projected_roas is None:
        return "insufficient data to recommend a budget change — run pricing/legal analyses first"
    if projected_roas >= _ROAS_STRONG_THRESHOLD:
        return f"ROAS is strong ({projected_roas:.1f}x) — consider increasing daily budget to scale"
    if projected_roas < _ROAS_WEAK_THRESHOLD:
        return f"ROAS is weak ({projected_roas:.1f}x) — reduce budget or pause until creative/pricing improves"
    return f"ROAS is acceptable ({projected_roas:.1f}x) — hold budget steady and monitor"
