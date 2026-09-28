"""El agente de sourcing sobre el contrato con procedencia (Milestone 39)."""

import pytest

from app.agents.base import AgentResultStatus
from app.agents.supplier_sourcing import SupplierSourcingAgent
from app.integrations.ports import SupplierOffer
from app.sourcing.provenance import SupplierFactProvenance

CANDIDATE_FIELDS = {
    "name",
    "region",
    "country",
    "city",
    "website",
    "unit_price",
    "currency",
    "quoted_unit",
    "quoted_quantity",
    "moq",
    "lead_time_days",
    "transit_days",
    "transport_mode",
    "incoterm",
    "payment_terms",
    "destination_market",
    "reliability",
    "provenance",
    "verification",
    "verified_by",
    "source",
    "logistics_cost_per_unit",
    "logistics_provenance",
    "total_landed_cost_per_unit",
    "landed_cost_missing",
    "notes",
}


class StubDirectory:
    """Un directorio que contesta lo que se le diga, para poder probar lo que el
    mock no puede producir: proveedores reales y ofertas incompletas."""

    name = "stub"

    def __init__(self, offers: list[SupplierOffer]) -> None:
        self._offers = offers

    def find_suppliers(self, *, category, destination_market, max_results=5):
        return self._offers[:max_results]


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


def test_fixture_suppliers_never_justify_a_go():
    """Hasta el Milestone 39 el mock decía `verified: True` y eso bastaba para
    recomendar GO. Un proveedor inventado no puede sostener una compra."""
    agent = SupplierSourcingAgent()

    result = agent.run({"category": "electronics", "destination_region": "mexico", "max_results": 10})

    assert result.recommendation == "REVIEW"
    assert any("fixture data" in risk for risk in result.risks)


def test_a_supplier_whose_identity_nobody_verified_generates_an_explicit_risk():
    agent = SupplierSourcingAgent(
        StubDirectory(
            [
                SupplierOffer(
                    name="Real Co",
                    provenance=SupplierFactProvenance.SUPPLIER_CLAIM,
                    source="https://real.example",
                    region="eu",
                    unit_price=3.0,
                    currency="EUR",
                    moq=10,
                    verification=SupplierFactProvenance.SUPPLIER_CLAIM,
                )
            ]
        )
    )

    result = agent.run({"category": "home", "destination_region": "eu", "max_results": 5})

    assert result.recommendation == "REVIEW"
    assert any("Real Co" in risk and "not verified" in risk for risk in result.risks)


def test_a_third_party_verified_supplier_can_justify_a_go():
    agent = SupplierSourcingAgent(
        StubDirectory(
            [
                SupplierOffer(
                    name="Audited Co",
                    provenance=SupplierFactProvenance.SUPPLIER_CLAIM,
                    source="https://audited.example",
                    region="eu",
                    unit_price=3.0,
                    currency="EUR",
                    moq=10,
                    verification=SupplierFactProvenance.THIRD_PARTY_VERIFIED,
                    verified_by="Bureau of Test",
                )
            ]
        )
    )

    result = agent.run({"category": "home", "destination_region": "eu", "max_results": 5})

    assert result.recommendation == "GO"


def test_an_offer_without_a_price_has_no_landed_cost_and_says_why():
    """Y no se ordena la primera: un coste ausente no es un coste de cero."""
    agent = SupplierSourcingAgent(
        StubDirectory(
            [
                SupplierOffer(
                    name="Silent Co",
                    provenance=SupplierFactProvenance.SUPPLIER_CLAIM,
                    source="https://silent.example",
                    region="eu",
                    verification=SupplierFactProvenance.SUPPLIER_CLAIM,
                ),
                SupplierOffer(
                    name="Priced Co",
                    provenance=SupplierFactProvenance.SUPPLIER_CLAIM,
                    source="https://priced.example",
                    region="eu",
                    unit_price=9.0,
                    currency="EUR",
                    moq=10,
                    verification=SupplierFactProvenance.SUPPLIER_CLAIM,
                ),
            ]
        )
    )

    result = agent.run({"category": "home", "destination_region": "eu", "max_results": 5})

    names = [c["name"] for c in result.data["candidates"]]
    assert names == ["Priced Co", "Silent Co"]

    silent = result.data["candidates"][1]
    assert silent["total_landed_cost_per_unit"] is None
    assert silent["logistics_cost_per_unit"] is None
    assert "did not publish a price" in silent["landed_cost_missing"]
    assert any("Silent Co" in risk and "no landed cost" in risk for risk in result.risks)


def test_a_price_cannot_be_declared_without_a_currency():
    with pytest.raises(ValueError, match="currency"):
        SupplierOffer(
            name="Ambiguous Co",
            provenance=SupplierFactProvenance.SUPPLIER_CLAIM,
            source="https://ambiguous.example",
            unit_price=4.0,
        )


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
        assert set(candidate) == CANDIDATE_FIELDS
        assert candidate["total_landed_cost_per_unit"] == round(
            candidate["unit_price"] + candidate["logistics_cost_per_unit"], 4
        )
        # El coste logístico lo calcula un estimador nuestro; el precio lo dice
        # la fuente. No comparten procedencia.
        assert candidate["logistics_provenance"] == SupplierFactProvenance.AMAZONA_ESTIMATE
        assert candidate["provenance"] == SupplierFactProvenance.SIMULATED
