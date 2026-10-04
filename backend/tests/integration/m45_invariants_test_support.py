"""Los invariantes del registro de ingresos verificados como una función (Milestone 45, ADR 0030).

Módulo auxiliar de tests, **no** un test. Es el hermano de `m44_invariants_test_support.check_invariants`: aquel mira
pedidos, cobros, reembolsos y fulfillments; éste mira **el dinero que el registro dice haber verificado** y lo
contrasta, fila a fila, con lo que dicen los cobros, los reembolsos y los eventos.

Es un **oráculo independiente**: no importa `app.revenue.check` ni `app.revenue.ledger` (que son lo que se prueba) y
escribe a mano el vocabulario (`payment.succeeded`, `ORDER_PAYMENT`…). Si el código y el oráculo se equivocaran igual,
habría que haberlo copiado, y no se ha copiado. Lo único que sí se llama es `app.revenue.aggregates.summary`, **para
comparar su respuesta con el oráculo**, no para calcular nada con ella.

Cada comprobación sale de algo escrito (el ADR 0030, una restricción de la base, una promesa de la API), y los mensajes
dicen qué entrada y qué cifra, para que un fallo de una semilla se pueda reproducir. Vacío = todo en orden.

`LedgerWatch` añade lo que una foto no ve: el registro es **append-only**, y eso solo se comprueba **a lo largo del
tiempo**. Cada paso recuerda lo que vio, y el siguiente exige que siga igual y que no haya desaparecido nada.
"""

import datetime
from collections import defaultdict
from decimal import Decimal

from m44_invariants_test_support import check_invariants
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.order import Order
from app.db.models.payment import Payment, PaymentEvent, Refund
from app.db.models.revenue import RevenueLedgerEntry
from app.revenue.aggregates import Period, summary

ZERO = Decimal(0)

#: El vocabulario del ADR 0030 §3, escrito a mano (a propósito: no se importa de `app.revenue.domain`).
CAPTURE_EVENT = "payment.succeeded"
REFUND_EVENT = "refund.succeeded"
CLASSIFICATION_OF_PAYMENT = {
    "SUCCEEDED": "ORDER_PAYMENT",
    "DUPLICATE_CAPTURE": "DUPLICATE_RECEIPT",
    "CAPTURE_MISMATCH": "MISMATCH_RECEIPT",
}
#: Los estados de un evento que **no** son dinero asentado: nunca pueden tener una entrada.
NOT_SETTLED = {"RECEIVED", "STALE", "CONFLICT", "UNMATCHED", "REJECTED"}
UNDER_REVIEW = ("DUPLICATE_RECEIPT", "MISMATCH_RECEIPT")


def _dec(value: object) -> Decimal:
    return Decimal(str(value if value is not None else 0))


def _aware(value: datetime.datetime) -> datetime.datetime:
    """SQLite devuelve fechas sin zona; todas las que se guardan son UTC."""
    return value if value.tzinfo is not None else value.replace(tzinfo=datetime.UTC)


def check_revenue_invariants(db: Session) -> list[str]:
    db.expire_all()
    entries = list(db.scalars(select(RevenueLedgerEntry)))
    events = {e.id: e for e in db.scalars(select(PaymentEvent))}
    payments = {p.id: p for p in db.scalars(select(Payment))}
    refunds = {r.id: r for r in db.scalars(select(Refund))}
    orders = {o.id: o for o in db.scalars(select(Order))}

    broken: list[str] = []
    broken += _each_entry_is_backed_by_a_verified_event(entries, events, payments, refunds, orders)
    broken += _each_payment_matches_its_entries(entries, payments)
    broken += _refunds_never_exceed_what_was_captured(entries, payments, refunds)
    broken += _an_order_is_paid_only_with_verified_revenue(entries, payments, orders)
    broken += _no_event_that_is_not_settled_moves_the_ledger(entries, events)
    broken += _the_aggregates_say_what_the_entries_say(db, entries, events)
    return broken


# --- 1. Cada entrada tiene un hecho verificado detrás ---------------------------------------------------------------


