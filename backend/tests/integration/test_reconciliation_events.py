# ruff: noqa: F811 - los fixtures de pytest se importan del módulo de apoyo y los tests los piden por su nombre
"""Reanudar los eventos de pago guardados y no aplicados, con un tope de intentos que no inventa estados (Milestone
45, ADR 0029 §6).

Sobre SQLite y PostgreSQL. Lo que se afirma:

- un evento `RECEIVED` viejo se aplica **una vez** por la puerta de siempre (`PaymentService.apply`); uno reciente no
se toca;
- el intento se cuenta **antes** de aplicar: una caída a mitad también cuenta;
- un evento que falla **no bloquea** a los demás; a los 5 intentos deja de reintentarse solo y **sigue `RECEIVED`**
(sin estado nuevo, sin `FAILED`,
  sin liberar nada, sin perderse), visible y auditado una vez;
- una reentrega del proveedor no cuenta y sigue aplicando el evento;
- `retry_event` reintenta el **procesamiento**: no cobra, no llama al proveedor, no toca el hecho; sobre cualquier
estado que no sea `RECEIVED` no
  hace nada; deja auditado quién, cuándo, por qué y qué resultó;
- con varios reconciliadores, redelivery y reintento a la vez (PostgreSQL real), el dinero se mueve **una** vez.
"""

import datetime
from decimal import Decimal

import pytest
from order_test_support import add_product
from payment_test_support import (
    SIMULATION,
    ScriptedPaymentProvider,
    add_order,
    captured_total,
    events,
    fresh_order_status,
    ingress,
    reload,
    run_together,
    start_attempt,
)
from reconciliation_test_support import (  # noqa: F401 - fixtures de pytest
    db,
    engine,
    event_row,
    factory,
)
from sqlalchemy import select, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app import cli
from app.core.errors import NotFoundError, ValidationError
from app.db.models.audit import AuditLog
from app.db.models.external_action import ExternalAction
from app.db.models.payment import PaymentEvent
from app.money.money import Money
from app.payments.ingress import PaymentIngress
from app.payments.port import PaymentEventType
from app.payments.service import PaymentService
from app.reconciliation.events import EventReconciler, retry_event
from app.reconciliation.report import build_status

EVERYTHING = datetime.timedelta(seconds=-1)
FIVE_MINUTES = datetime.timedelta(minutes=5)
CAP = 5


class Crash(BaseException):
    """El proceso muere (no es una excepción que el código capture)."""


def reconciler(db: Session, *, older_than: datetime.timedelta = EVERYTHING, cap: int = CAP) -> EventReconciler:
    return EventReconciler(db, older_than=older_than, max_attempts=cap)


def stuck_capture(db: Session, monkeypatch, *, event_id: str = "evt-stuck", provider=None):
    """Un cobro `OPEN` y su captura verificada **guardada y sin aplicar** (el proceso cayó entre las dos
    transacciones de la puerta)."""
    provider = provider or ScriptedPaymentProvider()
    order = add_order(db, add_product(db, name=f"Product {event_id}"), customer=f"sim_{event_id}")
    payment = start_attempt(db, order, provider)
    headers, raw = provider.simulate_event(
        PaymentEventType.PAYMENT_SUCCEEDED,
        provider_payment_ref=payment.provider_payment_ref,
        client_reference=payment.id,
        amount=Money.of("50.00", "EUR"),
        event_id=event_id,
    )
    real_apply = PaymentService.apply

    def crash(self, event_id):
        raise Crash("died between the two transactions")

    monkeypatch.setattr(PaymentService, "apply", crash)
    with pytest.raises(Crash):
        ingress(db, provider).receive(provider.name, headers, raw)
    monkeypatch.setattr(PaymentService, "apply", real_apply)
    db.rollback()
    assert event_row(db, event_id).processing_status == "RECEIVED"
    return order, payment, provider, headers, raw


def audit_rows(db: Session, action: str) -> list[AuditLog]:
    db.expire_all()
    return list(
        db.scalars(select(AuditLog).where(AuditLog.action == action).order_by(AuditLog.created_at, AuditLog.id))
    )


