"""Cuándo un pedido necesita que una persona lo mire (Milestone 44, ADR 0028 §4).

`attention_required` **se calcula al leer**, a partir del estado de las tablas; no es una columna que pueda quedar
obsoleta, y calcularlo no escribe nada (un `GET` no escribe, I10). Cada razón es un código estable que la pantalla
y las pruebas pueden nombrar. El sistema no «arregla» el pedido por su cuenta: avisa.

Las razones las aportan los dominios que existen: los pagos y los reembolsos (captura duplicada, captura sobre un
pedido cancelado, captura de un importe distinto, intento abierto con el pedido ya cobrado, resultado desconocido,
evidencia en conflicto) y, más adelante, el fulfillment. Lo que no existe aún no aporta ninguna.
"""

import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.order import Order
from app.db.models.payment import Payment, PaymentEvent, Refund
from app.orders.domain import OrderStatus
from app.payments.domain import (
    ACTIVE_PAYMENT_STATUSES,
    REFUND_CONFIRMATION_GRACE_MINUTES,
    EventProcessing,
    PaymentStatus,
    RefundStatus,
)

CAPTURED_ON_CANCELLED_ORDER = "captured_on_cancelled_order"
DUPLICATE_CAPTURE = "duplicate_capture"
CAPTURE_MISMATCH = "capture_mismatch"
OPEN_ATTEMPT_ON_SETTLED_ORDER = "open_attempt_on_settled_order"
PAYMENT_OUTCOME_UNKNOWN = "payment_outcome_unknown"
CONFLICTING_PAYMENT_EVENTS = "conflicting_payment_events"
REFUND_OUTCOME_UNKNOWN = "refund_outcome_unknown"
#: El proveedor aceptó devolver el dinero y no lo ha confirmado con un hecho verificado pasado un tiempo.
REFUND_UNCONFIRMED = "refund_unconfirmed"


def attention_reasons(db: Session, order: Order, *, now: datetime.datetime | None = None) -> list[str]:
    """Las razones, en un orden estable. Vacío = nada que mirar. `now` solo lo fijan las pruebas."""
    payments = list(db.scalars(select(Payment).where(Payment.order_id == order.id).order_by(Payment.attempt_number)))
    reasons: list[str] = []
    settled = order.status in (
        OrderStatus.PAID.value,
        OrderStatus.COMPLETED.value,
        OrderStatus.CANCELLED.value,
    )

    if order.status == OrderStatus.CANCELLED.value and any(Decimal(str(p.captured_amount)) > 0 for p in payments):
        reasons.append(CAPTURED_ON_CANCELLED_ORDER)
    if any(p.status == PaymentStatus.DUPLICATE_CAPTURE.value for p in payments):
        reasons.append(DUPLICATE_CAPTURE)
    if any(p.status == PaymentStatus.CAPTURE_MISMATCH.value for p in payments):
        reasons.append(CAPTURE_MISMATCH)
    if settled and any(p.status in ACTIVE_PAYMENT_STATUSES for p in payments):
        reasons.append(OPEN_ATTEMPT_ON_SETTLED_ORDER)
    if any(p.status == PaymentStatus.UNKNOWN_OUTCOME.value for p in payments):
        reasons.append(PAYMENT_OUTCOME_UNKNOWN)

    if payments:
        ids = [p.id for p in payments]
        conflicts = db.scalar(
            select(PaymentEvent.id)
            .where(PaymentEvent.payment_id.in_(ids), PaymentEvent.processing_status == EventProcessing.CONFLICT.value)
            .limit(1)
        )
        if conflicts is not None:
            reasons.append(CONFLICTING_PAYMENT_EVENTS)
        unknown_refund = db.scalar(
            select(Refund.id)
            .where(Refund.payment_id.in_(ids), Refund.status == RefundStatus.UNKNOWN_OUTCOME.value)
            .limit(1)
        )
        if unknown_refund is not None:
            reasons.append(REFUND_OUTCOME_UNKNOWN)
        cutoff = (now or datetime.datetime.now(datetime.UTC)) - datetime.timedelta(
            minutes=REFUND_CONFIRMATION_GRACE_MINUTES
        )
        sent = db.scalars(
            select(Refund.requested_at).where(Refund.payment_id.in_(ids), Refund.status == RefundStatus.SENDING.value)
        ).all()
        if any(_aware(requested) < cutoff for requested in sent):
            reasons.append(REFUND_UNCONFIRMED)
    return reasons


def _aware(value: datetime.datetime) -> datetime.datetime:
    """SQLite devuelve fechas sin zona; todas las que se guardan son UTC."""
    return value if value.tzinfo is not None else value.replace(tzinfo=datetime.UTC)
