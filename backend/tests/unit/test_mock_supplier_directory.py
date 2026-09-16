from app.ai.mock_supplier_directory import MockSupplierDirectory

_REQUIRED_FIELDS = {
    "name",
    "region",
    "unit_price",
    "moq",
    "lead_time_days",
    "verified",
    "reliability_score",
}


def test_same_category_returns_the_same_result():
    directory = MockSupplierDirectory()

    first = directory.get_suppliers(category="electronics", max_results=5)
    second = directory.get_suppliers(category="electronics", max_results=5)

    assert first == second


def test_different_categories_produce_different_suppliers():
    directory = MockSupplierDirectory()

    electronics = directory.get_suppliers(category="electronics", max_results=10)
    home = directory.get_suppliers(category="home", max_results=10)

    assert electronics != home
    assert {s["name"] for s in electronics}.isdisjoint({s["name"] for s in home})


def test_results_are_capped_at_max_results():
    directory = MockSupplierDirectory()

    results = directory.get_suppliers(category="electronics", max_results=2)

    assert len(results) <= 2


def test_unknown_category_returns_an_empty_list_not_an_error():
    directory = MockSupplierDirectory()

    results = directory.get_suppliers(category="does-not-exist", max_results=5)

    assert results == []


def test_each_supplier_has_the_required_shape_and_no_field_is_empty():
    directory = MockSupplierDirectory()

    for supplier in directory.get_suppliers(category="electronics", max_results=10):
        assert set(supplier) == _REQUIRED_FIELDS
        assert supplier["name"]
        assert supplier["region"]
        assert supplier["unit_price"] > 0
        assert supplier["moq"] > 0
        assert supplier["lead_time_days"] > 0
        assert isinstance(supplier["verified"], bool)
        assert 0.0 <= supplier["reliability_score"] <= 1.0


def test_categories_include_suppliers_from_multiple_regions():
    directory = MockSupplierDirectory()

    for category in ("electronics", "home", "accessories"):
        regions = {s["region"] for s in directory.get_suppliers(category=category, max_results=10)}
        assert len(regions) >= 2, f"{category} should offer suppliers from more than one region"
