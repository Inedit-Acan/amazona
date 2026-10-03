# ruff: noqa: F811 - los fixtures de pytest se importan del módulo de apoyo y los tests los piden por su nombre
"""El registro de ingresos verificados proyecta los hechos de pago, y solo ellos (Milestone 45, ADR 0030 §4–§9).

Sobre SQLite y sobre un PostgreSQL de verdad. Todo entra por la puerta de eventos, como un webhook: lo que se afirma es
que `PaymentService` escribe la entrada **en la misma transacción** que el hecho económico, con su procedencia, su
clasificación y sin inventar nada: un `CONFLICT`, un `UNMATCHED`, un duplicado de evento o un reembolso sin confirmar no
cuentan como ingreso, y lo que no cuenta tampoco desaparece.
"""

import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from payment_test_support import deliver, events, ingress, payments_of, start_attempt
from reconciliation_test_support import db, engine, factory  # noqa: F401 - fixtures de pytest
from revenue_test_support import (
    EXPIRED,
    REFUND_FAILED,
    SIMULATION,
    SUCCEEDED,
    ScriptedPaymentProvider,
    aware,
    capture,
    capture_entry,
    confirm_refund,
    duplicate_pair,
    entries,
    mismatched_capture,
    new_order,
    provider_refund,
    refund_event,
    refund_of,
    reload,
)
from sqlalchemy import delete, select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.db.models.audit import AuditLog
from app.db.models.order import Order
from app.db.models.payment import Payment, PaymentEvent, Refund
from app.db.models.revenue import RevenueLedgerEntry
from app.money.money import Money
from app.orders.service import OrderService
from app.payments.port import PaymentEventType
from app.payments.service import PaymentService
from app.revenue.domain import Classification, classify_capture
from app.revenue.evidence import pending_economic_evidence
from app.revenue.ledger import RevenueLedger, RevenueLedgerWriteError

OCCURRED = datetime.datetime(2026, 10, 3, 9, 0, tzinfo=datetime.UTC)


@pytest.fixture()
def provider() -> ScriptedPaymentProvider:
    return ScriptedPaymentProvider()


# --- La captura normal ---------------------------------------------------------------------------------------------


def test_a_normal_capture_projects_one_order_payment_entry_with_its_whole_provenance(db: Session, provider):
    order = new_order(db)
    payment = capture(db, provider, order, occurred_at=OCCURRED)

    (entry,) = entries(db)
    (event,) = events(db)

    assert (entry.kind, entry.classification) == ("CAPTURE", "ORDER_PAYMENT")
    assert (entry.payment_event_id, entry.payment_id, entry.order_id) == (event.id, payment.id, order.id)
    assert entry.refund_id is None and entry.capture_entry_id is None
    assert entry.amount == Decimal("50") == Decimal(str(payment.captured_amount)) and entry.currency == "EUR"
    assert aware(entry.occurred_at) == OCCURRED, "the moment of the fact, not the moment it arrived"
    assert aware(entry.recorded_at) > OCCURRED and event.processing_status == "APPLIED"


def test_a_duplicate_capture_is_money_under_review_not_revenue(db: Session, provider):
    order = new_order(db)
    canonical, duplicate = duplicate_pair(db, provider, order)
    assert (canonical.status, duplicate.status) == ("SUCCEEDED", "DUPLICATE_CAPTURE")

    by_payment = {e.payment_id: e for e in entries(db)}

    assert len(by_payment) == 2
    assert by_payment[canonical.id].classification == "ORDER_PAYMENT"
    assert by_payment[duplicate.id].classification == "DUPLICATE_RECEIPT"
    assert all(
        e.kind == "CAPTURE" and e.order_id == order.id and e.amount == Decimal("50") for e in by_payment.values()
    )
    assert duplicate.duplicate_of_payment_id == canonical.id, "the original is reconstructible from the payment"


def test_a_capture_of_another_amount_is_recorded_for_what_was_really_captured(db: Session, provider):
    payment = mismatched_capture(db, provider, new_order(db), "12.50")
    assert payment.status == "CAPTURE_MISMATCH"

    (entry,) = entries(db)

    assert (entry.classification, entry.amount, entry.payment_id) == ("MISMATCH_RECEIPT", Decimal("12.5"), payment.id)