def _each_entry_is_backed_by_a_verified_event(entries, events, payments, refunds, orders) -> list[str]:
    broken: list[str] = []
    for entry in entries:
        tag = f"ledger entry {entry.id} ({entry.kind} {entry.amount} {entry.currency})"
        event = events.get(entry.payment_event_id)
        payment = payments.get(entry.payment_id)

        if event is None:
            broken.append(f"{tag}: no PaymentEvent {entry.payment_event_id} behind it")
            continue
        if event.processing_status != "APPLIED":
            broken.append(f"{tag}: its event is {event.processing_status}, only an APPLIED event is money")
        wanted = CAPTURE_EVENT if entry.kind == "CAPTURE" else REFUND_EVENT
        if event.event_type != wanted:
            broken.append(f"{tag}: a {entry.kind} entry caused by a {event.event_type!r} event (wanted {wanted!r})")
        if event.amount is None or _dec(event.amount) != _dec(entry.amount):
            broken.append(f"{tag}: amount differs from its event ({event.amount})")
        if event.currency != entry.currency:
            broken.append(f"{tag}: currency differs from its event ({event.currency})")
        if _aware(event.occurred_at) != _aware(entry.occurred_at):
            broken.append(f"{tag}: occurred_at is not the event's (the ledger counts when it HAPPENED)")

        if payment is None:
            broken.append(f"{tag}: payment {entry.payment_id} does not exist")
            continue
        if payment.order_id != entry.order_id or entry.order_id not in orders:
            broken.append(f"{tag}: order {entry.order_id} is not the payment's order {payment.order_id}")
        if payment.currency != entry.currency:
            broken.append(f"{tag}: currency {entry.currency} differs from the payment's {payment.currency}")
        if _dec(entry.amount) <= ZERO:
            broken.append(f"{tag}: non-positive amount")

        if entry.kind == "REFUND":
            refund = refunds.get(entry.refund_id or "")
            if refund is None:
                broken.append(f"{tag}: names refund {entry.refund_id}, which does not exist")
            else:
                if refund.status != "SUCCEEDED":
                    broken.append(f"{tag}: refund {refund.id} is {refund.status}, only a confirmed refund is an entry")
                if _dec(refund.amount) != _dec(entry.amount):
                    broken.append(f"{tag}: refund {refund.id} says {refund.amount}")
                if refund.payment_id != entry.payment_id:
                    broken.append(f"{tag}: refund {refund.id} belongs to another payment")
    return broken


# --- 2. Cada cobro cuadra con sus entradas -----------------------------------------------------------------------


def _each_payment_matches_its_entries(entries, payments) -> list[str]:
    broken: list[str] = []
    by_payment: dict[str, list[RevenueLedgerEntry]] = defaultdict(list)
    for entry in entries:
        by_payment[entry.payment_id].append(entry)

    for payment in payments.values():
        tag = f"payment {payment.id} ({payment.status})"
        own = by_payment.get(payment.id, [])
        captures = [e for e in own if e.kind == "CAPTURE"]
        refunded = sum((_dec(e.amount) for e in own if e.kind == "REFUND"), ZERO)

        if len(captures) > 1:
            broken.append(f"{tag}: {len(captures)} capture entries (a payment is captured once)")
        if _dec(payment.captured_amount) > ZERO:
            if len(captures) != 1:
                broken.append(f"{tag}: captured {payment.captured_amount} but {len(captures)} capture entries")
            else:
                capture = captures[0]
                if _dec(capture.amount) != _dec(payment.captured_amount):
                    broken.append(f"{tag}: ledger captured {capture.amount}, payment says {payment.captured_amount}")
                if capture.classification != CLASSIFICATION_OF_PAYMENT.get(payment.status):
                    broken.append(
                        f"{tag}: classified {capture.classification}, the payment state dictates "
                        f"{CLASSIFICATION_OF_PAYMENT.get(payment.status)}"
                    )
        elif captures:
            broken.append(f"{tag}: a capture entry for a payment that captured nothing")

        if refunded != _dec(payment.refunded_amount):
            broken.append(f"{tag}: ledger refunded {refunded}, payment says {payment.refunded_amount}")

        for refund_entry in (e for e in own if e.kind == "REFUND"):
            capture = captures[0] if len(captures) == 1 else None
            if capture is None:
                broken.append(f"{tag}: a refund entry {refund_entry.id} without its capture entry")
            elif (refund_entry.capture_entry_id, refund_entry.classification, refund_entry.currency) != (
                capture.id,
                capture.classification,
                capture.currency,
            ):
                broken.append(f"{tag}: refund entry {refund_entry.id} does not inherit its capture")
    return broken


