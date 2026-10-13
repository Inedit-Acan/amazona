"""Un escenario que no es un número real o no cabe como `Money` no se devuelve (M46, Commit 5c).

Antes `monthly_revenue = precio × volumen` desbordaba a `inf` y, al serializarse el resultado, salía como `null` en un
análisis «con éxito». Ahora `build_scenarios` falla en voz alta. No fija ningún máximo de negocio: lo que no cabe es lo
que `Money` no puede representar.
"""

import math

import pytest

from app.economics.scenarios import build_scenarios
from app.money.money import AmountNotRepresentableError


def _build(**overrides):
    args = dict(unit_landed_cost=5.56, sale_price=20.0, monthly_unit_sales_base=100.0, monthly_fixed_costs=500.0)
    return build_scenarios(**(args | overrides))


def test_a_normal_scenario_set_is_returned_with_real_numbers():
    scenarios = _build()

    assert set(scenarios) == {"conservative", "base", "optimistic"}
    for scenario in scenarios.values():
        values = (scenario.monthly_unit_sales, scenario.margin_percent)
        assert all(math.isfinite(value) for value in values)
        assert math.isfinite(scenario.monthly_revenue) and math.isfinite(scenario.monthly_profit)


def test_a_volume_whose_revenue_money_cannot_hold_fails_in_the_open():
    with pytest.raises(AmountNotRepresentableError):
        _build(monthly_unit_sales_base=1e308)


def test_each_scenario_is_checked_not_only_the_base_one():
    # base: 4e22 × 20 = 8e23 (cabe); optimistic: 1,3 × 4e22 × 20 = 1,04e24 (no cabe)
    with pytest.raises(AmountNotRepresentableError) as caught:
        _build(monthly_unit_sales_base=4e22)

    assert "optimistic" in str(caught.value)


def test_a_margin_that_is_not_a_real_number_fails_even_when_revenue_and_profit_are_finite():
    """Con un precio subnormal el margen se desborda a `-inf` mientras el ingreso y el beneficio siguen siendo finitos:
    solo la comprobación de finitud del escenario lo detecta."""
    with pytest.raises(AmountNotRepresentableError):
        _build(sale_price=1e-320, monthly_unit_sales_base=100.0, monthly_fixed_costs=0.0)


def test_the_error_does_not_repeat_the_values_received():
    with pytest.raises(AmountNotRepresentableError) as caught:
        _build(monthly_unit_sales_base=1.2345678e300)

    assert "1.2345678" not in str(caught.value)
