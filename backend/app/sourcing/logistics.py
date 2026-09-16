"""Deterministic, fixture-driven logistics cost estimator. Placeholder
until a real freight/customs rates provider is integrated — the factors
below are illustrative simulated figures, not real carrier tariffs or
tariffs owed to any customs authority.
"""

from pydantic import BaseModel

_SAME_REGION_SHIPPING_COST_PER_UNIT = 0.15

# Simulated freight cost per unit, keyed by (origin_region, destination_region).
# Not derived from any real carrier's rate card.
_SHIPPING_COST_PER_UNIT: dict[tuple[str, str], float] = {
    ("china", "mexico"): 0.9,
    ("china", "eu"): 0.7,
    ("china", "vietnam"): 0.3,
    ("china", "china"): _SAME_REGION_SHIPPING_COST_PER_UNIT,
    ("vietnam", "mexico"): 0.85,
    ("vietnam", "eu"): 0.75,
    ("vietnam", "china"): 0.3,
    ("mexico", "eu"): 0.95,
    ("mexico", "mexico"): _SAME_REGION_SHIPPING_COST_PER_UNIT,
    ("eu", "mexico"): 0.95,
    ("eu", "eu"): _SAME_REGION_SHIPPING_COST_PER_UNIT,
}
_UNKNOWN_REGION_SHIPPING_COST_PER_UNIT = 1.5

# Simulated customs/duties multiplier applied to declared unit cost, keyed
# by destination region. 1.0 == no duty. Not real tariff schedules.
_CUSTOMS_FACTOR: dict[str, float] = {
    "china": 1.10,
    "vietnam": 1.08,
    "mexico": 1.16,
    "eu": 1.12,
}
_UNKNOWN_REGION_CUSTOMS_FACTOR = 1.25


class LogisticsEstimate(BaseModel):
    shipping_cost_per_unit: float
    customs_factor: float
    estimated_total_logistics_cost: float
    notes: str


def estimate_logistics_cost(
    *, origin_region: str, destination_region: str, unit_cost: float, moq: int
) -> LogisticsEstimate:
    origin = origin_region.lower()
    destination = destination_region.lower()

    if origin == destination:
        shipping_cost_per_unit = _SAME_REGION_SHIPPING_COST_PER_UNIT
    else:
        shipping_cost_per_unit = _SHIPPING_COST_PER_UNIT.get(
            (origin, destination), _UNKNOWN_REGION_SHIPPING_COST_PER_UNIT
        )

    customs_factor = _CUSTOMS_FACTOR.get(destination, _UNKNOWN_REGION_CUSTOMS_FACTOR)

    shipping_total = shipping_cost_per_unit * moq
    customs_total = unit_cost * (customs_factor - 1) * moq
    estimated_total_logistics_cost = round(shipping_total + customs_total, 4)

    notes = (
        f"simulated freight {origin}->{destination} + simulated customs factor "
        f"for {destination}; not derived from real carrier or tariff data"
    )

    return LogisticsEstimate(
        shipping_cost_per_unit=shipping_cost_per_unit,
        customs_factor=customs_factor,
        estimated_total_logistics_cost=estimated_total_logistics_cost,
        notes=notes,
    )
