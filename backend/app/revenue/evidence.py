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

from sqlalchemy import ColumnElement, func, select
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
    """Siempre en UTC: PostgreSQL devuelve las fechas en la zona de la sesión y SQLite sin zona."""
    return value.replace(tzinfo=datetime.UTC) if value.tzinfo is None else value.astimezone(datetime.UTC)


def money(value: object) -> str:
    """Un importe exacto como texto (nunca `float`)."""
    return format(Decimal(str(value)).quantize(_PLACES), "f")


def _is_pending_money_event(start: datetime.datetime | None = None, end: datetime.datetime | None = None):
    """Las condiciones de un evento de dinero sin asentar; opcionalmente, en un rango de `occurred_at` (`start`
    inclusivo, `end` exclusivo)."""
    found: list[ColumnElement[bool]] = [
        PaymentEvent.processing_status.in_(PENDING_STATUSES),
        PaymentEvent.event_type.in_(MONEY_EVENT_TYPES),
        PaymentEvent.amount.is_not(None),
    ]
    if start is not None:
        found.append(PaymentEvent.occurred_at >= start)
    if end is not None:
        found.append(PaymentEvent.occurred_at < end)
    return tuple(found)


def pending_evidence_totals(
    db: Session, *, start: datetime.datetime | None = None, end: datetime.datetime | None = None
) -> dict:
    """Cuántos eventos hay sin asentar y cuánto dinero dicen, por moneda y tipo, sin listarlos. Un agregado: no suma
    monedas distintas ni entra en ningún total de ingresos."""
    totals = db.execute(
        select(
            PaymentEvent.currency,
            PaymentEvent.event_type,
            func.count(PaymentEvent.id),
            func.sum(PaymentEvent.amount),
        )
        .where(*_is_pending_money_event(start, end))
        .group_by(PaymentEvent.currency, PaymentEvent.event_type)
        .order_by(PaymentEvent.currency, PaymentEvent.event_type)
    ).all()
    return {
        "count": sum(int(row[2]) for row in totals),
        "by_currency": [
            {"currency": row[0], "event_type": row[1], "count": int(row[2]), "amount": money(row[3])} for row in totals
        ],
    }


def pending_economic_evidence(
    db: Session, *, now: datetime.datetime | None = None, limit: int = LISTED_EVIDENCE
) -> dict:
    moment = now or datetime.datetime.now(datetime.UTC)
    events = db.scalars(
        select(PaymentEvent)
        .where(*_is_pending_money_event())
        .order_by(PaymentEvent.received_at, PaymentEvent.id)
        .limit(limit)
    ).all()
    return {
        **pending_evidence_totals(db),
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
