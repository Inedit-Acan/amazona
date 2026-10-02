"""Un evento de pago verificado entra por una puerta y lo aplica un servicio (Milestone 44, ADR 0028 §1 y §4).

Lo que se prueba, con un proveedor simulado **con guion** y una base de datos en memoria:

- un pago solo se confirma por un evento verificado, y se confirma **una vez**;
- un evento duplicado no cambia nada; el mismo id con otro contenido es un conflicto y el original queda intacto;
- un evento que no se puede verificar no escribe nada;
- un evento fuera de orden no deshace un hecho, y **la evidencia financiera no se descarta nunca**: una captura
  tardía, duplicada o de otro importe se registra, el pedido no se «arregla» por su cuenta y queda marcado para que
  una persona lo mire.
"""

import datetime
import secrets
from decimal import Decimal

import pytest
from order_test_support import add_product, make_engine, session_factory
from payment_test_support import (
    SIMULATION,
    ScriptedPaymentProvider,
    add_order,
    captured_total,
    deliver,
    events,
    fresh_order_status,
    ingress,
    payments_of,
    reload,
    start_attempt,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.actions.contract import ActionStatus
from app.api.orders import order_out
from app.core.errors import ConflictError, NotFoundError
from app.db.models.audit import AuditLog
from app.db.models.external_action import ExternalAction
from app.db.models.order import Order
from app.db.models.payment import Payment, PaymentEvent
from app.money.money import Money
from app.orders.errors import OperationNotAllowedError
from app.orders.service import OrderService
from app.payments.domain import EventProcessing, PaymentStatus
from app.payments.port import (
    InvalidSignatureError,
    MissingSignatureError,
    PaymentEventType,
    StaleTimestampError,
    WebhookVerificationError,
)
from app.payments.providers.simulated import SimulatedPaymentProvider
from app.payments.service import PaymentService

SUCCEEDED = PaymentEventType.PAYMENT_SUCCEEDED
FAILED = PaymentEventType.PAYMENT_FAILED
EXPIRED = PaymentEventType.PAYMENT_EXPIRED
ATTEMPT_FAILED = PaymentEventType.PAYMENT_ATTEMPT_FAILED


@pytest.fixture()
def db():
    engine = make_engine()
    session = session_factory(engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def product(db: Session):
    return add_product(db)


@pytest.fixture()
def order(db: Session, product) -> Order:
    return add_order(db, product)  # 2 x 25.00 = 50.00


@pytest.fixture()
def provider() -> ScriptedPaymentProvider:
    return ScriptedPaymentProvider()


def audit_actions(db: Session) -> list[str]:
    return [a.action for a in db.scalars(select(AuditLog).order_by(AuditLog.created_at, AuditLog.id))]


# --- Un pago se confirma por un evento verificado, una vez ---------------------------------------------------------


def test_a_verified_capture_confirms_the_payment_and_pays_the_order(db: Session, order: Order, provider):
    payment = start_attempt(db, order, provider)

    result = deliver(db, provider, SUCCEEDED, payment)

    assert result.outcome == "applied" and result.duplicate is False
    payment = reload(db, payment)
    assert payment.status == PaymentStatus.SUCCEEDED.value
    assert Decimal(str(payment.captured_amount)) == Decimal("50")
    assert payment.succeeded_at is not None and payment.closed_at is not None
    paid = reload(db, order)
    assert paid.status == "PAID" and paid.paid_at is not None
    (event,) = events(db)
    assert event.processing_status == EventProcessing.APPLIED.value and event.payment_id == payment.id
    assert "payment.captured" in audit_actions(db)


def test_the_event_is_stored_without_the_raw_body_only_its_hash_and_whitelisted_fields(db: Session, order, provider):
    payment = start_attempt(db, order, provider)

    deliver(db, provider, SUCCEEDED, payment, event_id="evt_stored")

    (event,) = events(db)
    assert len(event.payload_hash) == 64 and event.provider == provider.name
    assert set(event.data) == {"failure_code"}
    assert Decimal(str(event.amount)) == Decimal("50") and event.currency == "EUR"
    assert not hasattr(event, "raw_body") and not hasattr(event, "headers")


def test_the_payment_is_confirmed_once_even_if_the_same_event_arrives_again(db: Session, order, provider):
    payment = start_attempt(db, order, provider)
    headers, raw = provider.simulate_event(
        SUCCEEDED,
        provider_payment_ref=payment.provider_payment_ref,
        client_reference=payment.id,
        amount=Money.of("50.00", "EUR"),
        event_id="evt_once",
    )

    first = ingress(db, provider).receive(provider.name, headers, raw)
    again = ingress(db, provider).receive(provider.name, headers, raw)

    assert (first.outcome, first.duplicate) == ("applied", False)
    assert (again.outcome, again.duplicate) == ("applied", True), "a repeated delivery changes nothing"
    assert len(events(db)) == 1
    assert captured_total(db, order) == Decimal("50")
    assert audit_actions(db).count("payment.captured") == 1


def test_applying_a_stored_event_twice_has_no_second_effect(db: Session, order, provider):
    payment = start_attempt(db, order, provider)
    deliver(db, provider, SUCCEEDED, payment)
    (event,) = events(db)

    assert PaymentService(db).apply(event.id) == EventProcessing.APPLIED.value
    assert captured_total(db, order) == Decimal("50")
    assert audit_actions(db).count("payment.captured") == 1


def test_a_second_event_id_for_the_same_capture_does_not_count_the_money_twice(db: Session, order, provider):
    """Algunas pasarelas mandan dos eventos distintos por una captura. Es la misma captura del mismo cobro."""
    payment = start_attempt(db, order, provider)
    deliver(db, provider, SUCCEEDED, payment, event_id="evt_a")

    second = deliver(db, provider, SUCCEEDED, payment, event_id="evt_b")

    assert second.outcome == "stale"
    assert captured_total(db, order) == Decimal("50") and len(payments_of(db, order)) == 1


def test_a_second_capture_event_with_another_amount_for_the_same_payment_is_a_conflict_not_more_money(
    db: Session, order, provider
):
    payment = start_attempt(db, order, provider)
    deliver(db, provider, SUCCEEDED, payment, event_id="evt_a")

    second = deliver(db, provider, SUCCEEDED, payment, event_id="evt_b", amount="60.00")

    assert second.outcome == "conflict"
    assert captured_total(db, order) == Decimal("50")
    assert "conflicting_payment_events" in order_out(db, reload(db, order)).attention_reasons


# --- Un evento que no se puede verificar no escribe nada -----------------------------------------------------------


def signed(provider, payment, **kwargs):
    return provider.simulate_event(
        SUCCEEDED,
        provider_payment_ref=payment.provider_payment_ref,
        client_reference=payment.id,
        amount=Money.of("50.00", "EUR"),
        **kwargs,
    )


def assert_nothing_changed(db: Session, order: Order, payment: Payment) -> None:
    assert events(db) == [], "an unverified event is never stored"
    assert reload(db, payment).status == PaymentStatus.OPEN.value
    assert fresh_order_status(db, order) == "AWAITING_PAYMENT"


def test_a_tampered_body_is_rejected_and_changes_nothing(db: Session, order, provider):
    payment = start_attempt(db, order, provider)
    headers, raw = signed(provider, payment)
    tampered = raw.replace(b'"50.0000"', b'"500.0000"') if b'"50.0000"' in raw else raw + b" "

    with pytest.raises(InvalidSignatureError):
        ingress(db, provider).receive(provider.name, headers, tampered)

    assert_nothing_changed(db, order, payment)
    assert "payment_webhook.rejected" in audit_actions(db)


def test_a_signature_from_another_key_is_rejected(db: Session, order, provider):
    payment = start_attempt(db, order, provider)
    stranger = SimulatedPaymentProvider(signing_key=secrets.token_bytes(32), operations={})
    headers, raw = signed(stranger, payment)

    with pytest.raises(InvalidSignatureError):
        ingress(db, provider).receive(provider.name, headers, raw)

    assert_nothing_changed(db, order, payment)


def test_a_missing_signature_is_rejected(db: Session, order, provider):
    payment = start_attempt(db, order, provider)
    _, raw = signed(provider, payment)

    with pytest.raises(MissingSignatureError):
        ingress(db, provider).receive(provider.name, {}, raw)

    assert_nothing_changed(db, order, payment)


def test_an_old_signed_event_is_a_replay_and_is_rejected(db: Session, order, provider):
    payment = start_attempt(db, order, provider)
    old = datetime.datetime.now(datetime.UTC) - datetime.timedelta(
        seconds=provider.capabilities.signature_tolerance_seconds + 60
    )
    headers, raw = signed(provider, payment, timestamp=old)

    with pytest.raises(StaleTimestampError):
        ingress(db, provider).receive(provider.name, headers, raw)

    assert_nothing_changed(db, order, payment)


def test_the_rejection_audit_never_contains_the_body_or_the_reason_the_caller_sees(db: Session, order, provider):
    payment = start_attempt(db, order, provider)
    headers, raw = signed(provider, payment)
    with pytest.raises(WebhookVerificationError):
        ingress(db, provider).receive(provider.name, headers, raw + b" ")

    (rejected,) = db.scalars(select(AuditLog).where(AuditLog.action == "payment_webhook.rejected")).all()

    assert rejected.after == {"reason": "invalid_signature"}
    assert raw.decode() not in str(rejected.after)


def test_an_oversized_body_is_rejected_before_it_is_verified(db: Session, order, provider):
    start_attempt(db, order, provider)

    with pytest.raises(WebhookVerificationError):
        ingress(db, provider).receive(provider.name, {"x": "y"}, b"x" * (64 * 1024 + 1))

    assert events(db) == []


def test_a_provider_that_is_not_enabled_here_is_not_found(db: Session, order, provider):
    payment = start_attempt(db, order, provider)
    headers, raw = signed(provider, payment)

    with pytest.raises(NotFoundError):
        ingress(db, provider).receive("another-gateway", headers, raw)


# --- El mismo id con otro contenido --------------------------------------------------------------------------------


def test_the_same_event_id_with_a_different_payload_is_a_conflict_and_the_original_stays(db: Session, order, provider):
    payment = start_attempt(db, order, provider)
    deliver(db, provider, SUCCEEDED, payment, event_id="evt_same")
    (original,) = events(db)

    with pytest.raises(ConflictError, match="different content"):
        deliver(db, provider, SUCCEEDED, payment, event_id="evt_same", amount="49.00")

    (kept,) = events(db)
    assert kept.id == original.id and kept.payload_hash == original.payload_hash
    assert Decimal(str(kept.amount)) == Decimal("50")
    assert captured_total(db, order) == Decimal("50")
    assert "payment_event.payload_mismatch" in audit_actions(db)


# --- Fuera de orden ------------------------------------------------------------------------------------------------


def test_a_failure_after_a_capture_does_not_undo_it(db: Session, order, provider):
    payment = start_attempt(db, order, provider)
    deliver(db, provider, SUCCEEDED, payment)

    late = deliver(db, provider, FAILED, payment)

    assert late.outcome == "conflict"
    assert reload(db, payment).status == "SUCCEEDED" and fresh_order_status(db, order) == "PAID"
    assert "payment.closing_event_after_capture" in audit_actions(db)


def test_a_closing_event_after_the_payment_was_already_closed_changes_nothing(db: Session, order, provider):
    payment = start_attempt(db, order, provider)
    deliver(db, provider, FAILED, payment, failure_code="card_declined")

    assert deliver(db, provider, EXPIRED, payment).outcome == "stale"
    assert deliver(db, provider, FAILED, payment).outcome == "stale"

    payment = reload(db, payment)
    assert payment.status == "FAILED" and payment.last_failure_code == "card_declined"


def test_an_informational_failed_attempt_leaves_the_payment_open(db: Session, order, provider):
    payment = start_attempt(db, order, provider)

    result = deliver(db, provider, ATTEMPT_FAILED, payment, failure_code="insufficient_funds")

    assert result.outcome == "applied"
    payment = reload(db, payment)
    assert payment.status == "OPEN" and payment.last_failure_code == "insufficient_funds"
    deliver(db, provider, SUCCEEDED, payment)
    assert fresh_order_status(db, order) == "PAID", "the same open payment can still be captured"


def test_nothing_can_be_captured_from_an_attempt_that_never_left(db: Session, order, provider):
    payment = Payment(
        order_id=order.id,
        attempt_number=1,
        provider=provider.name,
        status="REQUESTED",
        amount=Decimal("50"),
        currency="EUR",
        correlation_id="c",
    )
    db.add(payment)
    db.commit()

    result = deliver(db, provider, SUCCEEDED, payment, use_payment_ref=False)

    assert result.outcome == "conflict"
    assert reload(db, payment).status == "REQUESTED" and captured_total(db, order) == 0
    assert events(db)[0].amount is not None, "the evidence is kept even if it could not be applied"


def test_the_last_event_is_the_most_recent_fact_not_the_last_to_arrive(db: Session, order, provider):
    payment = start_attempt(db, order, provider)
    recent = datetime.datetime(2026, 10, 2, 12, 0, tzinfo=datetime.UTC)

    deliver(db, provider, ATTEMPT_FAILED, payment, occurred_at=recent)
    deliver(db, provider, ATTEMPT_FAILED, payment, occurred_at=recent - datetime.timedelta(hours=1))

    last = reload(db, payment).last_event_at
    assert last.replace(tzinfo=datetime.UTC) == recent


# --- La evidencia financiera nunca se descarta ---------------------------------------------------------------------


def test_a_late_capture_after_a_failure_is_recorded_and_pays_the_order(db: Session, order, provider):
    payment = start_attempt(db, order, provider)
    deliver(db, provider, FAILED, payment)

    result = deliver(db, provider, SUCCEEDED, payment)

    assert result.outcome == "applied"
    assert reload(db, payment).status == "SUCCEEDED" and fresh_order_status(db, order) == "PAID"
    assert captured_total(db, order) == Decimal("50"), (
        "money that existed is never lost because the attempt looked dead"
    )


def test_a_late_capture_of_an_expired_attempt_after_another_attempt_succeeded_is_a_duplicate_capture(
    db: Session, order, provider
):
    """Pago A confirmado; el pago B estaba EXPIRED; llega la captura tardía auténtica de B."""
    b = start_attempt(db, order, provider)  # intento 1
    deliver(db, provider, EXPIRED, b)
    a = start_attempt(db, order, provider)  # intento 2
    deliver(db, provider, SUCCEEDED, a)
    assert reload(db, a).status == "SUCCEEDED" and fresh_order_status(db, order) == "PAID"
    paid_at = reload(db, order).paid_at

    late = deliver(db, provider, SUCCEEDED, b, event_id="evt_late_b")

    assert late.outcome == "applied"
    b, a = reload(db, b), reload(db, a)
    assert b.status == "DUPLICATE_CAPTURE" and b.duplicate_of_payment_id == a.id
    assert a.status == "SUCCEEDED"
    assert captured_total(db, order) == Decimal("100"), "both real captures stay in the books"
    assert Decimal(str(b.captured_amount)) == Decimal("50")
    assert reload(db, order).status == "PAID" and reload(db, order).paid_at == paid_at, "the order does not change"
    view = order_out(db, reload(db, order))
    assert view.attention_required and "duplicate_capture" in view.attention_reasons
    assert "payment.duplicate_capture" in audit_actions(db)
    late_event = db.scalars(select(PaymentEvent).where(PaymentEvent.provider_event_id == "evt_late_b")).one()
    assert late_event.processing_status == "APPLIED" and late_event.payment_id == b.id


def test_a_late_capture_of_a_failed_attempt_while_a_newer_one_is_open_pays_the_order_and_flags_the_open_one(
    db: Session, order, provider
):
    first = start_attempt(db, order, provider)
    deliver(db, provider, FAILED, first)
    second = start_attempt(db, order, provider)

    deliver(db, provider, SUCCEEDED, first, event_id="evt_late_first")

    assert reload(db, first).status == "SUCCEEDED" and fresh_order_status(db, order) == "PAID"
    assert "open_attempt_on_settled_order" in order_out(db, reload(db, order)).attention_reasons
    deliver(db, provider, SUCCEEDED, second, event_id="evt_second")
    assert reload(db, second).status == "DUPLICATE_CAPTURE" and captured_total(db, order) == Decimal("100")


def test_a_late_capture_on_a_cancelled_order_is_recorded_and_does_not_reopen_the_order(db: Session, order, provider):
    payment = start_attempt(db, order, provider)
    deliver(db, provider, EXPIRED, payment)
    OrderService(db, settings=SIMULATION).cancel(order.id, actor="t")
    assert fresh_order_status(db, order) == "CANCELLED"

    result = deliver(db, provider, SUCCEEDED, payment, event_id="evt_late")

    assert result.outcome == "applied"
    payment = reload(db, payment)
    assert payment.status == "SUCCEEDED" and Decimal(str(payment.captured_amount)) == Decimal("50")
    cancelled = reload(db, order)
    assert cancelled.status == "CANCELLED" and cancelled.paid_at is None, "the system does not fix the order by itself"
    view = order_out(db, cancelled)
    assert view.attention_required and "captured_on_cancelled_order" in view.attention_reasons
    assert "payment.late_capture_on_cancelled_order" in audit_actions(db)
    with pytest.raises(ConflictError):  # no se cobra de nuevo un pedido cancelado
        start_attempt(db, order, provider)


def test_a_capture_of_a_different_amount_is_recorded_as_it_was_and_the_order_stays_unpaid(db: Session, order, provider):
    payment = start_attempt(db, order, provider)

    result = deliver(db, provider, SUCCEEDED, payment, amount="30.00")

    assert result.outcome == "applied"
    payment = reload(db, payment)
    assert payment.status == "CAPTURE_MISMATCH" and Decimal(str(payment.captured_amount)) == Decimal("30")
    assert fresh_order_status(db, order) == "AWAITING_PAYMENT"
    view = order_out(db, reload(db, order))
    assert "capture_mismatch" in view.attention_reasons
    assert "payment.capture_mismatch" in audit_actions(db)


def test_a_capture_of_more_than_expected_is_recorded_too_the_money_existed(db: Session, order, provider):
    payment = start_attempt(db, order, provider)

    deliver(db, provider, SUCCEEDED, payment, amount="80.00")

    assert Decimal(str(reload(db, payment).captured_amount)) == Decimal("80")
    assert reload(db, payment).status == "CAPTURE_MISMATCH"


def test_a_capture_that_is_not_in_the_currency_of_the_payment_is_kept_as_evidence_and_not_applied(
    db: Session, order, provider
):
    payment = start_attempt(db, order, provider)

    result = deliver(db, provider, SUCCEEDED, payment, currency="USD")

    assert result.outcome == "conflict"
    assert reload(db, payment).status == "OPEN" and captured_total(db, order) == 0
    (event,) = events(db)
    assert event.currency == "USD" and event.processing_status == "CONFLICT"


def test_a_capture_without_an_amount_is_kept_as_evidence_and_not_invented(db: Session, order, provider):
    payment = start_attempt(db, order, provider)
    headers, raw = provider.simulate_event(
        SUCCEEDED, provider_payment_ref=payment.provider_payment_ref, client_reference=payment.id
    )

    result = ingress(db, provider).receive(provider.name, headers, raw)

    assert result.outcome == "conflict" and reload(db, payment).status == "OPEN"
    assert events(db)[0].processing_status == "CONFLICT"


def test_a_capture_arriving_while_the_open_outcome_is_unknown_is_recorded_without_closing_the_action(
    db: Session, order
):
    provider = ScriptedPaymentProvider("timeout_after")
    payment = start_attempt(db, order, provider)
    assert payment.status == "UNKNOWN_OUTCOME" and payment.provider_payment_ref is None
    headers, raw = provider.simulate_event(
        SUCCEEDED,
        provider_payment_ref="simpay_discovered",
        client_reference=payment.id,
        amount=Money.of("50.00", "EUR"),
    )

    result = ingress(db, provider).receive(provider.name, headers, raw)

    assert result.outcome == "applied"
    payment = reload(db, payment)
    assert payment.status == "SUCCEEDED" and payment.provider_payment_ref == "simpay_discovered"
    assert fresh_order_status(db, order) == "PAID"
    action = db.scalars(select(ExternalAction)).one()
    assert action.status == ActionStatus.UNKNOWN_OUTCOME.value, "a webhook is a fact, not a way to close a guess"


def test_an_event_that_matches_none_of_our_payments_is_kept_unmatched(db: Session, order, provider):
    start_attempt(db, order, provider)
    headers, raw = provider.simulate_event(
        SUCCEEDED,
        provider_payment_ref="simpay_stranger",
        client_reference="no-such-payment",
        amount=Money.of("5.00", "EUR"),
    )

    result = ingress(db, provider).receive(provider.name, headers, raw)

    assert result.outcome == "unmatched"
    (event,) = events(db)
    assert event.payment_id is None and event.processing_status == "UNMATCHED"


# --- Dos transacciones: el evento guardado no se pierde ------------------------------------------------------------


class SimulatedCrash(BaseException):
    """El proceso muere (no es una excepción que el código capture)."""


def test_a_process_that_dies_after_storing_the_event_leaves_it_received_and_the_redelivery_resumes_it(
    db: Session, order, provider, monkeypatch
):
    payment = start_attempt(db, order, provider)
    headers, raw = signed(provider, payment, event_id="evt_crash")
    real_apply = PaymentService.apply

    def crash(self, event_id):
        raise SimulatedCrash("died between the two transactions")

    monkeypatch.setattr(PaymentService, "apply", crash)
    with pytest.raises(SimulatedCrash):
        ingress(db, provider).receive(provider.name, headers, raw)
    monkeypatch.setattr(PaymentService, "apply", real_apply)
    db.rollback()

    (stored,) = events(db)
    assert stored.processing_status == "RECEIVED", "the verified event survived the crash"
    assert reload(db, payment).status == "OPEN" and fresh_order_status(db, order) == "AWAITING_PAYMENT"

    again = ingress(db, provider).receive(provider.name, headers, raw)

    assert again.outcome == "applied" and again.duplicate is True
    assert reload(db, payment).status == "SUCCEEDED" and fresh_order_status(db, order) == "PAID"
    assert len(events(db)) == 1 and captured_total(db, order) == Decimal("50")


def test_a_failure_halfway_through_applying_leaves_nothing_half_applied(db: Session, order, provider, monkeypatch):
    payment = start_attempt(db, order, provider)
    headers, raw = signed(provider, payment, event_id="evt_half")

    def explode(self, event, payment, order):
        raise SimulatedCrash("died after the payment was marked captured and before the order was updated")

    monkeypatch.setattr(PaymentService, "_mark_order_paid", explode)
    with pytest.raises(SimulatedCrash):
        ingress(db, provider).receive(provider.name, headers, raw)
    monkeypatch.undo()
    db.rollback()

    assert reload(db, payment).status == "OPEN" and captured_total(db, order) == 0, "the capture was rolled back too"
    assert fresh_order_status(db, order) == "AWAITING_PAYMENT"
    (stored,) = events(db)
    assert stored.processing_status == "RECEIVED"

    ingress(db, provider).receive(provider.name, headers, raw)

    assert reload(db, payment).status == "SUCCEEDED" and fresh_order_status(db, order) == "PAID"
    assert captured_total(db, order) == Decimal("50")


# --- Lectura -------------------------------------------------------------------------------------------------------


def test_the_order_view_lists_the_attempts_and_has_nothing_to_flag_when_all_is_well(db: Session, order, provider):
    first = start_attempt(db, order, provider)
    deliver(db, provider, FAILED, first)
    second = start_attempt(db, order, provider)
    deliver(db, provider, SUCCEEDED, second)

    view = order_out(db, reload(db, order))

    assert [(p.attempt_number, p.status) for p in view.payments] == [(1, "FAILED"), (2, "SUCCEEDED")]
    assert view.status == "PAID" and view.attention_required is False and view.attention_reasons == []
    assert view.payments[1].captured_amount.amount == "50.0000"


def test_a_view_of_an_order_with_no_payment_attempt_is_empty_not_invented(db: Session, order):
    view = order_out(db, order)

    assert view.payments == [] and view.refunds == [] and not view.attention_required


def test_the_operator_cannot_open_a_charge_the_gate_denies_and_no_event_is_needed(db: Session, order, provider):
    from app.pipeline.kill_switch import PipelineKillSwitchService

    PipelineKillSwitchService(db).disable(reason="test", actor="owner@amazona.local", correlation_id="c")

    with pytest.raises(OperationNotAllowedError):
        start_attempt(db, order, provider)
