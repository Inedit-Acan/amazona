from app.ai.mock_marketplace_directory import MockMarketplaceDirectory

_REQUIRED_TOP_FIELDS = {"competition", "commission", "policy"}
_REQUIRED_COMPETITION_FIELDS = {
    "competitor_count",
    "avg_price",
    "avg_rating",
    "buy_box_difficulty",
    "data_origin",
}
_REQUIRED_COMMISSION_FIELDS = {"referral_fee_percent", "fulfillment_fee_per_unit"}
_REQUIRED_POLICY_FIELDS = {"approval_required", "prohibited", "notes"}


def test_same_category_and_platform_returns_the_same_result():
    directory = MockMarketplaceDirectory()

    first = directory.get_marketplace_data(category="electronics", platform="amazon")
    second = directory.get_marketplace_data(category="electronics", platform="amazon")

    assert first == second


def test_unknown_category_platform_pair_returns_none_not_an_error():
    directory = MockMarketplaceDirectory()

    result = directory.get_marketplace_data(category="does-not-exist", platform="does-not-exist")

    assert result is None


def test_at_least_one_combination_requires_category_approval():
    directory = MockMarketplaceDirectory()

    combinations = [
        directory.get_marketplace_data(category=category, platform="amazon")
        for category in ("electronics", "home", "accessories")
    ]
    requiring_approval = [c for c in combinations if c is not None and c["policy"]["approval_required"]]

    assert requiring_approval, "at least one fixture combination should require category approval"


def test_each_known_combination_has_the_required_shape_and_marks_data_origin():
    directory = MockMarketplaceDirectory()

    for category in ("electronics", "home", "accessories"):
        result = directory.get_marketplace_data(category=category, platform="amazon")
        assert result is not None, f"{category}/amazon should be a known fixture combination"
        assert set(result) == _REQUIRED_TOP_FIELDS
        assert set(result["competition"]) == _REQUIRED_COMPETITION_FIELDS
        assert result["competition"]["data_origin"] == "simulated_not_sp_api"
        assert set(result["commission"]) == _REQUIRED_COMMISSION_FIELDS
        assert set(result["policy"]) == _REQUIRED_POLICY_FIELDS
