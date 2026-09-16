from app.agents.base import AgentResultStatus
from app.agents.supplier_sourcing import SupplierSourcingAgent


def test_candidates_are_ranked_by_total_landed_cost_ascending():
    agent = SupplierSourcingAgent()

    result = agent.run({"category": "electronics", "destination_region": "mexico", "max_results": 5})

    candidates = result.data["candidates"]
    assert len(candidates) >= 2
    costs = [c["total_landed_cost_per_unit"] for c in candidates]
    assert costs == sorted(costs)


def test_max_results_caps_the_number_of_candidates():
    agent = SupplierSourcingAgent()

    result = agent.run({"category": "electronics", "destination_region": "mexico", "max_results": 1})

    assert len(result.data["candidates"]) == 1


def test_unverified_suppliers_generate_an_explicit_risk():
    agent = SupplierSourcingAgent()

    result = agent.run({"category": "electronics", "destination_region": "mexico", "max_results": 10})

    unverified = [c for c in result.data["candidates"] if not c["verified"]]
    assert unverified, "fixture should include at least one unverified supplier for this test to be meaningful"
    for candidate in unverified:
        assert any(candidate["name"] in risk for risk in result.risks)


def test_unknown_category_returns_completed_with_review_and_no_candidates():
    agent = SupplierSourcingAgent()

    result = agent.run({"category": "does-not-exist", "destination_region": "mexico", "max_results": 5})

    assert result.status == AgentResultStatus.COMPLETED
    assert result.recommendation == "REVIEW"
    assert result.data["candidates"] == []
    assert result.risks


def test_each_candidate_has_the_required_shape():
    agent = SupplierSourcingAgent()

    result = agent.run({"category": "home", "destination_region": "eu", "max_results": 10})

    for candidate in result.data["candidates"]:
        assert set(candidate) == {
            "name",
            "region",
            "unit_price",
            "moq",
            "lead_time_days",
            "verified",
            "reliability_score",
            "logistics_cost_per_unit",
            "total_landed_cost_per_unit",
            "notes",
        }
        assert candidate["total_landed_cost_per_unit"] == round(
            candidate["unit_price"] + candidate["logistics_cost_per_unit"], 4
        )