def make_apply_fail(monkeypatch, exc: Exception, *, only: str | None = None):
    real = PaymentService.apply
    calls: list[str] = []

    def failing(self, event_id: str):
        calls.append(event_id)
        if only is None or event_id == only:
            raise exc
        return real(self, event_id)

    monkeypatch.setattr(PaymentService, "apply", failing)
    return calls


# --- Reanudar un evento
# ---------------------------------------------------------------------------------------------------


def test_an_old_stored_event_is_applied_once_through_the_usual_door_and_the_attempt_is_audited(
    db: Session, monkeypatch
):
    order, payment, _, _, _ = stuck_capture(db, monkeypatch)

    report = reconciler(db).sweep()

    assert report.outcomes == {"applied": 1} and report.failed == [] and report.skipped == 0
    assert reload(db, payment).status == "SUCCEEDED" and fresh_order_status(db, order) == "PAID"
    assert captured_total(db, order) == Decimal("50")
    event = event_row(db, "evt-stuck")
    assert event.processing_status == "APPLIED" and event.reconcile_attempts == 1
    (attempt,) = audit_rows(db, "payment_event.reconcile_attempt")
    assert attempt.actor == "reconciler" and attempt.after == {
        "attempt": 1,
        "max_attempts": CAP,
        "failed": False,
        "outcome": "applied",
    }


def test_a_recent_event_may_be_applying_right_now_and_is_not_touched(db: Session, monkeypatch):
    stuck_capture(db, monkeypatch)

    report = reconciler(db, older_than=datetime.timedelta(hours=1)).sweep()

    assert report.examined == 0 and event_row(db, "evt-stuck").processing_status == "RECEIVED"
    assert event_row(db, "evt-stuck").reconcile_attempts == 0


def test_nothing_is_applied_twice_by_sweeping_again(db: Session, monkeypatch):
    order, _, _, _, _ = stuck_capture(db, monkeypatch)
    reconciler(db).sweep()

    again = reconciler(db).sweep()

    assert again.examined == 0 and captured_total(db, order) == Decimal("50"), "the money moved once"
    assert len(audit_rows(db, "payment.captured")) == 1


def test_an_attempt_is_counted_before_applying_so_a_crash_halfway_counts_too(db: Session, monkeypatch):
    stuck_capture(db, monkeypatch)
    real = PaymentService.apply
    monkeypatch.setattr(PaymentService, "apply", lambda self, event_id: (_ for _ in ()).throw(Crash("died applying")))

    with pytest.raises(Crash):
        reconciler(db).sweep()
    db.rollback()
    monkeypatch.setattr(PaymentService, "apply", real)

    event = event_row(db, "evt-stuck")
    assert event.processing_status == "RECEIVED" and event.reconcile_attempts == 1, "the dying attempt was counted"
    assert reconciler(db).sweep().outcomes == {"applied": 1}, "and the next tick still resumes it"
    assert event_row(db, "evt-stuck").reconcile_attempts == 2


# --- El tope: nada se inventa
# -------------------------------------------------------------------------------------------


def test_after_five_failures_the_event_stops_being_retried_and_stays_received_visible_and_audited_once(
    db: Session, monkeypatch
):
    order, payment, _, _, _ = stuck_capture(db, monkeypatch)
    calls = make_apply_fail(monkeypatch, RuntimeError("could not settle the capture"))

    reports = [reconciler(db).sweep() for _ in range(CAP)]

    assert [len(r.failed) for r in reports] == [1] * CAP
    assert [r.capped_now for r in reports] == [[]] * (CAP - 1) + [[event_row(db, "evt-stuck").id]]
    event = event_row(db, "evt-stuck")
    assert event.reconcile_attempts == CAP and event.processing_status == "RECEIVED", (
        "the event stays RECEIVED: no new state"
    )
    assert (
        event.last_reconcile_error == "RuntimeError: could not settle the capture"
        and event.last_reconcile_at is not None
    )
    sixth = reconciler(db).sweep()
    assert sixth.examined == 0 and len(calls) == CAP, "past the cap the automatic retries stop"
    assert event_row(db, "evt-stuck").reconcile_attempts == CAP
    # nada se inventó: ni FAILED, ni reservas liberadas, ni pedido tocado, ni evento perdido
    assert fresh_order_status(db, order) == "AWAITING_PAYMENT" and reload(db, payment).status == "OPEN"
    assert len(events(db)) == 1
    assert len(audit_rows(db, "payment_event.reconcile_attempt")) == CAP
    (capped,) = audit_rows(db, "payment_event.reconcile_capped")
    assert capped.after["attempts"] == CAP and capped.after["max_attempts"] == CAP
    assert "stays RECEIVED" in capped.after["note"]


