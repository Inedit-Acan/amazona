"""Deterministic marketplace listing content generator. No real listing
is ever published — this is a draft template, same placeholder standard
as app.legal.terms_template and app.ecommerce.content.
"""


def generate_listing_content(
    *, product_name: str, category: str, sale_price: float | None, competition_level: str | None
) -> dict:
    price_display = f"${sale_price:.2f}" if sale_price is not None else "TBD"
    hook = "Stand out from the crowd" if competition_level == "high" else "Backed by real demand"

    return {
        "title": f"{product_name} — {category.capitalize()} | {hook}",
        "bullet_points": [
            f"Category: {category}",
            f"Price: {price_display}",
            "Simulated listing draft — not published on any marketplace yet",
            "Quality checked during sourcing",
        ],
        "backend_keywords": [
            product_name.lower(),
            category.lower(),
            f"best {category.lower()}",
            f"{product_name.lower()} deal",
        ],
    }
