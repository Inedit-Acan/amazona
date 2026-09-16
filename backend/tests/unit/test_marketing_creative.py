from app.marketing.creative import generate_ad_creative, generate_audience_segments, recommend_budget_action


def test_generate_audience_segments_is_deterministic_and_returns_two_or_three():
    first = generate_audience_segments(category="electronics", competition_level="low")
    second = generate_audience_segments(category="electronics", competition_level="low")

    assert first == second
    assert 2 <= len(first) <= 3
    for segment in first:
        assert {"name", "age_range", "interests", "estimated_reach"} == set(segment)


def test_generate_audience_segments_handles_missing_competition_level():
    segments = generate_audience_segments(category="home", competition_level=None)

    assert len(segments) >= 2


def test_generate_ad_creative_includes_product_name_and_a_text_image_brief():
    creative = generate_ad_creative(product_name="Wireless earbuds pro", category="electronics", sale_price=45.0)

    assert "Wireless earbuds pro" in creative["headline"] or "Wireless earbuds pro" in creative["primary_text"]
    assert isinstance(creative["image_brief"], str)
    assert len(creative["image_brief"]) > 0
    assert creative["cta"]


def test_generate_ad_creative_handles_missing_price():
    creative = generate_ad_creative(product_name="Wireless earbuds pro", category="electronics", sale_price=None)

    assert creative["headline"]


def test_recommend_budget_action_scales_up_on_strong_roas():
    action = recommend_budget_action(projected_roas=3.0)

    assert "increas" in action.lower() or "scal" in action.lower()


def test_recommend_budget_action_scales_down_on_weak_roas():
    action = recommend_budget_action(projected_roas=0.5)

    assert "reduc" in action.lower() or "pause" in action.lower()


def test_recommend_budget_action_handles_missing_roas():
    action = recommend_budget_action(projected_roas=None)

    assert "insufficient" in action.lower()
