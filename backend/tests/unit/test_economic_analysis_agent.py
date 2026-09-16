from app.agents.base import AgentResultStatus
from app.agents.economic_analysis import EconomicAnalysisAgent


def test_negative_base_margin_is_a_no_go():
    agent = EconomicAnalysisAgent()

    result = agent.run(
        {"unit_landed_cost": 25.0, "sale_price": 20.0, "monthly_unit_sales_base": 300.0}
    )

    assert result.recommendation == "NO_GO"
    assert result.data["scenarios"]["base"]["margin_percent"] < 0


def test_positive_margin_but_negative_base_profit_is_no_go():
    agent = EconomicAnalysisAgent()

    # margin_percent is positive, but fixed costs swamp the expected
    # (base) volume's contribution — loses money even in the expected
    # case, not just under a downside scenario.
    result = agent.run(
        {
            "unit_landed_cost": 19.0,
            "sale_price": 20.0,
            "monthly_unit_sales_base": 300.0,
            "monthly_fixed_costs": 500.0,
        }
    )

    assert result.recommendation == "NO_GO"
    assert result.data["scenarios"]["base"]["margin_percent"] > 0
    assert result.data["scenarios"]["base"]["monthly_profit"] < 0


def test_positive_base_profit_but_negative_conservative_profit_is_review():
    agent = EconomicAnalysisAgent()

    # base (1.0x volume) is profitable, but conservative (0.7x volume)
    # dips below zero once fixed costs are subtracted — profitable in the
    # expected case, but not resilient to a downside scenario.
    result = agent.run(
        {
            "unit_landed_cost": 10.0,
            "sale_price": 20.0,
            "monthly_unit_sales_base": 60.0,
            "monthly_fixed_costs": 500.0,
        }
    )

    assert result.recommendation == "REVIEW"
    assert result.data["scenarios"]["base"]["monthly_profit"] > 0
    assert result.data["scenarios"]["conservative"]["monthly_profit"] < 0


def test_healthy_margin_with_no_risks_is_a_go():
    agent = EconomicAnalysisAgent()

    result = agent.run(
        {
            "unit_landed_cost": 5.0,
            "sale_price": 20.0,
            "monthly_unit_sales_base": 300.0,
            "monthly_fixed_costs": 500.0,
            "supplier_verified": True,
            "lead_time_days": 20,
            "competition_level": "low",
        }
    )

    assert result.recommendation == "GO"
    assert result.risks == []


def test_unverified_supplier_generates_a_risk():
    agent = EconomicAnalysisAgent()

    result = agent.run(
        {
            "unit_landed_cost": 5.0,
            "sale_price": 20.0,
            "monthly_unit_sales_base": 300.0,
            "supplier_verified": False,
        }
    )

    assert any("not verified" in risk for risk in result.risks)


def test_long_lead_time_generates_a_risk():
    agent = EconomicAnalysisAgent()

    result = agent.run(
        {
            "unit_landed_cost": 5.0,
            "sale_price": 20.0,
            "monthly_unit_sales_base": 300.0,
            "lead_time_days": 60,
        }
    )

    assert any("lead time" in risk for risk in result.risks)


def test_high_competition_generates_a_risk():
    agent = EconomicAnalysisAgent()

    result = agent.run(
        {
            "unit_landed_cost": 5.0,
            "sale_price": 20.0,
            "monthly_unit_sales_base": 300.0,
            "competition_level": "high",
        }
    )

    assert any("competition" in risk for risk in result.risks)


def test_demand_signal_is_converted_when_no_explicit_sales_base_given():
    agent = EconomicAnalysisAgent()

    result = agent.run({"unit_landed_cost": 5.0, "sale_price": 20.0, "demand_signal": 0.65})

    assert result.data["scenarios"]["base"]["monthly_unit_sales"] > 0


def test_missing_demand_data_returns_review_with_explicit_risk():
    agent = EconomicAnalysisAgent()

    result = agent.run({"unit_landed_cost": 5.0, "sale_price": 20.0})

    assert result.status == AgentResultStatus.COMPLETED
    assert result.recommendation == "REVIEW"
    assert result.risks