def test_money_captured_late_on_a_cancelled_order_is_recorded_and_the_order_is_not_reopened(db: Session, provider):
    order = new_order(db)
    payment = start_attempt(db, order, provider)
    deliver(db, provider, EXPIRED, payment)
    OrderService(db, settings=SIMULATION).cancel(order.id, actor="t")
    deliver(db, provider, SUCCEEDED, payment)

    (entry,) = entries(db)

    assert entry.classification == "ORDER_PAYMENT" and entry.amount == Decimal("50")
    assert reload(db, order).status == "CANCELLED", "an entry never reopens or changes the order"


def test_the_visible_state_of_an_order_never_creates_an_entry(db: Session, provider):
    order = new_order(db)
    start_attempt(db, order, provider)
    db.execute(update(Order).where(Order.id == order.id).values(status="PAID"))
    db.commit()

    assert entries(db) == [], "PAID on an order is not a verified fact of money"


# --- Idempotencia --------------------------------------------------------------------------------------------------


def test_the_same_capture_delivered_twice_is_one_entry(db: Session, provider):
    payment = start_attempt(db, new_order(db), provider)
    first = deliver(db, provider, SUCCEEDED, payment, event_id="evt_same", occurred_at=OCCURRED)
    second = deliver(db, provider, SUCCEEDED, payment, event_id="evt_same", occurred_at=OCCURRED)

    assert (first.outcome, second.outcome, second.duplicate) == ("applied", "applied", True)
    assert len(entries(db)) == 1


def test_the_same_capture_announced_under_another_event_id_adds_no_entry(db: Session, provider):
    payment = capture(db, provider, new_order(db), event_id="evt_a")
    again = deliver(db, provider, SUCCEEDED, payment, event_id="evt_b")

    assert again.outcome == "stale" and len(entries(db)) == 1


def test_a_second_capture_event_with_another_amount_is_a_conflict_with_no_entry_and_stays_visible(
    db: Session, provider
):
    payment = capture(db, provider, new_order(db), event_id="evt_a")
    other = deliver(db, provider, SUCCEEDED, payment, event_id="evt_b", amount="49.00")

    assert other.outcome == "conflict" and len(entries(db)) == 1
    evidence = pending_economic_evidence(db)
    assert evidence["count"] == 1 and evidence["items"][0]["status"] == "CONFLICT"
    assert evidence["items"][0]["amount"] == "49.0000"


# --- CONFLICT y UNMATCHED con dinero: visibles, no ingreso ---------------------------------------------------------


def test_a_capture_in_another_currency_is_kept_as_pending_evidence_and_is_not_revenue(db: Session, provider):
    payment = start_attempt(db, new_order(db), provider)
    result = deliver(db, provider, SUCCEEDED, payment, currency="USD")

    assert result.outcome == "conflict"
    assert entries(db) == []
    assert Decimal(str(reload(db, payment).captured_amount)) == 0
    evidence = pending_economic_evidence(db)
    assert evidence["by_currency"] == [
        {"currency": "USD", "event_type": "payment.succeeded", "count": 1, "amount": "50.0000"}
    ]
    stored = events(db)[0]
    assert stored.processing_status == "CONFLICT" and stored.currency == "USD" and stored.amount == Decimal("50")


def test_an_event_that_matches_none_of_our_payments_is_kept_as_pending_evidence_and_is_not_revenue(
    db: Session, provider
):
    start_attempt(db, new_order(db), provider)
    headers, raw = provider.simulate_event(
        SUCCEEDED,
        provider_payment_ref="simpay_stranger",
        client_reference="no-such-payment",
        amount=Money.of("5.00", "EUR"),
    )
    result = ingress(db, provider).receive(provider.name, headers, raw)

    assert result.outcome == "unmatched" and entries(db) == []
    evidence = pending_economic_evidence(db)
    assert [(i["status"], i["amount"], i["currency"]) for i in evidence["items"]] == [("UNMATCHED", "5.0000", "EUR")]


def test_a_provider_refund_that_does_not_fit_is_pending_evidence_and_moves_no_entry(db: Session, provider):
    payment = capture(db, provider, new_order(db))

    result = provider_refund(db, provider, payment, "50.01", "simref_big", "evt_big")

    assert result.outcome == "conflict"
    assert [e.kind for e in entries(db)] == ["CAPTURE"]
    evidence = pending_economic_evidence(db)
    assert [(r["event_type"], r["amount"]) for r in evidence["by_currency"]] == [("refund.succeeded", "50.0100")]