def test_a_poisoned_event_does_not_block_the_others_in_the_same_batch(db: Session, monkeypatch):
    _, _, _, _, _ = stuck_capture(db, monkeypatch, event_id="evt-poison")
    healthy_order, healthy_payment, _, _, _ = stuck_capture(db, monkeypatch, event_id="evt-healthy")
    poisoned_id = event_row(db, "evt-poison").id
    make_apply_fail(monkeypatch, RuntimeError("boom"), only=poisoned_id)

    report = reconciler(db).sweep()

    assert report.failed == [(poisoned_id, "RuntimeError")] and report.outcomes == {"applied": 1}
    assert event_row(db, "evt-poison").processing_status == "RECEIVED"
    assert event_row(db, "evt-healthy").processing_status == "APPLIED"
    assert reload(db, healthy_payment).status == "SUCCEEDED" and fresh_order_status(db, healthy_order) == "PAID"


def test_the_stored_error_is_the_type_only_for_errors_that_are_not_ours(db: Session, monkeypatch):
    stuck_capture(db, monkeypatch)
    make_apply_fail(
        monkeypatch,
        OperationalError("UPDATE payments SET captured_amount = 50.00 WHERE id = 'x'", {"id": "x"}, Exception("down")),
    )

    reconciler(db).sweep()

    assert event_row(db, "evt-stuck").last_reconcile_error == "OperationalError", "no statement, no parameters"


def test_a_redelivery_from_the_provider_is_not_counted_and_still_applies_a_capped_event(db: Session, monkeypatch):
    order, payment, provider, headers, raw = stuck_capture(db, monkeypatch)
    real = PaymentService.apply
    make_apply_fail(monkeypatch, RuntimeError("boom"))
    for _ in range(CAP):
        reconciler(db).sweep()
    monkeypatch.setattr(PaymentService, "apply", real)
    assert event_row(db, "evt-stuck").reconcile_attempts == CAP

    again = PaymentIngress(db, settings=SIMULATION, provider=provider).receive(provider.name, headers, raw)

    assert again.duplicate is True and again.outcome == "applied"
    assert fresh_order_status(db, order) == "PAID" and captured_total(db, order) == Decimal("50")
    assert event_row(db, "evt-stuck").reconcile_attempts == CAP, "the provider's redelivery is not an automatic attempt"


def test_a_capped_event_is_visible_in_the_status_with_its_attempts_age_and_last_error(db: Session, monkeypatch):
    stuck_capture(db, monkeypatch)
    make_apply_fail(monkeypatch, RuntimeError("could not settle the capture"))
    for _ in range(CAP):
        reconciler(db).sweep()
    from app.core.config import Settings

    status = build_status(db, Settings(_env_file=None))

    assert status["events"]["waiting"]["count"] == 0
    capped = status["events"]["capped"]
    assert capped["count"] == 1
    (item,) = capped["items"]
    assert item["attempts"] == CAP and item["last_error"] == "RuntimeError: could not settle the capture"
    assert item["age_seconds"] is not None and item["age_seconds"] >= 0 and item["provider"] == "simulated-payments"


def test_the_attempt_cap_must_be_positive(db: Session):
    with pytest.raises(ValidationError):
        EventReconciler(db, older_than=EVERYTHING, max_attempts=0)


# --- retry_event: la salida humana
# --------------------------------------------------------------------------------------------


