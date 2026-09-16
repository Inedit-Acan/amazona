from app.economics.scenarios import build_scenarios, estimate_monthly_unit_sales


def test_estimate_monthly_unit_sales_is_deterministic():
    first = estimate_monthly_unit_sales(0.65)
    second = estimate_monthly_unit_sales(0.65)

    assert first == second


def test_estimate_monthly_unit_sales_increases_with_demand_signal():
    low = estimate_monthly_unit_sales(0.2)
    high = estimate_monthly_unit_sales(0.8)

    assert high > low


def test_build_scenarios_returns_the_three_expected_keys():
    scenarios = build_scenarios(
        unit_landed_cost=5.0, sale_price=20.0, monthly_unit_sales_base=300.0, monthly_fixed_costs=500.0
    )

    assert set(scenarios) == {"conservative", "base", "optimistic"}


def test_build_scenarios_optimistic_profit_exceeds_base_exceeds_conservative():
    scenarios = build_scenarios(
        unit_landed_cost=5.0, sale_price=20.0, monthly_unit_sales_base=300.0, monthly_fixed_costs=500.0
    )

    assert (
        scenarios["optimistic"].monthly_profit
        > scenarios["base"].monthly_profit
        > scenarios["conservative"].monthly_profit
    )


def test_build_scenarios_margin_percent_is_the_same_across_scenarios():
    scenarios = build_scenarios(
        unit_landed_cost=5.0, sale_price=20.0, monthly_unit_sales_base=300.0, monthly_fixed_costs=500.0
    )

    assert scenarios["conservative"].margin_percent == scenarios["base"].margin_percent
    assert scenarios["base"].margin_percent == scenarios["optimistic"].margin_percent


def test_build_scenarios_negative_margin_when_cost_exceeds_price():
    scenarios = build_scenarios(
        unit_landed_cost=25.0, sale_price=20.0, monthly_unit_sales_base=300.0, monthly_fixed_costs=500.0
    )

    assert scenarios["conservative"].margin_percent < 0
    assert scenarios["base"].margin_percent < 0
    assert scenarios["optimistic"].margin_percent < 0


def test_build_scenarios_computes_revenue_and_profit_correctly_for_base():
    scenarios = build_scenarios(
        unit_landed_cost=5.0, sale_price=20.0, monthly_unit_sales_base=300.0, monthly_fixed_costs=500.0
    )

    base = scenarios["base"]
    assert base.monthly_revenue == 20.0 * 300.0
    assert base.monthly_profit == (20.0 - 5.0) * 300.0 - 500.0