def test_events_that_move_no_money_are_never_entries_or_evidence(db: Session, provider):
    order = new_order(db)
    failed = start_attempt(db, order, provider)
    deliver(db, provider, PaymentEventType.PAYMENT_ATTEMPT_FAILED, failed)
    deliver(db, provider, EXPIRED, failed)
    payment = capture(db, provider, order, event_id="evt_ok")
    deliver(db, provider, SUCCEEDED, payment, event_id="evt_ok_again")  # STALE: nothing new

    assert len(entries(db)) == 1
    assert pending_economic_evidence(db) == {"count": 0, "by_currency": [], "items": []}


def test_a_closing_event_that_contradicts_a_capture_is_a_conflict_but_is_not_money_evidence(db: Session, provider):
    payment = capture(db, provider, new_order(db))

    result = deliver(db, provider, PaymentEventType.PAYMENT_FAILED, payment, amount="50.00")

    assert result.outcome == "conflict" and events(db)[-1].amount == Decimal("50")
    assert pending_economic_evidence(db)["count"] == 0, "a payment.failed is not money received or returned"
    assert len(entries(db)) == 1


def test_pending_evidence_carries_no_body_hash_or_data(db: Session, provider):
    deliver(db, provider, SUCCEEDED, start_attempt(db, new_order(db), provider), currency="USD")

    (item,) = pending_economic_evidence(db)["items"]

    assert set(item) == {
        "id", "status", "event_type", "provider", "amount", "currency", "payment_id", "refund_id", "note",
        "occurred_at", "age_seconds",
    }  # fmt: skip


# --- Reembolsos: heredan la clasificación de la captura que revierten ----------------------------------------------


def test_a_confirmed_refund_of_a_normal_capture_reduces_verified_revenue(db: Session, provider):
    payment = capture(db, provider, new_order(db))
    refund = refund_of(db, provider, payment, "20.00")
    assert [e.kind for e in entries(db)] == ["CAPTURE"], "accepted by the provider is not money returned"

    confirm_refund(db, provider, refund)

    cap, ref = capture_entry(db, payment), entries(db)[-1]
    assert (ref.kind, ref.classification, ref.amount) == ("REFUND", "ORDER_PAYMENT", Decimal("20"))
    assert (ref.capture_entry_id, ref.refund_id, ref.payment_id, ref.order_id) == (
        cap.id,
        refund.id,
        payment.id,
        payment.order_id,
    )
    assert ref.currency == cap.currency


def test_a_failed_or_unconfirmed_refund_adds_no_entry(db: Session, provider):
    payment = capture(db, provider, new_order(db))
    refund = refund_of(db, provider, payment, "20.00")
    refund_event(db, provider, refund, REFUND_FAILED)

    assert [e.kind for e in entries(db)] == ["CAPTURE"]


def test_refunding_a_duplicate_reduces_the_money_under_review_not_the_revenue(db: Session, provider):
    canonical, duplicate = duplicate_pair(db, provider, new_order(db))
    refund = refund_of(db, provider, duplicate, "50.00", reason="duplicate_capture")

    confirm_refund(db, provider, refund)

    ref = [e for e in entries(db) if e.kind == "REFUND"][0]
    assert ref.classification == "DUPLICATE_RECEIPT"
    assert ref.capture_entry_id == capture_entry(db, duplicate).id
    assert ref.capture_entry_id != capture_entry(db, canonical).id, "it never touches the legitimate revenue"


def test_refunding_a_mismatched_capture_inherits_the_mismatch_classification(db: Session, provider):
    payment = mismatched_capture(db, provider, new_order(db), "12.50")
    refund = refund_of(db, provider, payment, "12.50", reason="capture_mismatch")

    confirm_refund(db, provider, refund)

    ref = [e for e in entries(db) if e.kind == "REFUND"][0]
    assert (ref.classification, ref.amount) == ("MISMATCH_RECEIPT", Decimal("12.5"))


def test_partial_refunds_add_up_to_what_the_payment_says_was_refunded(db: Session, provider):
    payment = capture(db, provider, new_order(db))
    for amount in ("10.00", "15.00", "5.50"):
        confirm_refund(db, provider, refund_of(db, provider, payment, amount))

    refunds_total = sum((e.amount for e in entries(db) if e.kind == "REFUND"), Decimal(0))
    payment = reload(db, payment)

    assert refunds_total == Decimal("30.5") == Decimal(str(payment.refunded_amount))
    assert len([e for e in entries(db) if e.kind == "REFUND"]) == 3


