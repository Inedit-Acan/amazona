"""Deterministic order fulfillment, returns, and support-ticket-triage
generators. No real orders, no real CRM/ticketing/carrier integration —
same placeholder standard as the rest of the project. Every simulated
order/ticket here is a single illustrative example, not a queue of real
customer orders.
"""

import hashlib

_DEFAULT_LEAD_TIME_DAYS = 14
_PROCESSING_BUFFER_DAYS = 1
_DELIVERY_BUFFER_DAYS = 3

_RETURN_POLICY_BY_MARKET: dict[str, dict] = {
    "us": {"eligibility_window_days": 30, "restocking_fee_percent": 0.0},
    "eu": {"eligibility_window_days": 14, "restocking_fee_percent": 0.0},
    "mx": {"eligibility_window_days": 30, "restocking_fee_percent": 0.10},
}
_DEFAULT_RETURN_POLICY = {"eligibility_window_days": 30, "restocking_fee_percent": 0.10}


def generate_order_id(*, product_id: str, market: str) -> str:
    digest = hashlib.sha256(f"{product_id}:{market}".encode()).hexdigest()[:10]
    return f"ORD-{digest}"


def generate_order_tracking(*, lead_time_days: int | None) -> dict:
    ship_day = lead_time_days if lead_time_days is not None else _DEFAULT_LEAD_TIME_DAYS
    stages = [
        {"stage": "order_placed", "day_offset": 0},
        {"stage": "processing", "day_offset": _PROCESSING_BUFFER_DAYS},
        {"stage": "shipped", "day_offset": ship_day},
        {"stage": "out_for_delivery", "day_offset": ship_day + _DELIVERY_BUFFER_DAYS - 1},
        {"stage": "delivered", "day_offset": ship_day + _DELIVERY_BUFFER_DAYS},
    ]
    return {"stages": stages, "lead_time_days_used": ship_day}


def generate_return_policy(*, market: str, sale_price: float | None) -> dict:
    policy = _RETURN_POLICY_BY_MARKET.get(market.lower(), _DEFAULT_RETURN_POLICY)
    refund_estimate = None
    if sale_price is not None:
        refund_estimate = round(sale_price * (1 - policy["restocking_fee_percent"]), 2)
    return {
        "eligibility_window_days": policy["eligibility_window_days"],
        "restocking_fee_percent": policy["restocking_fee_percent"],
        "refund_estimate": refund_estimate,
    }


def classify_support_ticket(*, restricted: bool | None, legal_recommendation: str | None) -> dict:
    if restricted is None or legal_recommendation is None:
        return {
            "ticket_type": "compliance_question",
            "ai_resolvable": False,
            "escalation_reason": "legal/compliance status unknown for this product/market — escalate to a human",
        }
    if restricted or legal_recommendation != "GO":
        return {
            "ticket_type": "compliance_question",
            "ai_resolvable": False,
            "escalation_reason": "restricted or non-cleared category — compliance questions require human review",
        }
    return {
        "ticket_type": "order_status_inquiry",
        "ai_resolvable": True,
        "escalation_reason": None,
    }
