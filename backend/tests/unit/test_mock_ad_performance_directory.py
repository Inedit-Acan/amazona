from app.ai.mock_ad_performance_directory import MockAdPerformanceDirectory

_REQUIRED_FIELDS = {"avg_cpc", "avg_ctr", "conversion_rate", "data_origin"}


def test_same_category_and_platform_returns_the_same_result():
    directory = MockAdPerformanceDirectory()

    first = directory.get_performance_estimate(category="electronics", platform="meta")
    second = directory.get_performance_estimate(category="electronics", platform="meta")

    assert first == second


def test_unknown_category_platform_pair_returns_none_not_an_error():
    directory = MockAdPerformanceDirectory()

    result = directory.get_performance_estimate(category="does-not-exist", platform="does-not-exist")

    assert result is None


def test_each_known_combination_has_the_required_shape_and_marks_data_origin():
    directory = MockAdPerformanceDirectory()

    for category in ("electronics", "home", "accessories"):
        for platform in ("meta", "google"):
            result = directory.get_performance_estimate(category=category, platform=platform)
            assert result is not None, f"{category}/{platform} should be a known fixture combination"
            assert set(result) == _REQUIRED_FIELDS
            assert result["data_origin"] == "simulated_ad_performance_estimate"
            assert result["avg_cpc"] > 0
            assert 0.0 < result["avg_ctr"] < 1.0
            assert 0.0 < result["conversion_rate"] < 1.0


def test_different_platforms_can_produce_different_estimates_for_the_same_category():
    directory = MockAdPerformanceDirectory()

    meta = directory.get_performance_estimate(category="electronics", platform="meta")
    google = directory.get_performance_estimate(category="electronics", platform="google")

    assert meta != google