def test_the_same_refund_confirmed_twice_is_one_entry(db: Session, provider):
    payment = capture(db, provider, new_order(db))
    refund = refund_of(db, provider, payment, "20.00")
    first = confirm_refund(db, provider, refund, event_id="evt_r1")
    second = confirm_refund(db, provider, refund, event_id="evt_r2")

    assert (first.outcome, second.outcome) == ("applied", "stale")
    assert len([e for e in entries(db) if e.kind == "REFUND"]) == 1


def test_a_refund_the_provider_made_by_itself_is_projected_with_the_refund_that_was_created(db: Session, provider):
    payment = capture(db, provider, new_order(db))

    result = provider_refund(db, provider, payment, "20.00", "simref_dash_1", "evt_dash_1")

    assert result.outcome == "applied"
    refund = db.scalars(select(Refund)).one()
    ref = [e for e in entries(db) if e.kind == "REFUND"][0]
    assert refund.origin == "PROVIDER" and ref.refund_id == refund.id
    assert (ref.classification, ref.amount, ref.capture_entry_id) == (
        "ORDER_PAYMENT",
        Decimal("20"),
        capture_entry(db, payment).id,
    )


def test_the_same_provider_refund_under_two_event_ids_is_one_entry(db: Session, provider):
    payment = capture(db, provider, new_order(db))
    provider_refund(db, provider, payment, "20.00", "simref_same", "evt_x")
    again = provider_refund(db, provider, payment, "20.00", "simref_same", "evt_y")

    assert again.outcome == "stale" and len([e for e in entries(db) if e.kind == "REFUND"]) == 1


# --- Atomicidad: el hecho y su entrada, o nada ---------------------------------------------------------------------


def test_when_the_entry_cannot_be_written_the_event_is_not_applied_and_nothing_changes(
    db: Session, provider, monkeypatch
):
    order = new_order(db)
    payment = start_attempt(db, order, provider)
    # Una violación REAL del `CHECK` de clasificación: el registro falla con un `IntegrityError` de la base.
    monkeypatch.setattr("app.revenue.ledger.classify_capture", lambda status: SimpleNamespace(value="BOGUS"))

    with pytest.raises(RevenueLedgerWriteError) as raised:
        deliver(db, provider, SUCCEEDED, payment)

    assert not isinstance(raised.value, IntegrityError), "a ledger failure must not look like the capture race"
    db.rollback()
    (event,) = events(db)
    payment = reload(db, payment)
    assert event.processing_status == "RECEIVED", "the event stays RECEIVED and re-enters the ADR 0029 cycle"
    assert (payment.status, Decimal(str(payment.captured_amount))) == ("OPEN", 0), "no capture without its entry"
    assert reload(db, order).status == "AWAITING_PAYMENT", "the order is not marked paid"
    assert entries(db) == []

    monkeypatch.undo()
    assert PaymentService(db).apply(event.id) == "APPLIED"
    assert len(entries(db)) == 1 and reload(db, order).status == "PAID"


def test_an_integrity_error_that_is_not_the_capture_race_does_not_mark_the_order_paid(
    db: Session, provider, monkeypatch
):
    order = new_order(db)
    payment = start_attempt(db, order, provider)

    def boom(self, *args, **kwargs):
        raise IntegrityError("INSERT", {}, Exception("an unrelated constraint"))

    monkeypatch.setattr(PaymentService, "_record_capture", boom)

    with pytest.raises(IntegrityError):
        deliver(db, provider, SUCCEEDED, payment)

    db.rollback()
    assert reload(db, order).status == "AWAITING_PAYMENT", "nothing was recorded, so the order cannot be PAID"
    assert events(db)[0].processing_status == "RECEIVED" and entries(db) == []


def test_a_refund_whose_entry_cannot_be_written_is_not_settled(db: Session, provider, monkeypatch):
    payment = capture(db, provider, new_order(db))
    refund = refund_of(db, provider, payment, "20.00")

    def boom(self, **kwargs):
        raise RevenueLedgerWriteError("simulated")

    monkeypatch.setattr(RevenueLedger, "record_refund", boom)
    with pytest.raises(RevenueLedgerWriteError):
        confirm_refund(db, provider, refund)

    db.rollback()
    payment = reload(db, payment)
    assert Decimal(str(payment.refunded_amount)) == 0, "the refunded amount moved only together with its entry"
    assert reload(db, refund).status == "SENDING" and [e.kind for e in entries(db)] == ["CAPTURE"]
    monkeypatch.undo()
    assert PaymentService(db).apply(events(db)[-1].id) == "APPLIED"
    assert [e.kind for e in entries(db)] == ["CAPTURE", "REFUND"]


