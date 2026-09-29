"""Unidad, pedido y adquisición, y el techo de CAC (Milestone 40, ADR 0018)."""

from decimal import Decimal

import pytest

from app.economics.components import (
    CostBreakdown,
    CostConcept,
    included_in,
    known,
    not_applicable,
    unknown_optional,
    unknown_required,
)
from app.economics.unit_economics import (
    ORDERS_PER_ACQUISITION,
    DeclaredQuantity,
    Evaluability,
    UnitEconomicsInput,
    evaluate,
)
from app.money.money import Money
from app.sourcing.provenance import SupplierFactProvenance

CLAIM = SupplierFactProvenance.SUPPLIER_CLAIM


def euros(amount: str) -> Money:
    return Money.of(amount, "EUR")


def breakdown(**overrides) -> CostBreakdown:
    components = {
        CostConcept.PRODUCT: known(CostConcept.PRODUCT, euros("4.00"), provenance=CLAIM),
        CostConcept.LOGISTICS: known(CostConcept.LOGISTICS, euros("1.00"), provenance=CLAIM),
        CostConcept.IMPORT: included_in(CostConcept.IMPORT, CostConcept.LOGISTICS),
        CostConcept.CHANNEL: not_applicable(CostConcept.CHANNEL, "web propia"),
        CostConcept.PAYMENT: known(CostConcept.PAYMENT, euros("1.00"), provenance=CLAIM),
        CostConcept.OTHER_VARIABLE: unknown_optional(CostConcept.OTHER_VARIABLE),
    }
    components.update(overrides)
    return CostBreakdown(components=tuple(components.values()))


def inputs(**overrides) -> UnitEconomicsInput:
    defaults = {
        "sale_price": euros("20.00"),
        "breakdown": breakdown(),
        "units_per_order": DeclaredQuantity.declared(1, source="manual:test"),
        "expected_monthly_orders": DeclaredQuantity.declared(300, source="manual:test"),
        "monthly_fixed_costs": euros("500.00"),
    }
    return UnitEconomicsInput(**{**defaults, **overrides})


# --- la cadena ---------------------------------------------------------------


def test_the_margin_per_unit_subtracts_only_the_known_costs():
    result = evaluate(inputs())

    assert result.contribution_margin_per_unit == euros("14.00")
    assert result.margin_evaluability is Evaluability.EVALUABLE


def test_the_margin_per_order_is_the_margin_per_unit_times_the_units():
    """Si cada pedido lleva tres unidades, el margen que financia esa
    adquisición es el de tres unidades. Calcularlo sobre una lo subestima en un
    66 %."""
    result = evaluate(
        inputs(units_per_order=DeclaredQuantity.declared(3, source="manual:test"))
    )

    assert result.contribution_margin_per_unit == euros("14.00")
    assert result.contribution_margin_per_order == euros("42.00")


def test_the_cac_ceiling_is_the_order_margin_minus_the_allocated_fixed_cost():
    result = evaluate(inputs())

    assert result.allocated_fixed_cost_per_order == Money.of("1.6667", "EUR")
    assert result.max_breakeven_cac == Money.of("12.3333", "EUR")
    assert result.cac_evaluability is Evaluability.EVALUABLE


def test_with_more_units_per_order_the_cac_ceiling_rises():
    """La prueba de que unidad y pedido no son lo mismo: el mismo producto
    aguanta más coste de adquisición si cada pedido lleva más unidades."""
    one = evaluate(inputs(units_per_order=DeclaredQuantity.declared(1, source="t")))
    three = evaluate(
        inputs(
            units_per_order=DeclaredQuantity.declared(3, source="t"),
            expected_monthly_orders=DeclaredQuantity.declared(100, source="t"),
        )
    )

    assert one.max_breakeven_cac == Money.of("12.3333", "EUR")
    assert three.max_breakeven_cac == Money.of("37.0000", "EUR")
    # El margen por unidad no cambia: es el mismo producto.
    assert one.contribution_margin_per_unit == three.contribution_margin_per_unit


def test_the_ceiling_before_fixed_costs_is_the_order_margin():
    result = evaluate(inputs())

    assert result.breakeven_cac_before_fixed_costs == result.contribution_margin_per_order


def test_a_negative_ceiling_is_kept_negative():
    """Significa que el producto pierde dinero antes de gastar un euro en
    adquisición. Recortarlo a cero escondería precisamente eso."""
    result = evaluate(inputs(sale_price=euros("5.00")))

    assert result.max_breakeven_cac is not None
    assert result.max_breakeven_cac.is_negative


