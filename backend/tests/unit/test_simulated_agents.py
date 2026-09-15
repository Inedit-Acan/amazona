from app.agents.base import AgentResult
from app.agents.finance import FinanceAgent
from app.agents.legal import LegalAgent
from app.agents.product import ProductAgent
from app.agents.registry import build_default_agent_manager
from app.agents.supplier import SupplierAgent


def assert_is_valid_result(result: AgentResult) -> None:
    assert isinstance(result, AgentResult)
    assert result.recommendation
    assert 0.0 <= result.confidence <= 1.0
    assert isinstance(result.evidence, list)
    assert isinstance(result.risks, list)
    assert isinstance(result.assumptions, list)
    assert isinstance(result.data, dict)


def test_product_agent_recommends_go_for_a_strong_opportunity():
    agent = ProductAgent()
    result = agent.run(
        {"product_name": "Wireless earbuds", "estimated_monthly_searches": 12000, "competition_level": "low"}
    )

    assert_is_valid_result(result)
    assert agent.capability == "market_validation"
    assert result.recommendation == "GO"


def test_product_agent_flags_review_when_data_is_missing():
    agent = ProductAgent()
    result = agent.run({"product_name": "Unknown gadget"})

    assert_is_valid_result(result)
    assert result.recommendation == "REVIEW"
    assert result.confidence < 0.5


def test_supplier_agent_recommends_go_for_a_verified_fast_supplier():
    agent = SupplierAgent()
    result = agent.run(
        {"unit_cost": 4.2, "min_order_quantity": 500, "lead_time_days": 20, "supplier_verified": True}
    )

    assert_is_valid_result(result)
    assert agent.capability == "supplier_sourcing"
    assert result.recommendation == "GO"


def test_supplier_agent_flags_unverified_supplier_as_a_risk():
    agent = SupplierAgent()
    result = agent.run(
        {"unit_cost": 4.2, "min_order_quantity": 500, "lead_time_days": 20, "supplier_verified": False}
    )

    assert_is_valid_result(result)
    assert result.recommendation != "GO"
    assert "supplier not verified" in result.risks


def test_finance_agent_recommends_go_for_a_profitable_product():
    agent = FinanceAgent()
    result = agent.run(
        {"unit_cost": 5.0, "sale_price": 20.0, "monthly_unit_sales": 300, "monthly_fixed_costs": 500.0}
    )

    assert_is_valid_result(result)
    assert agent.capability == "financial_validation"
    assert result.recommendation == "GO"
    assert result.data["finance_veto"] is False


def test_finance_agent_vetoes_a_negative_margin_product():
    agent = FinanceAgent()
    result = agent.run(
        {"unit_cost": 25.0, "sale_price": 20.0, "monthly_unit_sales": 300, "monthly_fixed_costs": 500.0}
    )

    assert_is_valid_result(result)
    assert result.recommendation == "NO_GO"
    assert result.data["finance_veto"] is True


def test_legal_agent_clears_a_standard_category():
    agent = LegalAgent()
    result = agent.run({"restricted_category": False, "requires_certification": False})

    assert_is_valid_result(result)
    assert agent.capability == "legal_validation"
    assert result.status == "COMPLETED"
    assert result.data["legal_status"] == "CLEAR"


def test_legal_agent_blocks_a_restricted_category_without_certification():
    agent = LegalAgent()
    result = agent.run(
        {"restricted_category": True, "requires_certification": True, "certification_available": False}
    )

    assert_is_valid_result(result)
    assert result.status == "BLOCKED"
    assert result.recommendation == "NO_GO"
    assert result.data["legal_status"] == "BLOCKED"


def test_default_agent_manager_registers_all_four_specialists():
    registry, manager = build_default_agent_manager()

    for capability in ["market_validation", "supplier_sourcing", "financial_validation", "legal_validation"]:
        agents = registry.find_by_capability(capability)
        assert len(agents) == 1
        selected = manager.select_agent(capability)
        assert selected.capabilities == [capability]