# --- Datos anteriores al registro ----------------------------------------------------------------------------------


def test_a_refund_of_a_payment_captured_before_the_ledger_is_applied_and_audited_without_an_entry(
    db: Session, provider, monkeypatch
):
    with monkeypatch.context() as legacy:
        legacy.setattr(RevenueLedger, "record_capture", lambda self, **kwargs: None)
        payment = capture(db, provider, new_order(db))
    assert entries(db) == [] and Decimal(str(payment.captured_amount)) == 50

    refund = refund_of(db, provider, payment, "20.00")
    result = confirm_refund(db, provider, refund)

    assert result.outcome == "applied", "a money fact is never blocked by a gap in the ledger"
    assert Decimal(str(reload(db, payment).refunded_amount)) == 20
    assert entries(db) == []
    audit = db.scalars(select(AuditLog).where(AuditLog.action == "revenue.refund_outside_ledger")).one()
    assert audit.after["payment_id"] == payment.id and audit.after["refund_id"] == refund.id


# --- Inmutabilidad y forma ------------------------------------------------------------------------------------------


def test_an_entry_cannot_be_updated_or_deleted(db: Session, provider):
    capture(db, provider, new_order(db))
    (entry,) = entries(db)

    with pytest.raises(DBAPIError, match="append-only"):
        db.execute(update(RevenueLedgerEntry).where(RevenueLedgerEntry.id == entry.id).values(amount=Decimal("1")))
    db.rollback()
    with pytest.raises(DBAPIError, match="append-only"):
        db.execute(delete(RevenueLedgerEntry).where(RevenueLedgerEntry.id == entry.id))
    db.rollback()

    (still,) = entries(db)
    assert (still.id, still.amount, still.classification) == (entry.id, Decimal("50"), "ORDER_PAYMENT")


def test_a_truncate_is_rejected_on_postgresql(db: Session, provider):
    if db.get_bind().dialect.name != "postgresql":
        pytest.skip("TRUNCATE has a trigger only on PostgreSQL")
    capture(db, provider, new_order(db))

    with pytest.raises(DBAPIError, match="append-only"):
        db.execute(text("TRUNCATE revenue_ledger_entries"))
    db.rollback()
    assert len(entries(db)) == 1


def _clone(entry: RevenueLedgerEntry, **changes) -> RevenueLedgerEntry:
    values = {
        column: getattr(entry, column)
        for column in (
            "kind", "classification", "payment_event_id", "payment_id", "order_id", "refund_id",
            "capture_entry_id", "amount", "currency", "occurred_at", "recorded_at",
        )
    }  # fmt: skip
    values.update(changes)
    return RevenueLedgerEntry(**values)


def _rejects(db: Session, entry: RevenueLedgerEntry, constraint: str) -> None:
    """La base rechaza la fila **por esa restricción** (PostgreSQL da el nombre; SQLite, la columna)."""
    with pytest.raises(IntegrityError, match=constraint):
        db.add(entry)
        db.flush()
    db.rollback()


def _spare_event(db: Session, provider, payment: Payment) -> PaymentEvent:
    """Un evento verificado y guardado (`STALE`, sin entrada): un id de evento libre para forjar filas."""
    deliver(db, provider, SUCCEEDED, payment, event_id="evt_spare")
    return db.scalars(select(PaymentEvent).where(PaymentEvent.provider_event_id == "evt_spare")).one()


