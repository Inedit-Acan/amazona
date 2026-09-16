from app.legal.terms_template import generate_terms_and_conditions


def test_same_input_returns_the_same_text():
    first = generate_terms_and_conditions(category="electronics", market="eu", product_name="Wireless earbuds")
    second = generate_terms_and_conditions(category="electronics", market="eu", product_name="Wireless earbuds")

    assert first == second


def test_text_includes_product_category_and_market():
    text = generate_terms_and_conditions(category="electronics", market="eu", product_name="Wireless earbuds")

    assert "Wireless earbuds" in text
    assert "electronics" in text
    assert "eu" in text


def test_text_includes_a_placeholder_disclaimer():
    text = generate_terms_and_conditions(category="electronics", market="eu", product_name="Wireless earbuds")

    lowered = text.lower()
    assert "template" in lowered or "placeholder" in lowered
    assert "not legal advice" in lowered
