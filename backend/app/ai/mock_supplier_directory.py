"""Deterministic, fixture-driven global supplier directory. No network
access — this is a stand-in for a future real supplier directory API
(e.g. Alibaba/Made-in-China), used only to give the Supplier Sourcing
agent (Fase 3, Agent 2) something to rank.
"""

_SUPPLIER_DATASET: dict[str, list[dict]] = {
    "electronics": [
        {
            "name": "Shenzhen Volta Electronics",
            "region": "china",
            "unit_price": 4.2,
            "moq": 500,
            "lead_time_days": 25,
            "verified": True,
            "reliability_score": 0.88,
        },
        {
            "name": "Hanoi Circuit Works",
            "region": "vietnam",
            "unit_price": 4.6,
            "moq": 300,
            "lead_time_days": 20,
            "verified": True,
            "reliability_score": 0.81,
        },
        {
            "name": "Guadalajara ElectroPack",
            "region": "mexico",
            "unit_price": 5.9,
            "moq": 200,
            "lead_time_days": 12,
            "verified": False,
            "reliability_score": 0.55,
        },
    ],
    "home": [
        {
            "name": "Foshan Home Goods Co",
            "region": "china",
            "unit_price": 2.1,
            "moq": 1000,
            "lead_time_days": 30,
            "verified": True,
            "reliability_score": 0.79,
        },
        {
            "name": "Bratislava Homeware Supply",
            "region": "eu",
            "unit_price": 3.4,
            "moq": 250,
            "lead_time_days": 10,
            "verified": True,
            "reliability_score": 0.9,
        },
        {
            "name": "Monterrey Casa Distribution",
            "region": "mexico",
            "unit_price": 2.8,
            "moq": 400,
            "lead_time_days": 14,
            "verified": False,
            "reliability_score": 0.48,
        },
    ],
    "accessories": [
        {
            "name": "Yiwu Accessory Hub",
            "region": "china",
            "unit_price": 1.3,
            "moq": 1500,
            "lead_time_days": 28,
            "verified": True,
            "reliability_score": 0.72,
        },
        {
            "name": "Porto Leather & Co",
            "region": "eu",
            "unit_price": 3.9,
            "moq": 150,
            "lead_time_days": 9,
            "verified": True,
            "reliability_score": 0.93,
        },
    ],
}


class MockSupplierDirectory:
    """V1 stand-in for a real global supplier directory. Deterministic:
    the same (category, max_results) always returns the same result, in
    fixture order (ranking by cost happens in the agent, not here)."""

    def get_suppliers(self, *, category: str, max_results: int = 5) -> list[dict]:
        pool = _SUPPLIER_DATASET.get(category.lower(), [])
        return pool[:max_results]
