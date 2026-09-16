from app.agents.base import AgentResultStatus
from app.agents.legal_compliance import LegalComplianceAgent


def test_restricted_category_without_certification_is_blocked():
    agent = LegalComplianceAgent()

    result = agent.run(
        {
            "category": "accessories",
            "market": "eu",
            "product_name": "Leather phone strap",
            "certification_available": False,
        }
    )

    assert result.status == AgentResultStatus.BLOCKED
    assert result.recommendation == "NO_GO"
    assert result.data["restricted"] is True


def test_required_certification_missing_but_not_restricted_is_review():
    agent = LegalComplianceAgent()

    result = agent.run(
        {
            "category": "electronics",
            "market": "us",
            "product_name": "Wireless earbuds",
            "certification_available": False,
        }
    )

    assert result.recommendation == "REVIEW"
    assert result.data["restricted"] is False


def test_no_certification_required_and_no_risks_is_a_go():
    agent = LegalComplianceAgent()

    result = agent.run(
        {
            "category": "accessories",
            "market": "us",
            "product_name": "Travel cable organizer",
            "certification_available": False,
        }
    )

    assert result.recommendation == "GO"


def test_unverified_supplier_with_origin_region_adds_a_cross_border_risk():
    agent = LegalComplianceAgent()

    result = agent.run(
        {
            "category": "accessories",
            "market": "us",
            "product_name": "Travel cable organizer",
            "supplier_verified": False,
            "origin_region": "china",
        }
    )

    assert any("cross-border" in risk for risk in result.risks)


def test_recent_regulatory_changes_are_surfaced_as_a_risk():
    agent = LegalComplianceAgent()

    result = agent.run(
        {"category": "electronics", "market": "eu", "product_name": "Wireless earbuds"}
    )

    assert any("regulatory change" in risk for risk in result.risks)


def test_unknown_category_market_pair_returns_review_with_insufficient_data_risk():
    agent = LegalComplianceAgent()

    result = agent.run(
        {"category": "does-not-exist", "market": "does-not-exist", "product_name": "Mystery item"}
    )

    assert result.status == AgentResultStatus.COMPLETED
    assert result.recommendation == "REVIEW"
    assert result.risks


def test_data_includes_generated_terms_and_conditions():
    agent = LegalComplianceAgent()

    result = agent.run(
        {"category": "home", "market": "mx", "product_name": "Kitchen organizer"}
    )

    assert "Kitchen organizer" in result.data["terms_and_conditions"]
