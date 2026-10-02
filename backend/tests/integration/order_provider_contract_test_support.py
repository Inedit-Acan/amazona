"""Baterías de conformidad de los proveedores de M44 (ADR 0028 §1 y §7).

Módulo auxiliar de tests, **no** un test. Es lo que pasará cualquier proveedor de pagos o de fulfillment —el
simulado hoy, uno real mañana con su transporte falso— antes de que el sistema lo use. Extiende la batería de
los adaptadores con efecto (`adapter_contract_test_support`, ADR 0024) con lo propio de cada puerto:

**Pagos** (`assert_payment_provider_honours_contract`):

- declara sus capacidades y son coherentes con lo que el objeto dice de sí mismo;
- un webhook bien firmado se verifica y devuelve un evento de **ese** proveedor;
- un cuerpo alterado, una firma ausente o ilegible, una firma de otra clave y un sello de tiempo caducado o del
  futuro se **rechazan** con el error del contrato;
- verificar no escribe nada ni cambia el resultado de la siguiente verificación;
- abrir un cobro es idempotente por clave y consultable si dice serlo; lo que no soporta se rechaza sin efecto.

**Fulfillment** (`assert_fulfilment_provider_honours_contract`): idempotencia y consulta de la compra y del envío,
y un coste **declarado** que nunca es cero cuando no se sabe.
"""

import datetime
from collections.abc import Callable
from typing import Protocol

import pytest

from app.actions.contract import ActionRequest, ProviderRejectedError, derive_idempotency_key
from app.gates.action_gate import CostKind
from app.money.money import Money
from app.orders.fulfilment_port import (
    OPERATION_PURCHASE,
    OPERATION_SHIP,
    PHASE_PURCHASE,
    PHASE_SHIP,
    FulfilmentLine,
    FulfilmentProvider,
)
from app.payments.port import (
    InvalidSignatureError,
    MissingSignatureError,
    PaymentEventType,
    PaymentProvider,
    StaleTimestampError,
    VerifiedPaymentEvent,
    WebhookVerificationError,
)

NOW = datetime.datetime(2026, 10, 2, 12, 0, tzinfo=datetime.UTC)


def _must_reject(expected: type[Exception], message: str, call: Callable[[], object]) -> None:
    """La llamada tiene que fallar **con el error del contrato**. Fallar con otro error, o no fallar, es
    incumplir el contrato: se convierte en un fallo de la batería (no en un error cualquiera del proveedor)."""
    try:
        call()
    except expected:
        return
    except Exception as exc:  # noqa: BLE001 - cualquier otro error es la prueba de que no cumple
        raise AssertionError(f"{message}: raised {type(exc).__name__} instead of {expected.__name__}") from exc
    raise AssertionError(f"{message}: no error was raised")


class EventSigner(Protocol):
    """Cómo producir webhooks para el proveedor bajo prueba. Cada proveedor aporta el suyo."""

    def signed(self, event_type: PaymentEventType, *, timestamp: datetime.datetime) -> tuple[dict[str, str], bytes]:
        """Un evento bien firmado con la clave del proveedor, con ese sello de tiempo."""
        ...

    def foreign(self, event_type: PaymentEventType, *, timestamp: datetime.datetime) -> tuple[dict[str, str], bytes]:
        """Un evento firmado con **otra** clave (no la del proveedor)."""
        ...


def payment_request(provider: PaymentProvider, operation: str = "payment.open", site: str = "site-a") -> ActionRequest:
    key = derive_idempotency_key(site, 1) if provider.supports_idempotency else None
    if operation == "payment.open":
        payload = {"payment_id": f"pay-{site}", "order_id": "order-1", "amount": "12.5000", "currency": "EUR"}
    else:
        payload = {"provider_payment_ref": "simpay_x", "amount": "5.0000", "currency": "EUR"}
    return ActionRequest(
        provider=provider.name,
        operation=operation,
        idempotency_key=key,
        amount=None,
        payload=payload,
        correlation_id="corr-1",
    )