def test_one_acquisition_is_one_order_and_it_is_declared():
    """La compra repetida es LTV y queda fuera. Está escrito para que no sea
    una suposición silenciosa."""
    assert ORDERS_PER_ACQUISITION == Decimal(1)
    assert evaluate(inputs()).orders_per_acquisition == Decimal(1)


# --- unidades por pedido desconocidas ---------------------------------------


def test_without_units_per_order_there_is_no_order_margin_and_no_cac():
    result = evaluate(inputs(units_per_order=DeclaredQuantity.unknown()))

    assert result.contribution_margin_per_unit == euros("14.00")
    assert result.margin_evaluability is Evaluability.EVALUABLE
    assert result.contribution_margin_per_order is None
    assert result.max_breakeven_cac is None
    assert result.cac_evaluability is Evaluability.NOT_EVALUABLE
    assert "units_per_order" in result.missing_inputs


def test_a_one_that_nobody_declared_cannot_exist():
    """Es la corrección que impide que el 1 vuelva a ser una suposición."""
    with pytest.raises(ValueError, match="who says so"):
        DeclaredQuantity(value=Decimal(1), provenance=SupplierFactProvenance.UNKNOWN)


def test_a_fixture_may_use_one_but_it_says_it_is_simulated():
    quantity = DeclaredQuantity.simulated(1, source="fixtures:demo")

    assert quantity.value == Decimal(1)
    assert quantity.provenance is SupplierFactProvenance.SIMULATED


def test_a_declared_one_is_attributed_to_whoever_declared_it():
    quantity = DeclaredQuantity.declared(1, source="manual:owner")

    assert quantity.provenance is SupplierFactProvenance.DECLARED
    assert quantity.source == "manual:owner"


# --- pedidos mensuales desconocidos -----------------------------------------


def test_without_expected_orders_the_margin_stands_but_the_ceiling_does_not():
    """Tres niveles de evaluabilidad, no uno."""
    result = evaluate(inputs(expected_monthly_orders=DeclaredQuantity.unknown()))

    assert result.contribution_margin_per_unit == euros("14.00")
    assert result.contribution_margin_per_order == euros("14.00")
    assert result.breakeven_cac_before_fixed_costs == euros("14.00")
    assert result.allocated_fixed_cost_per_order is None
    assert result.max_breakeven_cac is None
    assert "expected_monthly_orders" in result.missing_inputs


def test_without_fixed_costs_there_is_no_allocation_either():
    result = evaluate(inputs(monthly_fixed_costs=None))

    assert result.allocated_fixed_cost_per_order is None
    assert "monthly_fixed_costs" in result.missing_inputs


# --- costes obligatorios ausentes -------------------------------------------


def test_a_required_cost_missing_makes_everything_not_evaluable():
    result = evaluate(
        inputs(breakdown=breakdown(**{CostConcept.PAYMENT: unknown_required(CostConcept.PAYMENT)}))
    )

    assert result.margin_evaluability is Evaluability.NOT_EVALUABLE
    assert result.cac_evaluability is Evaluability.NOT_EVALUABLE
    assert result.contribution_margin_per_unit is None
    assert "payment" in result.missing_inputs


def test_an_optional_cost_missing_is_recorded_and_does_not_block():
    """El margen es optimista en esa cantidad, y el resultado lo dice."""
    result = evaluate(inputs())

    assert result.margin_evaluability is Evaluability.EVALUABLE
    assert "other_variable" in result.omitted_costs


def test_not_evaluable_is_never_a_negative_result():
    """Un margen negativo se sabe y es malo; no evaluable es que no se sabe. El
    tipo los distingue y nada los colapsa."""
    blocked = evaluate(
        inputs(breakdown=breakdown(**{CostConcept.PRODUCT: unknown_required(CostConcept.PRODUCT)}))
    )
    negative = evaluate(inputs(sale_price=euros("1.00")))

    assert blocked.contribution_margin_per_unit is None
    assert negative.contribution_margin_per_unit is not None
    assert negative.contribution_margin_per_unit.is_negative
    assert negative.margin_evaluability is Evaluability.EVALUABLE


def test_the_result_carries_the_weakest_provenance_of_what_it_summed():
    result = evaluate(
        inputs(
            breakdown=breakdown(
                **{
                    CostConcept.PAYMENT: known(
                        CostConcept.PAYMENT,
                        euros("1.00"),
                        provenance=SupplierFactProvenance.SIMULATED,
                    )
                }
            )
        )
    )

    assert result.weakest_provenance is SupplierFactProvenance.SIMULATED


def test_a_target_margin_is_not_invented():
    """El hueco está preparado y vacío: el Milestone 40 calcula el techo de
    equilibrio, no un objetivo empresarial."""
    assert inputs().target_margin_per_order is None