def test_retrying_a_capped_event_resets_the_count_and_applies_it_once_without_charging_again(db: Session, monkeypatch):
    order, payment, provider, _, _ = stuck_capture(db, monkeypatch)
    real = PaymentService.apply
    make_apply_fail(monkeypatch, RuntimeError("boom"))
    for _ in range(CAP):
        reconciler(db).sweep()
    monkeypatch.setattr(PaymentService, "apply", real)
    calls_before, actions_before = len(provider.calls), len(db.scalars(select(ExternalAction)).all())

    result = retry_event(db, event_row(db, "evt-stuck").id, actor="cli:operator", reason="the provider is back")

    assert result.performed and result.outcome == "applied" and result.error is None
    assert result.attempts_before == CAP and result.status_before == "RECEIVED"
    event = event_row(db, "evt-stuck")
    assert event.processing_status == "APPLIED" and event.reconcile_attempts == 0 and event.last_reconcile_error is None
    assert captured_total(db, order) == Decimal("50") and fresh_order_status(db, order) == "PAID"
    assert len(provider.calls) == calls_before, "it never calls the payment provider"
    assert len(db.scalars(select(ExternalAction)).all()) == actions_before, "it never opens a new external operation"
    requested = audit_rows(db, "payment_event.reprocess_requested")[-1]
    assert requested.actor == "cli:operator" and requested.after["reason"] == "the provider is back"
    assert requested.before["reconcile_attempts"] == CAP and requested.after["performed"] is True
    (outcome,) = audit_rows(db, "payment_event.reprocess_result")
    assert outcome.after["outcome"] == "applied" and outcome.actor == "cli:operator"


def test_after_a_retry_the_scheduler_may_take_the_event_again(db: Session, monkeypatch):
    stuck_capture(db, monkeypatch)
    real = PaymentService.apply
    make_apply_fail(monkeypatch, RuntimeError("boom"))
    for _ in range(CAP):
        reconciler(db).sweep()
    event_id = event_row(db, "evt-stuck").id
    assert reconciler(db).sweep().examined == 0
    still_failing = retry_event(db, event_id, actor="cli:operator", reason="try again")
    assert still_failing.performed and still_failing.error == "RuntimeError: boom" and still_failing.outcome is None
    assert event_row(db, "evt-stuck").processing_status == "RECEIVED"
    monkeypatch.setattr(PaymentService, "apply", real)

    report = reconciler(db).sweep()

    assert report.outcomes == {"applied": 1}, "the reset put it back in the hands of the scheduler"


@pytest.mark.parametrize("state", ["APPLIED", "STALE", "CONFLICT", "REJECTED", "UNMATCHED"])
def test_retrying_an_event_that_is_not_received_does_nothing_and_moves_no_money(db: Session, monkeypatch, state: str):
    order, payment, _, _, _ = stuck_capture(db, monkeypatch)
    reconciler(db).sweep()  # el cobro queda aplicado
    db.execute(update(PaymentEvent).values(processing_status=state, note="as it was"))
    db.commit()
    captured_before = captured_total(db, order)
    snapshot = (event_row(db, "evt-stuck").payload_hash, event_row(db, "evt-stuck").provider_event_id)

    result = retry_event(db, event_row(db, "evt-stuck").id, actor="cli:operator", reason="check")

    assert result.performed is False and result.status_before == state
    assert captured_total(db, order) == captured_before, "no second economic effect"
    event = event_row(db, "evt-stuck")
    assert event.processing_status == state and event.note == "as it was"
    assert (event.payload_hash, event.provider_event_id) == snapshot, "the fact is never touched"
    requested = audit_rows(db, "payment_event.reprocess_requested")[-1]
    assert requested.after["performed"] is False and requested.actor == "cli:operator", (
        "the request is audited even when nothing was done"
    )
    assert audit_rows(db, "payment_event.reprocess_result") == []


def test_retrying_needs_a_reason_and_an_event_that_exists(db: Session, monkeypatch):
    stuck_capture(db, monkeypatch)

    with pytest.raises(ValidationError):
        retry_event(db, event_row(db, "evt-stuck").id, actor="cli:operator", reason="   ")
    with pytest.raises(NotFoundError):
        retry_event(db, "missing", actor="cli:operator", reason="why")
    assert event_row(db, "evt-stuck").processing_status == "RECEIVED"


# --- La consola -----------------------------------------------------------------------------------------------------


