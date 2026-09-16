from app.ai.mock_trends_provider import MockTrendsProvider


def test_same_query_returns_the_same_result():
    provider = MockTrendsProvider()

    first = provider.get_candidates(category="electronics", keywords=["earbuds"], max_results=3)
    second = provider.get_candidates(category="electronics", keywords=["earbuds"], max_results=3)

    assert first == second


def test_different_categories_produce_different_signals():
    provider = MockTrendsProvider()

    electronics = provider.get_candidates(category="electronics", max_results=5)
    home = provider.get_candidates(category="home", max_results=5)

    assert electronics != home
    assert {c["name"] for c in electronics}.isdisjoint({c["name"] for c in home})


def test_results_are_capped_at_max_results():
    provider = MockTrendsProvider()

    results = provider.get_candidates(category="electronics", max_results=2)

    assert len(results) <= 2


def test_results_are_ordered_by_demand_signal_descending():
    provider = MockTrendsProvider()

    results = provider.get_candidates(category="electronics", max_results=10)

    demand_signals = [c["demand_signal"] for c in results]
    assert demand_signals == sorted(demand_signals, reverse=True)


def test_unknown_category_returns_an_empty_list_not_an_error():
    provider = MockTrendsProvider()

    results = provider.get_candidates(category="does-not-exist", max_results=5)

    assert results == []


def test_keywords_filter_to_matching_candidates_when_any_match_exists():
    provider = MockTrendsProvider()

    all_results = provider.get_candidates(category="electronics", max_results=10)
    filtered = provider.get_candidates(category="electronics", keywords=["earbuds"], max_results=10)

    assert len(filtered) <= len(all_results)
    assert all("earbuds" in c["name"].lower() or "earbuds" in c["niche_rationale"].lower() for c in filtered)


def test_each_candidate_has_the_required_shape():
    provider = MockTrendsProvider()

    for candidate in provider.get_candidates(category="electronics", max_results=10):
        assert set(candidate) == {"name", "demand_signal", "competition_level", "niche_rationale"}
        assert 0.0 <= candidate["demand_signal"] <= 1.0
        assert candidate["competition_level"] in {"low", "medium", "high"}
