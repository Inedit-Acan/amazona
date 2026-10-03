"""Apoyo compartido de las pruebas del registro de ingresos verificados (Milestone 45, ADR 0030).

Módulo auxiliar de tests, **no** un test. Pone en el estado que se quiera un cobro capturado, duplicado o discrepante,
y un reembolso nuestro o del proveedor, siempre **por la puerta de eventos** (como un webhook): el registro no se
puebla a mano, porque lo que se prueba es que `PaymentService` lo proyecta.
"""

import datetime
from decimal import Decimal

from order_test_support import add_product
from payment_test_support import (
    REQUESTER,
    SIMULATION,
    ScriptedPaymentProvider,
    deliver,
    ingress,
    reload,
    start_attempt,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.order import Order
from app.db.models.payment import Payment, Refund
from app.db.models.revenue import RevenueLedgerEntry
from app.money.money import Money
from app.orders.refunds import RefundService
from app.payments.port import PaymentEventType

SUCCEEDED = PaymentEventType.PAYMENT_SUCCEEDED
EXPIRED = PaymentEventType.PAYMENT_EXPIRED
REFUND_SUCCEEDED = PaymentEventType.REFUND_SUCCEEDED
REFUND_FAILED = PaymentEventType.REFUND_FAILED

__all__ = [
    "REQUESTER",
    "SIMULATION",
    "SUCCEEDED",
    "EXPIRED",
    "REFUND_SUCCEEDED",
    "REFUND_FAILED",
    "ScriptedPaymentProvider",
    "aware",
    "capture",
    "capture_entry",
    "confirm_refund",
    "duplicate_pair",
    "entries",
    "mismatched_capture",
    "new_order",
    "provider_refund",
    "refund_of",
    "refund_event",
    "reload",
]


def aware(value: datetime.datetime) -> datetime.datetime:
    """SQLite devuelve fechas sin zona; todas las que se guardan son UTC."""
    return value if value.tzinfo is not None else value.replace(tzinfo=datetime.UTC)


def entries(db: Session) -> list[RevenueLedgerEntry]:
    db.expire_all()
    return list(db.scalars(select(RevenueLedgerEntry).order_by(RevenueLedgerEntry.recorded_at, RevenueLedgerEntry.id)))


def capture_entry(db: Session, payment: Payment) -> RevenueLedgerEntry:
    db.expire_all()
    return db.scalars(
        select(RevenueLedgerEntry).where(
            RevenueLedgerEntry.payment_id == payment.id, RevenueLedgerEntry.kind == "CAPTURE"
        )
    ).one()


def new_order(
    db: Session, name: str = "Widget", customer: str = "sim_customer", *, price: str = "25.00", currency: str = "EUR"
) -> Order:
    """Un pedido de 2 × 25.00 = 50.00 EUR (el precio y la moneda se pueden cambiar)."""
    from order_test_support import create_order, line

    return create_order(
        db, line(add_product(db, name=name), unit_price=price, currency=currency), customer_ref=customer
    )


def capture(db: Session, provider: ScriptedPaymentProvider, order: Order, **kwargs) -> Payment:
    """Un cobro con su captura normal aplicada por un evento verificado."""
    payment = start_attempt(db, order, provider)
    deliver(db, provider, SUCCEEDED, payment, **kwargs)
    return reload(db, payment)


def duplicate_pair(db: Session, provider: ScriptedPaymentProvider, order: Order) -> tuple[Payment, Payment]:
    """`(canónico, duplicado)`: un segundo cobro real del mismo pedido, guardado como `DUPLICATE_CAPTURE`."""
    first = start_attempt(db, order, provider)
    deliver(db, provider, EXPIRED, first)
    second = start_attempt(db, order, provider)
    deliver(db, provider, SUCCEEDED, second)
    deliver(db, provider, SUCCEEDED, first)
    return reload(db, second), reload(db, first)


def mismatched_capture(db: Session, provider: ScriptedPaymentProvider, order: Order, amount: str = "12.50") -> Payment:
    payment = start_attempt(db, order, provider)
    deliver(db, provider, SUCCEEDED, payment, amount=amount)
    return reload(db, payment)


def refund_of(
    db: Session,
    provider: ScriptedPaymentProvider,
    payment: Payment,
    amount: str = "10.00",
    *,
    reason: str = "customer_request",
) -> Refund:
    return RefundService(db, settings=SIMULATION, provider=provider).request(
        payment.id, amount=Money.of(amount, payment.currency), reason=reason, requester=REQUESTER
    )


def refund_event(db: Session, provider, refund: Refund, kind: PaymentEventType, **kwargs):
    """Lo que enviaría el proveedor: nuestro `refund_id` como referencia de cliente y, si la conoce, la suya."""
    payment = db.get(Payment, refund.payment_id)
    headers, raw = provider.simulate_event(
        kind,
        provider_payment_ref=payment.provider_payment_ref,
        provider_refund_ref=refund.provider_refund_ref,
        client_reference=refund.id,
        amount=Money.of(kwargs.get("amount") or str(refund.amount), refund.currency),
        event_id=kwargs.get("event_id"),
        occurred_at=kwargs.get("occurred_at"),
    )
    return ingress(db, provider).receive(provider.name, headers, raw)


def confirm_refund(db: Session, provider, refund: Refund, **kwargs):
    return refund_event(db, provider, refund, REFUND_SUCCEEDED, **kwargs)


def provider_refund(db: Session, provider, payment: Payment, amount: str, ref: str, event_id: str):
    """Un reembolso que el proveedor hizo por su cuenta (p. ej. desde su panel): no lo iniciamos nosotros."""
    return deliver(db, provider, REFUND_SUCCEEDED, payment, amount=amount, refund_ref=ref, event_id=event_id)


def total(values) -> Decimal:
    return sum((Decimal(str(v)) for v in values), Decimal(0))