# --- 3. Un reembolso no supera lo capturado -----------------------------------------------------------------------


def _refunds_never_exceed_what_was_captured(entries, payments, refunds) -> list[str]:
    broken: list[str] = []
    for payment in payments.values():
        own = [e for e in entries if e.payment_id == payment.id]
        captured = sum((_dec(e.amount) for e in own if e.kind == "CAPTURE"), ZERO)
        returned = sum((_dec(e.amount) for e in own if e.kind == "REFUND"), ZERO)
        if returned > captured:
            broken.append(f"payment {payment.id}: refunded {returned} in the ledger, captured only {captured}")
        # Y lo que las filas dicen, que incluye lo reservado por un reembolso en vuelo (ADR 0028 §5).
        committed = sum(
            (_dec(r.amount) for r in refunds.values() if r.payment_id == payment.id and r.status != "FAILED"), ZERO
        )
        if committed > _dec(payment.captured_amount):
            broken.append(
                f"payment {payment.id}: {committed} of refunds in flight or done exceed the captured "
                f"{payment.captured_amount}"
            )
    return broken


# --- 4. Un pedido solo está pagado con ingreso verificado detrás -------------------------------------------------


def _an_order_is_paid_only_with_verified_revenue(entries, payments, orders) -> list[str]:
    broken: list[str] = []
    for order in orders.values():
        if order.status != "PAID":
            continue
        verified = [
            e for e in entries if e.order_id == order.id and e.kind == "CAPTURE" and e.classification == "ORDER_PAYMENT"
        ]
        if len(verified) != 1:
            broken.append(f"order {order.id} is PAID with {len(verified)} verified capture entries (wanted exactly 1)")
        elif _dec(verified[0].amount) != _dec(order.amount_due):
            broken.append(
                f"order {order.id} is PAID for {order.amount_due} but its verified entry is {verified[0].amount}"
            )
    return broken


# --- 5. Lo que no es dinero asentado no mueve el registro -------------------------------------------------------


def _no_event_that_is_not_settled_moves_the_ledger(entries, events) -> list[str]:
    caused = {e.payment_event_id for e in entries}
    return [
        f"event {event.id} ({event.event_type}) is {event.processing_status} and has a ledger entry"
        for event in events.values()
        if event.processing_status in NOT_SETTLED and event.id in caused
    ]


# --- 6. Los agregados dicen lo que dicen las entradas ----------------------------------------------------------


