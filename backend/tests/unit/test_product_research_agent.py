from app.agents.base import AgentResult
from app.agents.product_research import ProductResearchAgent
from app.agents.registry import build_default_agent_manager


def assert_is_valid_result(result: AgentResult) -> None:
    assert isinstance(result, AgentResult)
    assert 0.0 <= result.confidence <= 1.0
    assert isinstance(result.data.get("candidates"), list)


def test_known_category_returns_candidates_ranked_by_opportunity_score():
    agent = ProductResearchAgent()

    result = agent.run({"category": "electronics", "max_results": 3})

    assert_is_valid_result(result)
    candidates = result.data["candidates"]
    assert 1 <= len(candidates) <= 3
    scores = [c["opportunity_score"] for c in candidates]
    assert scores == sorted(scores, reverse=True)
    assert agent.capability == "product_research"


def test_each_candidate_has_the_expected_fields():
    agent = ProductResearchAgent()

    result = agent.run({"category": "home", "max_results": 5})

    for candidate in result.data["candidates"]:
        assert set(candidate) == {
            "name",
            "category",
            "opportunity_score",
            "demand_signal",
            "competition_level",
            "niche_rationale",
        }
        assert candidate["category"] == "home"


def test_unknown_category_yields_no_candidates_and_low_confidence_review():
    agent = ProductResearchAgent()

    result = agent.run({"category": "does-not-exist", "max_results": 5})

    assert_is_valid_result(result)
    assert result.data["candidates"] == []
    assert result.recommendation == "REVIEW"
    assert result.confidence < 0.5
    assert result.risks


def test_high_competition_candidates_are_flagged_as_a_risk():
    agent = ProductResearchAgent()

    result = agent.run({"category": "accessories", "max_results": 5})

    candidates = result.data["candidates"]
    high_competition_names = {c["name"] for c in candidates if c["competition_level"] == "high"}
    if high_competition_names:
        assert any(name in risk for risk in result.risks for name in high_competition_names)


def test_keywords_narrow_the_candidate_pool():
    agent = ProductResearchAgent()

    result = agent.run({"category": "electronics", "keywords": ["earbuds"], "max_results": 5})

    names = [c["name"].lower() for c in result.data["candidates"]]
    assert all("earbuds" in name for name in names)


def test_product_research_agent_is_registered_in_the_default_agent_manager():
    registry, manager = build_default_agent_manager()

    agents = registry.find_by_capability("product_research")
    assert len(agents) == 1
    selected = manager.select_agent("product_research")
    assert selected.capabilities == ["product_research"]
