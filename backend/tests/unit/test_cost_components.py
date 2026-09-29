"""Los cinco estados de un coste, y la protección contra contar dos veces
(Milestone 40, ADR 0018)."""

import pytest

from app.economics.components import (
    CostBreakdown,
    CostConcept,
    CostStatus,
    DoubleCountingError,
    check_invariants,
    included_in,
    known,
    not_applicable,
    unknown_optional,
    unknown_required,
)
from app.money.money import Money
from app.sourcing.provenance import SupplierFactProvenance

CLAIM = SupplierFactProvenance.SUPPLIER_CLAIM
ESTIMATE = SupplierFactProvenance.AMAZONA_ESTIMATE


def euros(amount: str) -> Money:
    return Money.of(amount, "EUR")


def full(**overrides):
    """Un desglose completo de web propia, con lo que se quiera cambiar."""
    components = {
        CostConcept.PRODUCT: known(CostConcept.PRODUCT, euros("4.20"), provenance=CLAIM),
        CostConcept.LOGISTICS: known(CostConcept.LOGISTICS, euros("1.02"), provenance=ESTIMATE),
        CostConcept.IMPORT: included_in(CostConcept.IMPORT, CostConcept.LOGISTICS),
        CostConcept.CHANNEL: not_applicable(CostConcept.CHANNEL, "web propia: no hay comisión"),
        CostConcept.PAYMENT: known(CostConcept.PAYMENT, euros("0.83"), provenance=CLAIM),
        CostConcept.OTHER_VARIABLE: unknown_optional(CostConcept.OTHER_VARIABLE),
    }
    components.update(overrides)
    return CostBreakdown(components=tuple(components.values()))


# --- los cinco estados -------------------------------------------------------


def test_known_is_the_only_state_that_enters_the_sum():
    component = known(CostConcept.PRODUCT, euros("4.20"), provenance=CLAIM)

    assert component.status is CostStatus.KNOWN
    assert component.counts
    assert not component.blocks_evaluation


def test_included_in_another_does_not_sum_and_is_not_zero():
    """Está pagado y contado, en otro sitio. Sumarlo lo contaría dos veces;
    llamarlo cero diría que no existe."""
    component = included_in(CostConcept.IMPORT, CostConcept.PRODUCT)

    assert component.status is CostStatus.INCLUDED_IN_ANOTHER
    assert component.included_in is CostConcept.PRODUCT
    assert not component.counts
    assert not component.blocks_evaluation
    assert component.amount is None


def test_not_applicable_is_a_claim_about_the_scenario():
    component = not_applicable(CostConcept.CHANNEL, "una web propia no paga comisión")

    assert component.status is CostStatus.NOT_APPLICABLE
    assert component.reason
    assert not component.counts
    assert not component.blocks_evaluation


def test_not_applicable_without_a_reason_is_refused():
    with pytest.raises(ValueError, match="without saying why"):
        not_applicable(CostConcept.CHANNEL, "  ")


def test_unknown_required_blocks_the_evaluation():
    component = unknown_required(CostConcept.PAYMENT)

    assert component.status is CostStatus.UNKNOWN_REQUIRED
    assert component.blocks_evaluation
    assert not component.counts


def test_unknown_optional_does_not_block_but_is_recorded():
    component = unknown_optional(CostConcept.OTHER_VARIABLE)

    assert component.status is CostStatus.UNKNOWN_OPTIONAL
    assert not component.blocks_evaluation
    assert not component.counts


def test_the_four_non_known_states_all_add_nothing_and_mean_four_things():
    """Es la razón de ser de este módulo: «no sumo nada» significaba cuatro
    cosas distintas y un `None` las aplanaba."""
    states = {
        included_in(CostConcept.IMPORT, CostConcept.PRODUCT).status,
        not_applicable(CostConcept.CHANNEL, "x").status,
        unknown_required(CostConcept.PAYMENT).status,
        unknown_optional(CostConcept.OTHER_VARIABLE).status,
    }

    assert len(states) == 4
    assert all(s is not CostStatus.KNOWN for s in states)


# --- contradicciones al construir -------------------------------------------


def test_a_known_cost_without_an_amount_is_not_known():
    with pytest.raises(ValueError, match="without an amount"):
        CostBreakdown(components=(known(CostConcept.PRODUCT, None, provenance=CLAIM),))  # type: ignore[arg-type]


def test_a_known_cost_without_provenance_is_refused():
    """Un coste sin autor es lo que el Milestone 39 quitó de los proveedores."""
    with pytest.raises(ValueError, match="unattributed cost"):
        known(CostConcept.PRODUCT, euros("1"), provenance=SupplierFactProvenance.UNKNOWN)