@pytest.fixture()
def console(db: Session, factory, monkeypatch):
    monkeypatch.setenv(cli.BOOTSTRAP_ENV, "1")
    monkeypatch.setattr(cli, "get_session_factory", lambda: factory)
    return cli.main


def test_the_console_retry_applies_a_stuck_event_and_says_so(db: Session, monkeypatch, console, capsys):
    order, _, _, _, _ = stuck_capture(db, monkeypatch)

    status = console(["retry-payment-event", "--id", event_row(db, "evt-stuck").id, "--reason", "owner checked"])

    assert status == 0 and "applied" in capsys.readouterr().out
    assert fresh_order_status(db, order) == "PAID"


def test_the_console_retry_on_an_applied_event_says_nothing_was_done(db: Session, monkeypatch, console, capsys):
    stuck_capture(db, monkeypatch)
    reconciler(db).sweep()

    status = console(["retry-payment-event", "--id", event_row(db, "evt-stuck").id, "--reason", "just looking"])

    assert status == 0 and "nothing was done" in capsys.readouterr().out


def test_the_console_retry_reports_a_failure_cleanly_and_the_event_stays_received(
    db: Session, monkeypatch, console, capsys
):
    stuck_capture(db, monkeypatch)
    make_apply_fail(monkeypatch, RuntimeError("still broken"))

    status = console(["retry-payment-event", "--id", event_row(db, "evt-stuck").id, "--reason", "try"])

    shown = capsys.readouterr()
    assert status == cli.EXIT_FAILED == 1 and "still broken" in shown.err and "stays RECEIVED" in shown.err
    assert "Traceback" not in shown.err
    assert event_row(db, "evt-stuck").processing_status == "RECEIVED"


def test_the_console_retry_needs_the_bootstrap_flag_and_a_reason(db: Session, monkeypatch, console, capsys):
    stuck_capture(db, monkeypatch)
    event_id = event_row(db, "evt-stuck").id
    assert console(["retry-payment-event", "--id", event_id, "--reason", "   "]) == cli.EXIT_REFUSED
    assert "reason" in capsys.readouterr().err
    monkeypatch.delenv(cli.BOOTSTRAP_ENV)

    assert console(["retry-payment-event", "--id", event_id, "--reason", "x"]) == cli.EXIT_REFUSED
    assert "AMAZONA_BOOTSTRAP=1" in capsys.readouterr().err


def test_the_console_reconciliation_counts_failures_and_stops_at_the_cap(db: Session, monkeypatch):
    stuck_capture(db, monkeypatch)
    db.execute(
        update(PaymentEvent).values(received_at=datetime.datetime.now(datetime.UTC) - datetime.timedelta(minutes=30))
    )
    db.commit()
    make_apply_fail(monkeypatch, RuntimeError("boom"))

    results = [cli.reconcile_payment_events(db, older_than_minutes=1) for _ in range(CAP + 1)]

    assert results == [{"failed": 1}] * CAP + [{}], "the console counts as the scheduler does and honours the same cap"
    assert (
        event_row(db, "evt-stuck").reconcile_attempts == CAP
        and event_row(db, "evt-stuck").processing_status == "RECEIVED"
    )


# --- El reclamo del intento es la frontera del tope -----------------------------------------------------------------


def test_the_claim_of_an_attempt_is_the_frontier_of_the_cap_even_for_a_reconciler_with_a_stale_list(
    db: Session, factory, monkeypatch
):
    """Dos reconciliadores listaron el mismo evento con un intento por gastar: solo uno lo reclama."""
    stuck_capture(db, monkeypatch)
    event_id = event_row(db, "evt-stuck").id
    db.execute(update(PaymentEvent).values(reconcile_attempts=CAP - 1))
    db.commit()
    with factory() as other:
        first = EventReconciler(db, older_than=EVERYTHING, max_attempts=CAP)
        second = EventReconciler(other, older_than=EVERYTHING, max_attempts=CAP)

        assert first._claim_attempt(event_id) == CAP, "the first one takes the last attempt"
        assert second._claim_attempt(event_id) is None, "the second one finds the cap reached and does not pass it"

    assert (
        event_row(db, "evt-stuck").reconcile_attempts == CAP
        and event_row(db, "evt-stuck").processing_status == "RECEIVED"
    )