def test_the_database_itself_refuses_malformed_or_repeated_entries(db: Session, provider):
    payment = capture(db, provider, new_order(db))
    refund = refund_of(db, provider, payment, "20.00")
    confirm_refund(db, provider, refund)
    cap = capture_entry(db, payment)
    ref = [e for e in entries(db) if e.kind == "REFUND"][0]
    spare = _spare_event(db, provider, payment)
    other_refund = refund_of(db, provider, payment, "5.00")  # pedido, sin confirmar: sin entrada

    _rejects(db, _clone(cap, id="again"), "uq_revenue_entries_payment_event|uq_revenue_entries_one_capture|payment_")
    _rejects(db, _clone(cap, id="second-cap", payment_event_id=spare.id), "uq_revenue_entries_one_capture|payment_id")
    _rejects(db, _clone(ref, id="second-ref", payment_event_id=spare.id), "uq_revenue_entries_one_entry|refund_id")
    _rejects(db, _clone(ref, id="zero", payment_event_id=spare.id, refund_id=other_refund.id, amount=Decimal(0)),
             "ck_revenue_entries_amount_positive")  # fmt: skip
    _rejects(db, _clone(ref, id="bogus", payment_event_id=spare.id, refund_id=other_refund.id, classification="BOGUS"),
             "ck_revenue_entries_classification")  # fmt: skip
    _rejects(db, _clone(ref, id="cur", payment_event_id=spare.id, refund_id=other_refund.id, currency="EU"),
             "ck_revenue_entries_currency_shape")  # fmt: skip
    _rejects(db, _clone(cap, id="refund-on-capture", payment_event_id=spare.id, refund_id=other_refund.id),
             "ck_revenue_entries_refund_names")  # fmt: skip
    _rejects(db, _clone(ref, id="refund-no-capture", payment_event_id=spare.id, refund_id=other_refund.id,
                        capture_entry_id=None), "ck_revenue_entries_refund_names_capture")  # fmt: skip
    _rejects(db, _clone(ref, id="capture-with-link", payment_event_id=spare.id, refund_id=None),
             "ck_revenue_entries_refund_names_refund")  # fmt: skip
    assert len(entries(db)) == 2


def test_a_refund_cannot_claim_another_classification_than_its_capture_postgres(db: Session, provider):
    if db.get_bind().dialect.name != "postgresql":
        pytest.skip("SQLite test engines do not enforce foreign keys; the SQLite migration test covers this rule")
    canonical, duplicate = duplicate_pair(db, provider, new_order(db))
    first = refund_of(db, provider, duplicate, "20.00", reason="duplicate_capture")
    confirm_refund(db, provider, first)
    ref = [e for e in entries(db) if e.kind == "REFUND"][0]
    assert ref.classification == "DUPLICATE_RECEIPT"
    spare = _spare_event(db, provider, duplicate)
    second = refund_of(db, provider, duplicate, "10.00", reason="duplicate_capture")  # sin confirmar: sin entrada

    honest = _clone(ref, id="honest", payment_event_id=spare.id, refund_id=second.id)
    for forged in (
        _clone(honest, id="x1", classification="ORDER_PAYMENT"),  # otra clasificación
        _clone(honest, id="x2", currency="USD"),  # otra moneda
        _clone(honest, id="x3", payment_id=canonical.id),  # otro cobro
    ):
        _rejects(db, forged, "fk_revenue_entries_refund_inherits_capture")
    db.add(honest)  # la misma fila, honesta, sí entra: el rechazo anterior era por la herencia y por nada más
    db.flush()
    db.rollback()


# --- El vocabulario -------------------------------------------------------------------------------------------------


def test_the_classification_of_a_capture_is_dictated_by_the_state_of_the_payment():
    assert classify_capture("SUCCEEDED") is Classification.ORDER_PAYMENT
    assert classify_capture("DUPLICATE_CAPTURE") is Classification.DUPLICATE_RECEIPT
    assert classify_capture("CAPTURE_MISMATCH") is Classification.MISMATCH_RECEIPT
    for state in ("REQUESTED", "OPENING", "OPEN", "FAILED", "EXPIRED", "UNKNOWN_OUTCOME"):
        with pytest.raises(ValueError):
            classify_capture(state)


def test_every_payment_with_money_has_exactly_one_capture_entry_and_the_amounts_match(db: Session, provider):
    order = new_order(db)
    canonical, duplicate = duplicate_pair(db, provider, order)
    odd = mismatched_capture(db, provider, new_order(db, name="Gadget", customer="sim_other"), "12.50")

    for payment in payments_of(db, order) + [odd]:
        captured = Decimal(str(payment.captured_amount))
        rows = [e for e in entries(db) if e.payment_id == payment.id and e.kind == "CAPTURE"]
        assert len(rows) == (1 if captured > 0 else 0)
        assert sum((r.amount for r in rows), Decimal(0)) == captured
    assert {p.id for p in (canonical, duplicate)} <= {e.payment_id for e in entries(db)}
    assert db.scalars(select(PaymentEvent).where(PaymentEvent.processing_status == "RECEIVED")).all() == []
    assert db.scalars(select(Payment).where(Payment.status == "OPENING")).all() == []
