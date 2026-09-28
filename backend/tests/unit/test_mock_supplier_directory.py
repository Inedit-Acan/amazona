"""El directorio de fixtures, con el contrato del Milestone 39 (ADR 0017).

Lo que este fichero comprueba además de la forma: que **las cifras no han
cambiado**. Es la regla del Milestone 30 —el mock no se elimina y sigue dando
exactamente lo mismo— y aquí importa el doble, porque si un precio del fixture
se hubiera movido de paso, cualquier diferencia que apareciera después en una
pantalla sería inexplicable.
"""

import pytest

from app.ai.mock_supplier_directory import CURRENCY, SOURCE, MockSupplierDirectory
from app.sourcing.provenance import SupplierFactProvenance

#: Precio, MOQ, plazo y fiabilidad de cada proveedor de `electronics`, tal y
#: como estaban antes de la ADR 0017. Escritos a mano aquí: comparar contra el
#: propio fixture no comprobaría nada.
ELECTRONICS_BEFORE_M39 = [
    ("Shenzhen Volta Electronics", "china", 4.2, 500, 25, 0.88),
    ("Hanoi Circuit Works", "vietnam", 4.6, 300, 20, 0.81),
    ("Guadalajara ElectroPack", "mexico", 5.9, 200, 12, 0.55),
]


@pytest.fixture()
def directory() -> MockSupplierDirectory:
    return MockSupplierDirectory()


def find(directory: MockSupplierDirectory, category: str, max_results: int = 10):
    return directory.find_suppliers(
        category=category, destination_market="eu", max_results=max_results
    )


def test_same_category_returns_the_same_result(directory):
    assert find(directory, "electronics", 5) == find(directory, "electronics", 5)


def test_different_categories_produce_different_suppliers(directory):
    electronics = find(directory, "electronics")
    home = find(directory, "home")

    assert electronics != home
    assert {s.name for s in electronics}.isdisjoint({s.name for s in home})


def test_results_are_capped_at_max_results(directory):
    assert len(find(directory, "electronics", 2)) <= 2


def test_unknown_category_returns_an_empty_list_not_an_error(directory):
    assert find(directory, "does-not-exist", 5) == []


def test_the_figures_are_exactly_the_ones_from_before_milestone_39(directory):
    offers = find(directory, "electronics")

    actual = [(o.name, o.region, o.unit_price, o.moq, o.lead_time_days, o.reliability) for o in offers]
    assert actual == ELECTRONICS_BEFORE_M39


def test_every_offer_says_it_is_a_fixture(directory):
    """Antes decía `verified: True` con la misma cara con la que lo diría un
    registro mercantil. Ahora dice lo que es."""
    for offer in find(directory, "electronics"):
        assert offer.provenance is SupplierFactProvenance.SIMULATED
        assert offer.verification is SupplierFactProvenance.SIMULATED
        assert offer.source == SOURCE


def test_a_price_always_carries_its_currency(directory):
    """Un precio sin moneda no se puede comparar con ningún otro."""
    for offer in find(directory, "electronics"):
        assert offer.unit_price is not None
        assert offer.currency == CURRENCY


def test_what_the_fixture_does_not_know_stays_unsaid(directory):
    """El fixture no sabe el Incoterm ni las condiciones de pago ni si el
    proveedor hace envío ciego, y no se los inventa. Rellenarlos habría metido
    ocho afirmaciones falsas por proveedor en la pantalla."""
    for offer in find(directory, "electronics"):
        assert offer.incoterm is None
        assert offer.payment_terms is None
        assert offer.country is None
        assert offer.city is None
        assert offer.capabilities == ()


def test_categories_include_suppliers_from_multiple_regions(directory):
    for category in ("electronics", "home", "accessories"):
        regions = {s.region for s in find(directory, category)}
        assert len(regions) >= 2, f"{category} should offer suppliers from more than one region"