def test_a_claim_on_an_event_that_is_no_longer_received_counts_nothing(db: Session, monkeypatch):
    stuck_capture(db, monkeypatch)
    event_id = event_row(db, "evt-stuck").id
    reconciler(db).sweep()  # lo aplica
    assert event_row(db, "evt-stuck").processing_status == "APPLIED"

    assert EventReconciler(db, older_than=EVERYTHING, max_attempts=CAP)._claim_attempt(event_id) is None
    assert event_row(db, "evt-stuck").reconcile_attempts == 1, "the attempt of a settled event is not recounted"


def test_retrying_a_settled_event_touches_neither_its_counters_nor_the_door(db: Session, monkeypatch):
    stuck_capture(db, monkeypatch)
    event_id = event_row(db, "evt-stuck").id
    reconciler(db).sweep()
    db.execute(update(PaymentEvent).values(reconcile_attempts=3, last_reconcile_error="RuntimeError: old", note="kept"))
    db.commit()

    def forbidden(self, event_id):
        raise AssertionError("retrying a settled event must not even call the door")

    monkeypatch.setattr(PaymentService, "apply", forbidden)

    result = retry_event(db, event_id, actor="cli:operator", reason="check")

    assert result.performed is False
    event = event_row(db, "evt-stuck")
    assert (event.reconcile_attempts, event.last_reconcile_error, event.note) == (3, "RuntimeError: old", "kept")


# --- Carreras: PostgreSQL real
# ----------------------------------------------------------------------------------------------------


def test_reconcilers_redelivery_and_a_retry_at_once_move_the_money_exactly_once(engine, factory, monkeypatch):
    if engine.dialect.name != "postgresql":
        pytest.skip("races only exist on a database with real transactions")
    with factory() as setup:
        order, payment, provider, headers, raw = stuck_capture(setup, monkeypatch, event_id="evt-race")
        event_id = event_row(setup, "evt-race").id
        order_id = order.id

    def reconcile(session: Session):
        return EventReconciler(session, older_than=EVERYTHING, max_attempts=CAP).sweep()

    def redeliver(session: Session):
        return PaymentIngress(session, settings=SIMULATION, provider=provider).receive(provider.name, headers, raw)

    def retry(session: Session):
        return retry_event(session, event_id, actor="cli:operator", reason="race")

    results = run_together(engine, [reconcile, reconcile, reconcile, redeliver, redeliver, retry])

    errors = [r for r in results if isinstance(r, Exception)]
    assert not errors, errors
    with factory() as check:
        event = event_row(check, "evt-race")
        assert event.processing_status == "APPLIED", "applied by whoever won the compare-and-set"
        assert event.reconcile_attempts <= CAP
        from app.db.models.payment import Payment

        paid = check.scalars(select(Payment).where(Payment.order_id == order_id)).one()
        assert Decimal(str(paid.captured_amount)) == Decimal("50"), "the money moved once, whoever got there first"
        assert len(audit_rows(check, "payment.captured")) == 1
        assert len(check.scalars(select(PaymentEvent)).all()) == 1, "nobody created a second event"


def test_many_reconcilers_claiming_the_last_attempt_at_once_let_exactly_one_through(engine, factory, monkeypatch):
    if engine.dialect.name != "postgresql":
        pytest.skip("races only exist on a database with real transactions")
    with factory() as setup:
        stuck_capture(setup, monkeypatch, event_id="evt-claim")
        event_id = event_row(setup, "evt-claim").id
        setup.execute(update(PaymentEvent).values(reconcile_attempts=CAP - 1))
        setup.commit()

    def claim(session: Session):
        return EventReconciler(session, older_than=EVERYTHING, max_attempts=CAP)._claim_attempt(event_id)

    results = run_together(engine, [claim] * 8)

    assert not [r for r in results if isinstance(r, Exception)], results
    assert sorted(r for r in results if r is not None) == [CAP], "exactly one claimed the last attempt"
    assert results.count(None) == 7
    with factory() as check:
        assert event_row(check, "evt-claim").reconcile_attempts == CAP, "nobody passed the cap"
