from app.ecommerce.content import (
    generate_conversion_tips,
    generate_landing_page_copy,
    generate_payment_gateway_plan,
    generate_store_slug,
)


def test_generate_store_slug_is_deterministic_lowercase_and_hyphenated():
    first = generate_store_slug("Travel Cable Organizer", "abcd1234-...")
    second = generate_store_slug("Travel Cable Organizer", "abcd1234-...")

    assert first == second
    assert first == first.lower()
    assert " " not in first
    assert first == "travel-cable-organizer-abcd1234-store"


def test_generate_store_slug_strips_special_characters():
    slug = generate_store_slug("Wireless Earbuds Pro!! (2026)", "abcd1234-...")

    assert all(c.isalnum() or c == "-" for c in slug)


def test_generate_store_slug_differs_for_the_same_name_with_different_product_ids():
    first = generate_store_slug("Silicone kitchen organizer", "11111111-aaaa")
    second = generate_store_slug("Silicone kitchen organizer", "22222222-bbbb")

    assert first != second


def test_generate_landing_page_copy_includes_product_name():
    copy = generate_landing_page_copy(
        product_name="Wireless earbuds pro", category="electronics", sale_price=20.0, competition_level="low"
    )

    assert "Wireless earbuds pro" in copy["headline"] or "Wireless earbuds pro" in copy["subheadline"]
    assert copy["price_display"] == "$20.00"


def test_generate_landing_page_copy_handles_missing_price():
    copy = generate_landing_page_copy(
        product_name="Wireless earbuds pro", category="electronics", sale_price=None, competition_level=None
    )

    assert copy["price_display"] == "TBD"


def test_generate_payment_gateway_plan_always_requires_human_approval_for_known_markets():
    for market in ("us", "eu", "mx"):
        plan = generate_payment_gateway_plan(market)
        assert plan["requires_human_approval"] is True
        assert plan["mode"] == "test"
        assert plan["checklist"]


def test_generate_payment_gateway_plan_unknown_market_returns_a_generic_plan_not_an_error():
    plan = generate_payment_gateway_plan("does-not-exist")

    assert plan["requires_human_approval"] is True
    assert plan["gateway"]


def test_generate_conversion_tips_flags_thin_margin():
    thin = generate_conversion_tips(margin_percent=0.1, competition_level=None)
    healthy = generate_conversion_tips(margin_percent=0.6, competition_level=None)

    assert any("margin" in tip.lower() for tip in thin)
    assert thin != healthy


def test_generate_conversion_tips_flags_high_competition():
    tips = generate_conversion_tips(margin_percent=0.6, competition_level="high")

    assert any("competition" in tip.lower() or "differentiat" in tip.lower() for tip in tips)
