"""La reconciliación del registro con el estado de pago, de **solo lectura** (ADR 0030 §12 y §13).

Compara lo que dicen las entradas con lo que dice el cobro y **no corrige nada**: una divergencia es un defecto con
prioridad (la invariante L3 dice que no puede ocurrir) y se informa; jamás se arregla sola.

- **C1.** Por cobro con entradas: `Σ CAPTURE = captured_amount`.
- **C2.** Por cobro con captura en el registro: `Σ REFUND = refunded_amount`.
- **C3.** Toda entrada nombra un `PaymentEvent` `APPLIED` del tipo que le corresponde, con su mismo importe,
  moneda y cobro.
- **C4.** Un cobro con dinero capturado desde que existe el registro tiene su entrada `CAPTURE`.

Un cobro capturado **antes** del registro (sin ninguna entrada y con su captura aplicada antes de la primera
entrada, o con el registro vacío) es `outside_ledger`: se lista como informativo y **no** cuenta como divergencia.
"""

import datetime
from decimal import Decimal

from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from app.db.models.payment import Payment, PaymentEvent
from app.db.models.revenue import RevenueLedgerEntry as Entry
from app.payments.domain import EventProcessing
from app.revenue.domain import CAPTURE_EVENT_TYPE, REFUND_EVENT_TYPE, EntryKind
from app.revenue.evidence import money

#: Cuántos elementos concretos lista cada apartado (el resto se cuenta, no se lista).
LISTED_DIVERGENCES = 20


def _aware(value: datetime.datetime) -> datetime.datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=datetime.UTC)


def _dec(value: object) -> Decimal:
    return Decimal(str(value if value is not None else 0))


def _round(column):
    """Compara importes a la precisión de la columna (`Numeric(18,4)`); SQLite suma en coma flotante."""
    return func.round(column, 4)


def check_ledger(db: Session, *, limit: int = LISTED_DIVERGENCES) -> dict:
    """Una fotografía de la reconciliación del registro. Solo `SELECT`."""
    divergences: list[dict] = []
    outside: list[dict] = []

    captures = (
        select(Entry.payment_id.label("payment_id"), func.sum(Entry.amount).label("total"))
        .where(Entry.kind == EntryKind.CAPTURE.value)
        .group_by(Entry.payment_id)
        .subquery()
    )
    refunds = (
        select(Entry.payment_id.label("payment_id"), func.sum(Entry.amount).label("total"))
        .where(Entry.kind == EntryKind.REFUND.value)
        .group_by(Entry.payment_id)
        .subquery()
    )

    # C1: la suma de capturas del cobro frente a su dinero capturado (solo cobros que ya tienen entrada de captura).
    for row in db.execute(
        select(Payment.id, Payment.currency, Payment.captured_amount, captures.c.total)
        .join(captures, captures.c.payment_id == Payment.id)
        .where(_round(Payment.captured_amount) != _round(captures.c.total))
        .order_by(Payment.id)
    ):
        divergences.append(_amounts("C1", row.id, row.currency, row.captured_amount, row.total))

    # C2: la suma de reembolsos frente a lo reembolsado, solo en cobros cubiertos por el registro.
    for row in db.execute(
        select(Payment.id, Payment.currency, Payment.refunded_amount, func.coalesce(refunds.c.total, 0).label("total"))
        .join(captures, captures.c.payment_id == Payment.id)
        .outerjoin(refunds, refunds.c.payment_id == Payment.id)
        .where(_round(Payment.refunded_amount) != _round(func.coalesce(refunds.c.total, 0)))
        .order_by(Payment.id)
    ):
        divergences.append(_amounts("C2", row.id, row.currency, row.refunded_amount, row.total))

    divergences.extend(_event_mismatches(db))

    # C4 y `outside_ledger`: cobros con dinero capturado y sin ninguna entrada de captura.
    epoch = db.scalar(select(func.min(Entry.recorded_at)))
    uncovered = db.execute(
        select(Payment.id, Payment.currency, Payment.captured_amount)
        .outerjoin(captures, captures.c.payment_id == Payment.id)
        .where(Payment.captured_amount > 0, captures.c.total.is_(None))
        .order_by(Payment.id)
    ).all()
    for row in uncovered:
        applied_at = db.scalar(
            select(func.min(PaymentEvent.processed_at)).where(
                PaymentEvent.payment_id == row.id,
                PaymentEvent.event_type == CAPTURE_EVENT_TYPE,
                PaymentEvent.processing_status == EventProcessing.APPLIED.value,
            )
        )
        item = _amounts("C4", row.id, row.currency, row.captured_amount, 0)
        if epoch is None or applied_at is None or _aware(applied_at) < _aware(epoch):
            outside.append({k: item[k] for k in ("payment_id", "currency", "payment")})
        else:
            divergences.append(item)

    return {
        "entries": int(db.scalar(select(func.count(Entry.id))) or 0),
        "divergences": {"count": len(divergences), "items": divergences[:limit]},
        "outside_ledger": {"count": len(outside), "items": outside[:limit]},
    }


def _amounts(check: str, payment_id: str, currency: str, payment_side: object, ledger_side: object) -> dict:
    return {
        "check": check,
        "payment_id": payment_id,
        "currency": currency,
        "payment": money(payment_side),
        "ledger": money(_dec(ledger_side)),
    }


def _event_mismatches(db: Session) -> list[dict]:
    """C3: cada entrada contra el evento que dice haberla causado."""
    expected_type = case((Entry.kind == EntryKind.CAPTURE.value, CAPTURE_EVENT_TYPE), else_=REFUND_EVENT_TYPE)
    rows = db.execute(
        select(
            Entry.id,
            Entry.payment_id,
            Entry.amount,
            Entry.currency,
            PaymentEvent.processing_status,
            PaymentEvent.event_type,
            PaymentEvent.amount.label("event_amount"),
            PaymentEvent.currency.label("event_currency"),
            PaymentEvent.payment_id.label("event_payment_id"),
            expected_type.label("expected_type"),
        )
        .join(PaymentEvent, PaymentEvent.id == Entry.payment_event_id)
        .where(
            or_(
                PaymentEvent.processing_status != EventProcessing.APPLIED.value,
                PaymentEvent.event_type != expected_type,
                PaymentEvent.amount.is_(None),
                _round(PaymentEvent.amount) != _round(Entry.amount),
                PaymentEvent.currency != Entry.currency,
                PaymentEvent.payment_id.is_(None),
                PaymentEvent.payment_id != Entry.payment_id,
            )
        )
        .order_by(Entry.id)
    ).all()
    found = []
    for row in rows:
        reasons = []
        if row.processing_status != EventProcessing.APPLIED.value:
            reasons.append("the event is not APPLIED")
        if row.event_type != row.expected_type:
            reasons.append("the event type does not produce this kind of entry")
        if row.event_amount is None or _dec(row.event_amount) != _dec(row.amount):
            reasons.append("the amount differs from the event")
        if row.event_currency != row.currency:
            reasons.append("the currency differs from the event")
        if row.event_payment_id != row.payment_id:
            reasons.append("the event names another payment")
        found.append({"check": "C3", "entry_id": row.id, "payment_id": row.payment_id, "reasons": reasons})
    return found
