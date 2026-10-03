"""La evidencia económica pendiente de revisión, de **solo lectura** (ADR 0030 §4, decisión D1).

Un evento de dinero que no se pudo asentar (`CONFLICT`: contradice un hecho ya registrado o no se puede aplicar sin
inventar; `UNMATCHED`: ningún cobro nuestro lo explica) **no** genera una entrada del registro ni se cuenta como
ingreso, pero tampoco desaparece: se conserva sin alterar su evidencia original en `payment_events` y aquí se hace
visible, por moneda, con su nota y su edad. Ni cuerpos ni hashes del evento.

Solo cuentan los eventos que mueven dinero (`payment.succeeded` y `refund.succeeded`) con importe: un
`payment.failed` o un `refund.failed` no es dinero recibido ni devuelto.
"""

import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.payment import PaymentEvent
from app.payments.domain import EventProcessing
from app.revenue.domain import CAPTURE_EVENT_TYPE, REFUND_EVENT_TYPE

#: Cuántos elementos concretos lista la evidencia (el resto se cuenta, no se lista).
LISTED_EVIDENCE = 50

PENDING_STATUSES = (EventProcessing.CONFLICT.value, EventProcessing.UNMATCHED.value)
MONEY_EVENT_TYPES = (CAPTURE_EVENT_TYPE, REFUND_EVENT_TYPE)
_PLACES = Decimal("0.0001")


def _aware(value: datetime.datetime) -> datetime.datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=datetime.UTC)


def money(value: object) -> str:
    """Un importe exacto como texto (nunca `float`)."""
    return format(Decimal(str(value)).quantize(_PLACES), "f")


def _is_pending_money_event():
    return (
        PaymentEvent.processing_status.in_(PENDING_STATUSES),
        PaymentEvent.event_type.in_(MONEY_EVENT_TYPES),
        PaymentEvent.amount.is_not(None),
    )


def pending_economic_evidence(
    db: Session, *, now: datetime.datetime | None = None, limit: int = LISTED_EVIDENCE
) -> dict:
    moment = now or datetime.datetime.now(datetime.UTC)
    totals = db.execute(
        select(
            PaymentEvent.currency,
            PaymentEvent.event_type,
            func.count(PaymentEvent.id),
            func.sum(PaymentEvent.amount),
        )
        .where(*_is_pending_money_event())
        .group_by(PaymentEvent.currency, PaymentEvent.event_type)
        .order_by(PaymentEvent.currency, PaymentEvent.event_type)
    ).all()
    events = db.scalars(
        select(PaymentEvent)
        .where(*_is_pending_money_event())
        .order_by(PaymentEvent.received_at, PaymentEvent.id)
        .limit(limit)
    ).all()
    return {
        "count": sum(int(row[2]) for row in totals),
        "by_currency": [
            {"currency": row[0], "event_type": row[1], "count": int(row[2]), "amount": money(row[3])} for row in totals
        ],
        "items": [
            {
                "id": event.id,
                "status": event.processing_status,
                "event_type": event.event_type,
                "provider": event.provider,
                "amount": money(event.amount),
                "currency": event.currency,
                "payment_id": event.payment_id,
                "refund_id": event.refund_id,
                "note": event.note,
                "occurred_at": _aware(event.occurred_at).isoformat(),
                "age_seconds": max(0, int((moment - _aware(event.received_at)).total_seconds())),
            }
            for event in events
        ],
    }
