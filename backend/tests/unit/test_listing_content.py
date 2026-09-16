from app.marketplace.listing_content import generate_listing_content


def test_same_input_returns_the_same_result():
    first = generate_listing_content(
        product_name="Travel cable organizer", category="accessories", sale_price=20.0, competition_level="low"
    )
    second = generate_listing_content(
        product_name="Travel cable organizer", category="accessories", sale_price=20.0, competition_level="low"
    )

    assert first == second


def test_title_includes_product_name():
    content = generate_listing_content(
        product_name="Travel cable organizer", category="accessories", sale_price=20.0, competition_level="low"
    )

    assert "Travel cable organizer" in content["title"]


def test_handles_missing_price_and_competition_level():
    content = generate_listing_content(
        product_name="Travel cable organizer", category="accessories", sale_price=None, competition_level=None
    )

    assert content["title"]
    assert content["bullet_points"]
    assert content["backend_keywords"]


def test_bullet_points_and_keywords_are_non_empty_lists():
    content = generate_listing_content(
        product_name="Wireless earbuds pro", category="electronics", sale_price=45.0, competition_level="high"
    )

    assert isinstance(content["bullet_points"], list) and len(content["bullet_points"]) > 0
    assert isinstance(content["backend_keywords"], list) and len(content["backend_keywords"]) > 0