def test_a_cost_that_is_not_known_cannot_carry_a_figure():
    from app.economics.components import CostComponent

    with pytest.raises(ValueError, match="still carries an amount"):
        CostComponent(
            concept=CostConcept.IMPORT,
            status=CostStatus.NOT_APPLICABLE,
            amount=euros("1"),
            reason="x",
        )


# --- doble contabilización ---------------------------------------------------


def test_a_concept_cannot_appear_twice():
    with pytest.raises(DoubleCountingError, match="appears twice"):
        check_invariants(
            [
                known(CostConcept.PRODUCT, euros("4.20"), provenance=CLAIM),
                known(CostConcept.PRODUCT, euros("4.20"), provenance=CLAIM),
            ]
        )


def test_being_inside_something_nobody_declared_counts_nothing():
    """El arancel dentro de una logística desconocida no está contado en
    ninguna parte, y decir que lo está esconde el hueco."""
    with pytest.raises(DoubleCountingError, match="nobody declared"):
        full(
            **{
                CostConcept.LOGISTICS: unknown_required(CostConcept.LOGISTICS),
                CostConcept.IMPORT: included_in(CostConcept.IMPORT, CostConcept.LOGISTICS),
            }
        )


def test_a_cost_cannot_be_inside_itself():
    with pytest.raises(ValueError, match="included in itself"):
        included_in(CostConcept.IMPORT, CostConcept.IMPORT)


def test_a_cycle_is_refused_by_the_container_rule():
    """Un ciclo exige que todos sus miembros estén dentro de otro, y entonces
    ninguno es conocido: la regla del contenedor lo caza antes de que haga
    falta buscar el círculo."""
    with pytest.raises(DoubleCountingError, match="nobody declared"):
        check_invariants(
            [
                included_in(CostConcept.PRODUCT, CostConcept.IMPORT),
                included_in(CostConcept.IMPORT, CostConcept.PRODUCT),
                known(CostConcept.LOGISTICS, euros("1"), provenance=CLAIM),
                not_applicable(CostConcept.CHANNEL, "x"),
                unknown_optional(CostConcept.PAYMENT),
                unknown_optional(CostConcept.OTHER_VARIABLE),
            ]
        )


def test_every_concept_must_be_stated_even_the_ones_that_do_not_apply():
    """Un concepto omitido es indistinguible de uno en el que nadie pensó."""
    with pytest.raises(ValueError, match="missing"):
        CostBreakdown(components=(known(CostConcept.PRODUCT, euros("1"), provenance=CLAIM),))


def test_the_sum_walks_only_the_known_ones():
    breakdown = full()

    assert breakdown.total_cost(currency="EUR") == euros("6.05")
    assert {c.concept for c in breakdown.counted} == {
        CostConcept.PRODUCT,
        CostConcept.LOGISTICS,
        CostConcept.PAYMENT,
    }


def test_an_import_inside_the_product_is_not_added_a_second_time():
    """Incoterm DDP: los derechos ya están en el precio del proveedor."""
    breakdown = full(
        **{CostConcept.IMPORT: included_in(CostConcept.IMPORT, CostConcept.PRODUCT)}
    )

    assert breakdown.total_cost(currency="EUR") == euros("6.05")


# --- procedencia por componente ---------------------------------------------


def test_each_component_carries_its_own_provenance():
    breakdown = full()

    assert breakdown.of(CostConcept.PRODUCT).provenance is CLAIM
    assert breakdown.of(CostConcept.LOGISTICS).provenance is ESTIMATE


def test_the_weakest_provenance_is_a_floor_not_a_score():
    """Un margen no vale más que el más flojo de sus sumandos: si uno solo sale
    de un fixture, el margen es un margen simulado."""
    breakdown = full(
        **{
            CostConcept.PAYMENT: known(
                CostConcept.PAYMENT, euros("0.83"), provenance=SupplierFactProvenance.SIMULATED
            )
        }
    )

    assert breakdown.weakest_provenance is SupplierFactProvenance.SIMULATED


def test_a_component_that_does_not_count_does_not_weaken_the_floor():
    """Lo que no se suma no ensucia la procedencia de lo que sí."""
    breakdown = full()

    assert breakdown.weakest_provenance is ESTIMATE


def test_blocking_and_omitted_are_listed_separately():
    breakdown = full(**{CostConcept.PAYMENT: unknown_required(CostConcept.PAYMENT)})

    assert breakdown.blocking == (CostConcept.PAYMENT,)
    assert breakdown.omitted == (CostConcept.OTHER_VARIABLE,)