def assert_payment_provider_honours_contract(
    provider: PaymentProvider, signer: EventSigner, effects: Callable[[], int] | None = None
) -> None:
    assert isinstance(provider, PaymentProvider), "the provider does not implement the payment port"
    caps = provider.capabilities
    assert caps.name == provider.name, "capabilities must name the same provider"
    assert caps.supports_idempotency is provider.supports_idempotency, "idempotency is declared once and agrees"
    assert caps.signature_tolerance_seconds > 0, "a webhook needs a replay window"
    assert caps.event_types, "a provider must declare which events it can send"
    assert caps.supports_authorization_hold is False or isinstance(caps.supports_authorization_hold, bool)

    tolerance = caps.signature_tolerance_seconds
    event_type = PaymentEventType.PAYMENT_SUCCEEDED

    # --- Un webhook auténtico se verifica y es de este proveedor ---------------------------------------
    headers, raw = signer.signed(event_type, timestamp=NOW)
    verified = provider.verify_webhook(headers=headers, raw_body=raw, now=NOW)
    assert isinstance(verified, VerifiedPaymentEvent)
    assert verified.provider == provider.name, "an event must be attributed to the provider that verified it"
    assert verified.event_type is event_type
    assert verified.provider_event_id, "an event without identity cannot be deduplicated"
    assert verified.occurred_at.tzinfo is not None, "event times must carry their zone"

    # --- Verificar no escribe ni cambia nada: la misma verificación da el mismo resultado ---------------
    again = provider.verify_webhook(headers=headers, raw_body=raw, now=NOW)
    assert again == verified, "verification must be a pure function of its inputs"

    # --- Lo que NO es auténtico se rechaza --------------------------------------------------------------
    altered = bytearray(raw)
    altered[len(altered) // 2] ^= 0x01
    _must_reject(
        InvalidSignatureError,
        "a tampered body",
        lambda: provider.verify_webhook(headers=headers, raw_body=bytes(altered), now=NOW),
    )

    _must_reject(
        MissingSignatureError,
        "a missing signature",
        lambda: provider.verify_webhook(headers={}, raw_body=raw, now=NOW),
    )

    _must_reject(
        WebhookVerificationError,
        "an unreadable signature",
        lambda: provider.verify_webhook(headers={name: "garbage" for name in headers}, raw_body=raw, now=NOW),
    )

    foreign_headers, foreign_raw = signer.foreign(event_type, timestamp=NOW)
    _must_reject(
        InvalidSignatureError,
        "a signature from another key",
        lambda: provider.verify_webhook(headers=foreign_headers, raw_body=foreign_raw, now=NOW),
    )

    old_headers, old_raw = signer.signed(event_type, timestamp=NOW - datetime.timedelta(seconds=tolerance + 5))
    _must_reject(
        StaleTimestampError,
        "an expired timestamp",
        lambda: provider.verify_webhook(headers=old_headers, raw_body=old_raw, now=NOW),
    )

    future_headers, future_raw = signer.signed(event_type, timestamp=NOW + datetime.timedelta(seconds=tolerance + 5))
    _must_reject(
        StaleTimestampError,
        "a timestamp from the future",
        lambda: provider.verify_webhook(headers=future_headers, raw_body=future_raw, now=NOW),
    )

    # --- Las operaciones salientes: idempotentes por clave y consultables -------------------------------
    request = payment_request(provider)
    before = effects() if effects else None
    first = provider.execute(request)
    if provider.supports_idempotency:
        assert provider.execute(request).reference == first.reference, "the same key must be the same operation"
        if effects:
            assert effects() == before + 1, "an idempotent provider repeated the effect for the same key"
        other = provider.execute(payment_request(provider, site="site-b"))
        assert other.reference != first.reference, "a different key must be a different operation"
        if effects:
            assert effects() == before + 2

    if caps.supports_lookup:
        assert provider.lookup(request.idempotency_key or "") is not None, "lookup must find what it executed"  # type: ignore[attr-defined]
        assert provider.lookup("amz-never-executed") is None, "lookup answers None only for what does not exist"  # type: ignore[attr-defined]

    unsupported = ActionRequest(
        provider=provider.name,
        operation="payment.teleport",
        idempotency_key=request.idempotency_key,
        amount=None,
        payload={},
        correlation_id="corr-1",
    )
    effects_before = effects() if effects else None
    _must_reject(ProviderRejectedError, "an unsupported operation", lambda: provider.execute(unsupported))
    if effects:
        assert effects() == effects_before, "a rejected operation must have no effect"


# --- Fulfillment -------------------------------------------------------------------------------------


def _line(quantity: int, unit_cost: str | None) -> FulfilmentLine:
    return FulfilmentLine(
        order_item_id=f"item-{quantity}",
        line_number=quantity,
        product_id="product-1",
        quantity=quantity,
        unit_cost=Money.of(unit_cost, "EUR") if unit_cost is not None else None,
    )


def fulfilment_request(provider: FulfilmentProvider, operation: str, site: str = "site-a") -> ActionRequest:
    key = derive_idempotency_key(site, 1) if provider.supports_idempotency else None
    return ActionRequest(
        provider=provider.name,
        operation=operation,
        idempotency_key=key,
        amount=None,
        payload={"fulfillment_id": site},
        correlation_id="corr-1",
    )


def assert_fulfilment_provider_honours_contract(
    provider: FulfilmentProvider, effects: Callable[[], int] | None = None
) -> None:
    assert isinstance(provider, FulfilmentProvider), "the provider does not implement the fulfilment port"
    caps = provider.capabilities
    assert caps.name == provider.name
    assert caps.supports_idempotency is provider.supports_idempotency
    assert {PHASE_PURCHASE, PHASE_SHIP} <= caps.phases or caps.phases, "a provider declares the phases it runs"

    for operation in (OPERATION_PURCHASE, OPERATION_SHIP):
        request = fulfilment_request(provider, operation, site=f"site-{operation}")
        before = effects() if effects else None
        first = provider.execute(request)
        if provider.supports_idempotency:
            assert provider.execute(request).reference == first.reference
            if effects:
                assert effects() == before + 1, "an idempotent provider repeated the effect for the same key"
            assert provider.execute(fulfilment_request(provider, operation, site="other")).reference != first.reference
        if caps.supports_lookup:
            assert provider.lookup(request.idempotency_key or "") is not None  # type: ignore[attr-defined]
            assert provider.lookup("amz-never-executed") is None  # type: ignore[attr-defined]

    _must_reject(
        ProviderRejectedError,
        "an unsupported operation",
        lambda: provider.execute(fulfilment_request(provider, "fulfillment.teleport")),
    )

    # --- El coste: declarado, y desconocido nunca es cero -------------------------------------------------
    unknown = provider.quote_cost(phase=PHASE_PURCHASE, lines=[_line(2, "3.00"), _line(1, None)], currency="EUR")
    assert unknown.kind is CostKind.UNKNOWN, "one line of unknown cost makes the whole purchase unknown, not cheaper"
    assert unknown.as_amount() is None

    known = provider.quote_cost(phase=PHASE_PURCHASE, lines=[_line(2, "3.00"), _line(1, "1.50")], currency="EUR")
    assert known.kind is CostKind.KNOWN and known.as_amount() == pytest.approx(7.5)

    assert provider.quote_cost(phase=PHASE_PURCHASE, lines=[], currency="EUR").kind is CostKind.UNKNOWN, (
        "a purchase of nothing is not a free purchase"
    )
    mismatched = provider.quote_cost(
        phase=PHASE_PURCHASE,
        lines=[FulfilmentLine("i", 1, "p", 1, Money.of("2.00", "USD"))],
        currency="EUR",
    )
    assert mismatched.kind is CostKind.UNKNOWN, "a cost in another currency is not converted by guessing"

    shipping = provider.quote_cost(phase=PHASE_SHIP, lines=[_line(1, "3.00")], currency="EUR")
    assert shipping.kind in (CostKind.ZERO, CostKind.KNOWN, CostKind.UNKNOWN)
