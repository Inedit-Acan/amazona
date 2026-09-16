"""Deterministic e-commerce content generators. No real store, no real
payment processor, no live traffic — placeholders in the same spirit as
MockTrendsProvider / estimate_logistics_cost / terms_template. Going to
a real payment gateway's live mode is never automated here — it always
requires explicit human approval, same standard as any simulated
high-impact action elsewhere in this system.
"""

import re

_PAYMENT_GATEWAYS_BY_MARKET: dict[str, dict] = {
    "us": {
        "gateway": "Stripe",
        "checklist": [
            "Create a Stripe test-mode account",
            "Configure webhook endpoint for order events",
            "Verify business details",
            "Switch to live mode (requires human approval)",
        ],
    },
    "eu": {
        "gateway": "Stripe/Adyen",
        "checklist": [
            "Create a test-mode account with the chosen provider",
            "Configure SCA-compliant checkout flow",
            "Verify VAT/business registration details",
            "Switch to live mode (requires human approval)",
        ],
    },
    "mx": {
        "gateway": "Mercado Pago",
        "checklist": [
            "Create a Mercado Pago test-mode account",
            "Configure webhook endpoint for order events",
            "Verify RFC/business registration details",
            "Switch to live mode (requires human approval)",
        ],
    },
}
_DEFAULT_PAYMENT_GATEWAY = {
    "gateway": "generic test-mode gateway",
    "checklist": [
        "Create a test-mode account with a locally supported provider",
        "Configure webhook endpoint for order events",
        "Verify business registration details for this market",
        "Switch to live mode (requires human approval)",
    ],
}

_THIN_MARGIN_THRESHOLD = 0.2


def generate_store_slug(product_name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", product_name.lower()).strip("-")
    return f"{slug}-store"


def generate_landing_page_copy(
    *, product_name: str, category: str, sale_price: float | None, competition_level: str | None
) -> dict:
    price_display = f"${sale_price:.2f}" if sale_price is not None else "TBD"
    differentiation = (
        "built to stand out in a crowded market"
        if competition_level == "high"
        else "backed by real demand research"
    )

    return {
        "headline": f"{product_name} — {differentiation}",
        "subheadline": f"A carefully sourced {category} pick, ready to ship.",
        "price_display": price_display,
        "bullets": [
            f"Category: {category}",
            f"Price: {price_display}",
            "Simulated storefront draft — not a live store yet",
        ],
        "cta": "Shop now",
    }


def generate_payment_gateway_plan(market: str) -> dict:
    plan = _PAYMENT_GATEWAYS_BY_MARKET.get(market.lower(), _DEFAULT_PAYMENT_GATEWAY)
    return {
        "gateway": plan["gateway"],
        "mode": "test",
        "checklist": list(plan["checklist"]),
        "requires_human_approval": True,
    }


def generate_conversion_tips(*, margin_percent: float | None, competition_level: str | None) -> list[str]:
    tips: list[str] = []

    if margin_percent is not None and margin_percent < _THIN_MARGIN_THRESHOLD:
        tips.append(
            f"Margin is thin ({margin_percent:.1%}) — consider a higher price point or highlighting value "
            "over price in the landing page copy."
        )
    else:
        tips.append("Margin supports promotional pricing or bundling if needed.")

    if competition_level == "high":
        tips.append("High competition detected — lead with differentiation, not price, in the headline.")

    return tips
