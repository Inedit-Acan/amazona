"""El proveedor de fulfillment simulado cumple el contrato (ADR 0028 §6 y §7).

La batería comprueba idempotencia y consulta de la compra y del envío, y que el coste se **declara**: el
desconocido nunca es cero, una compra de nada no es gratis y una moneda distinta no se convierte a ojo.
"""

import pytest
from order_provider_contract_test_support import assert_fulfilment_provider_honours_contract

from app.gates.action_gate import CostKind
from app.money.money import Money
from app.orders.fulfilment_port import (
    OPERATION_PURCHASE,
    PHASE_PURCHASE,
    PHASE_SHIP,
    FulfilmentLine,
    FulfilmentProvider,
)
from app.orders.simulated_fulfilment import PROVIDER_NAME, SimulatedFulfilmentAdapter

FAILED = (AssertionError, pytest.fail.Exception)


def test_the_simulated_adapter_honours_the_contract():
    ops: dict = {}
    adapter = SimulatedFulfilmentAdapter(operations=ops)

    assert_fulfilment_provider_honours_contract(adapter, effects=lambda: len(ops))


def test_it_declares_its_capabilities():
    adapter = SimulatedFulfilmentAdapter(operations={})

    assert isinstance(adapter, FulfilmentProvider)
    assert adapter.name == PROVIDER_NAME == adapter.capabilities.name
    assert adapter.capabilities.phases == {PHASE_PURCHASE, PHASE_SHIP}
    assert adapter.capabilities.supports_idempotency and adapter.capabilities.supports_lookup


def test_a_shipment_costs_a_declared_simulated_zero_not_an_unknown():
    cost = SimulatedFulfilmentAdapter(operations={}).quote_cost(
        phase=PHASE_SHIP,
        lines=[FulfilmentLine("i", 1, "p", 1, None)],
        currency="EUR",
    )

    assert cost.kind is CostKind.ZERO and cost.provenance == "simulated"


def test_a_purchase_costs_the_sum_of_its_lines_and_is_unknown_if_any_line_is():
    adapter = SimulatedFulfilmentAdapter(operations={})
    known = adapter.quote_cost(
        phase=PHASE_PURCHASE,
        lines=[
            FulfilmentLine("a", 1, "p", 3, Money.of("2.10", "EUR")),
            FulfilmentLine("b", 2, "p", 1, Money.of("0.70", "EUR")),
        ],
        currency="EUR",
    )
    unknown = adapter.quote_cost(
        phase=PHASE_PURCHASE,
        lines=[FulfilmentLine("a", 1, "p", 3, Money.of("2.10", "EUR")), FulfilmentLine("b", 2, "p", 1, None)],
        currency="EUR",
    )

    assert known.kind is CostKind.KNOWN and known.as_amount() == pytest.approx(7.0)
    assert unknown.kind is CostKind.UNKNOWN and unknown.as_amount() is None


def test_a_purchase_with_a_declared_zero_cost_line_is_a_zero_not_an_unknown():
    cost = SimulatedFulfilmentAdapter(operations={}).quote_cost(
        phase=PHASE_PURCHASE,
        lines=[FulfilmentLine("a", 1, "p", 2, Money.zero("EUR"))],
        currency="EUR",
    )

    assert cost.kind is CostKind.ZERO


def test_an_unknown_phase_has_an_unknown_cost():
    cost = SimulatedFulfilmentAdapter(operations={}).quote_cost(phase="teleport", lines=[], currency="EUR")

    assert cost.kind is CostKind.UNKNOWN


def test_two_instances_share_what_was_executed_in_the_process():
    first, second = SimulatedFulfilmentAdapter(), SimulatedFulfilmentAdapter()
    from app.actions.contract import ActionRequest

    request = ActionRequest(
        provider=PROVIDER_NAME,
        operation=OPERATION_PURCHASE,
        idempotency_key="amz-shared-instance-test",
        amount=None,
        payload={},
        correlation_id="c",
    )
    done = first.execute(request)

    assert second.lookup("amz-shared-instance-test") == done