def _the_aggregates_say_what_the_entries_say(db: Session, entries, events) -> list[str]:
    """Calcula a mano, por moneda, lo verificado y lo que está en revisión, y lo compara con lo que responde
    `summary`. Si los dos coinciden en TODO, ni las monedas se mezclan, ni la revisión entra en el titular, ni la
    evidencia pendiente suma, ni nada se cuenta dos veces."""
    broken: list[str] = []
    expected: dict[tuple[str, str, str], list] = defaultdict(lambda: [0, ZERO])
    for entry in entries:
        cell = expected[(entry.currency, entry.classification, entry.kind)]
        cell[0] += 1
        cell[1] += _dec(entry.amount)

    answer = summary(db, Period())
    if answer["entries"] != len(entries):
        broken.append(f"summary counts {answer['entries']} entries, there are {len(entries)}")

    reported_verified = {row["currency"]: row for row in answer["verified"]}
    currencies = sorted({currency for currency, _, _ in expected})
    for currency in currencies:
        captured = expected.get((currency, "ORDER_PAYMENT", "CAPTURE"), [0, ZERO])
        returned = expected.get((currency, "ORDER_PAYMENT", "REFUND"), [0, ZERO])
        row = reported_verified.get(currency)
        if captured[0] or returned[0]:
            if row is None:
                broken.append(f"summary has no verified block for {currency}")
            else:
                for key, value in (
                    ("revenue", captured[1]),
                    ("refunds", returned[1]),
                    ("net", captured[1] - returned[1]),
                ):
                    if _dec(row[key]) != value:
                        broken.append(f"summary {currency} {key} is {row[key]}, the entries add up to {value}")
        elif row is not None:
            broken.append(f"summary reports verified revenue in {currency} with no ORDER_PAYMENT entries")

        reported_review = {(r["currency"], r["classification"]): r for r in answer["under_review"]}
        for classification in UNDER_REVIEW:
            received = expected.get((currency, classification, "CAPTURE"), [0, ZERO])
            refunded = expected.get((currency, classification, "REFUND"), [0, ZERO])
            row = reported_review.get((currency, classification))
            if received[0] or refunded[0]:
                if row is None or _dec(row["received"]) != received[1] or _dec(row["refunded"]) != refunded[1]:
                    broken.append(f"summary under_review {currency} {classification} differs from the entries")
            elif row is not None:
                broken.append(f"summary reports {classification} money in {currency} that no entry has")

    # La revisión **nunca** entra en el titular: el consolidado EUR es solo ORDER_PAYMENT.
    eur = answer["consolidated_eur"]
    if eur is not None:
        captured = expected.get(("EUR", "ORDER_PAYMENT", "CAPTURE"), [0, ZERO])[1]
        returned = expected.get(("EUR", "ORDER_PAYMENT", "REFUND"), [0, ZERO])[1]
        if _dec(eur["revenue"]) != captured or _dec(eur["net"]) != captured - returned:
            broken.append(f"consolidated EUR {eur['revenue']}/{eur['net']} is not the ORDER_PAYMENT entries alone")
    elif any(currency == "EUR" for currency, _, _ in expected):
        broken.append("there are EUR entries and no consolidated EUR block")

    # La evidencia pendiente es dinero **sin asentar**: cuenta aparte y nunca estuvo en las entradas.
    pending = sum(
        1
        for e in events.values()
        if e.processing_status in ("CONFLICT", "UNMATCHED")
        and e.amount is not None
        and e.event_type in (CAPTURE_EVENT, REFUND_EVENT)
    )
    if answer["pending_evidence"]["count"] > pending:
        broken.append(f"summary counts {answer['pending_evidence']['count']} pending events, only {pending} can be")
    return broken


# --- El registro no se reescribe nunca ---------------------------------------------------------------------------


class LedgerWatch:
    """Recuerda lo que el registro dijo y exige, en cada paso, que no haya cambiado ni desaparecido nada."""

    def __init__(self) -> None:
        self._seen: dict[str, tuple] = {}

    def check(self, db: Session) -> list[str]:
        db.expire_all()
        now = {
            e.id: (
                e.kind,
                e.classification,
                e.payment_event_id,
                e.payment_id,
                e.order_id,
                e.refund_id,
                e.capture_entry_id,
                _dec(e.amount),
                e.currency,
                _aware(e.occurred_at),
                _aware(e.recorded_at),
            )
            for e in db.scalars(select(RevenueLedgerEntry))
        }
        broken = [
            f"ledger entry {entry_id} disappeared (the ledger is append-only)"
            for entry_id in self._seen
            if entry_id not in now
        ]
        broken += [
            f"ledger entry {entry_id} was rewritten: {self._seen[entry_id]} -> {value}"
            for entry_id, value in now.items()
            if entry_id in self._seen and self._seen[entry_id] != value
        ]
        self._seen.update(now)
        return broken


def check_everything(db: Session) -> list[str]:
    """Los invariantes de M44 y los de M45 a la vez."""
    return check_invariants(db) + check_revenue_invariants(db)
