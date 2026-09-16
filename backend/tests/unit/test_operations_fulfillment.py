from app.operations.fulfillment import (
    classify_support_ticket,
    generate_order_id,
    generate_order_tracking,
    generate_return_policy,
)


def test_generate_order_id_is_deterministic_and_varies_by_product_and_market():
    first = generate_order_id(product_id="abc123", market="us")
    second = generate_order_id(product_id="abc123", market="us")
    different_market = generate_order_id(product_id="abc123", market="eu")

    assert first == second
    assert first != different_market


def test_generate_order_tracking_uses_a_default_lead_time_when_none_given():
    tracking = generate_order_tracking(lead_time_days=None)

    assert tracking["stages"]
    stage_names = [s["stage"] for s in tracking["stages"]]
    assert stage_names == ["order_placed", "processing", "shipped", "out_for_delivery", "delivered"]


def test_generate_order_tracking_reflects_a_real_lead_time():
    short = generate_order_tracking(lead_time_days=5)
    long = generate_order_tracking(lead_time_days=40)

    short_delivered = next(s for s in short["stages"] if s["stage"] == "delivered")["day_offset"]
    long_delivered = next(s for s in long["stages"] if s["stage"] == "delivered")["day_offset"]
    assert long_delivered > short_delivered


def test_generate_return_policy_computes_refund_estimate_from_real_sale_price():
    # mx applies a restocking fee, so the refund estimate is strictly less
    # than the sale price.
    policy = generate_return_policy(market="mx", sale_price=50.0)

    assert policy["refund_estimate"] is not None
    assert policy["refund_estimate"] < 50.0
    assert 0 <= policy["restocking_fee_percent"] < 1


def test_generate_return_policy_handles_missing_sale_price():
    policy = generate_return_policy(market="us", sale_price=None)

    assert policy["refund_estimate"] is None
    assert policy["eligibility_window_days"] > 0


def test_classify_support_ticket_escalates_restricted_categories_to_a_human():
    ticket = classify_support_ticket(restricted=True, legal_recommendation="NO_GO")

    assert ticket["ai_resolvable"] is False
    assert ticket["escalation_reason"]


def test_classify_support_ticket_is_ai_resolvable_when_clear():
    ticket = classify_support_ticket(restricted=False, legal_recommendation="GO")

    assert ticket["ai_resolvable"] is True
    assert ticket["escalation_reason"] is None


def test_classify_support_ticket_escalates_when_legal_status_unknown():
    ticket = classify_support_ticket(restricted=None, legal_recommendation=None)

    assert ticket["ai_resolvable"] is False
    assert ticket["escalation_reason"]
