from app.ai.mock_regulatory_directory import MockRegulatoryDirectory

_REQUIRED_FIELDS = {"restricted", "required_certifications", "known_risks", "recent_changes"}


def test_same_category_and_market_returns_the_same_result():
    directory = MockRegulatoryDirectory()

    first = directory.get_requirements(category="electronics", market="eu")
    second = directory.get_requirements(category="electronics", market="eu")

    assert first == second


def test_unknown_category_market_pair_returns_none_not_an_error():
    directory = MockRegulatoryDirectory()

    result = directory.get_requirements(category="does-not-exist", market="does-not-exist")

    assert result is None


def test_different_markets_can_produce_different_requirements_for_the_same_category():
    directory = MockRegulatoryDirectory()

    us = directory.get_requirements(category="electronics", market="us")
    eu = directory.get_requirements(category="electronics", market="eu")

    assert us != eu


def test_at_least_one_combination_is_restricted_with_required_certifications():
    directory = MockRegulatoryDirectory()

    combinations = [
        directory.get_requirements(category=category, market=market)
        for category in ("electronics", "home", "accessories")
        for market in ("us", "eu", "mx")
    ]
    restricted_with_certs = [
        c for c in combinations if c is not None and c["restricted"] and c["required_certifications"]
    ]

    assert restricted_with_certs, "at least one fixture combination should be restricted+certified"


def test_each_known_combination_has_the_required_shape():
    directory = MockRegulatoryDirectory()

    for category in ("electronics", "home", "accessories"):
        for market in ("us", "eu", "mx"):
            result = directory.get_requirements(category=category, market=market)
            assert result is not None, f"{category}/{market} should be a known fixture combination"
            assert set(result) == _REQUIRED_FIELDS
            assert isinstance(result["restricted"], bool)
            assert isinstance(result["required_certifications"], list)
            assert isinstance(result["known_risks"], list)
            assert isinstance(result["recent_changes"], list)
            for change in result["recent_changes"]:
                assert set(change) == {"date", "description"}
