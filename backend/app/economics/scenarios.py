"""Deterministic, documented-placeholder economic scenario math. No
network access, no real market data — a stand-in for a future real
demand-forecasting/pricing model, in the same spirit as
MockTrendsProvider and estimate_logistics_cost.
"""

import math

from pydantic import BaseModel

from app.money.money import AmountNotRepresentableError, Money

# demand_signal (0-1, same scale MockTrendsProvider uses) -> estimated
# monthly unit sales. Derived as estimated_monthly_searches (demand_signal
# * 15000, the same conversion the CEO page's Research handoff already
# uses) times a placeholder search-to-sale conversion rate. Not a real
# market conversion rate.
_ESTIMATED_MONTHLY_SEARCHES_FACTOR = 15000.0
_SEARCH_TO_SALE_CONVERSION_RATE = 0.025

# Scenario volume multipliers applied to monthly_unit_sales_base. Fixed,
# documented placeholders — not derived from any real forecast model.
_SCENARIO_FACTORS = {
    "conservative": 0.7,
    "base": 1.0,
    "optimistic": 1.3,
}


class ScenarioResult(BaseModel):
    monthly_unit_sales: float
    margin_percent: float
    monthly_revenue: float
    monthly_profit: float


def estimate_monthly_unit_sales(demand_signal: float) -> float:
    estimated_monthly_searches = demand_signal * _ESTIMATED_MONTHLY_SEARCHES_FACTOR
    return estimated_monthly_searches * _SEARCH_TO_SALE_CONVERSION_RATE


def _require_a_real_result(name: str, scenario: "ScenarioResult") -> None:
    """Un escenario cuyo volumen, margen, ingreso o beneficio no es un número real o no cabe como `Money` no se
    devuelve: antes `monthly_revenue = precio × volumen` desbordaba a `inf` y, al serializarse, salía como `null`
    **en silencio** dentro de un análisis con éxito. Dos entradas individualmente válidas pueden dar un importe que
    no se puede representar; el análisis falla en voz alta en vez de callar. No fija ningún máximo de negocio: lo que
    no cabe es lo que `Money` no puede representar (ver `AmountNotRepresentableError`).
    """
    finite = math.isfinite(scenario.monthly_unit_sales) and math.isfinite(scenario.margin_percent)
    if not finite or not (
        Money.can_represent(scenario.monthly_revenue) and Money.can_represent(scenario.monthly_profit)
    ):
        raise AmountNotRepresentableError(
            f"the {name} scenario produces an amount that cannot be represented as money: the values received "
            "are individually valid but not together"
        )


def build_scenarios(
    *,
    unit_landed_cost: float,
    sale_price: float,
    monthly_unit_sales_base: float,
    monthly_fixed_costs: float,
) -> dict[str, ScenarioResult]:
    margin_percent = (sale_price - unit_landed_cost) / sale_price

    scenarios: dict[str, ScenarioResult] = {}
    for name, factor in _SCENARIO_FACTORS.items():
        monthly_unit_sales = monthly_unit_sales_base * factor
        monthly_revenue = sale_price * monthly_unit_sales
        monthly_profit = (sale_price - unit_landed_cost) * monthly_unit_sales - monthly_fixed_costs
        result = ScenarioResult(
            monthly_unit_sales=monthly_unit_sales,
            margin_percent=margin_percent,
            monthly_revenue=monthly_revenue,
            monthly_profit=monthly_profit,
        )
        _require_a_real_result(name, result)
        scenarios[name] = result
    return scenarios
