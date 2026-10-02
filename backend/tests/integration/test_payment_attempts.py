"""Abrir un intento de cobro de un pedido (Milestone 44, ADR 0028 §2, §3 y §7).

Un pedido puede tener varios intentos de cobro; los fallidos no obligan a recrearlo; un intento de resultado
desconocido bloquea los nuevos hasta reconciliarse o resolverse; y abrir un cobro es una acción externa **gobernada**
(permiso, kill switch, veto legal, política del proveedor, `ExternalAction`), aunque no gaste presupuesto.
"""

import datetime

import pytest
from order_test_support import add_product, make_engine, session_factory
from payment_test_support import (
    REQUESTER,
    SIMULATION,
    ScriptedPaymentProvider,
    add_order,
    deliver,
    payments_of,
    reload,
    start_attempt,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.actions.contract import ActionStatus, derive_idempotency_key
from app.actions.service import ExternalActionService
from app.core.config import Environment, Settings
from app.core.errors import ConflictError, ValidationError
from app.db.models.audit import AuditLog
from app.db.models.external_action import ExternalAction
from app.db.models.legal_analysis import LegalAnalysis
from app.db.models.order import Order
from app.db.models.payment import Payment
from app.integrations.operating_policy import OperationNotPermittedError
from app.integrations.ports import ProviderKind
from app.orders.errors import OperationNotAllowedError, OutcomeUnknownBlockError
from app.orders.payment_attempts import PaymentAttemptService, Requester
from app.orders.service import OrderService
from app.payments.domain import PaymentStatus
from app.payments.port import PaymentEventType
from app.payments.projection import payment_reference
from app.pipeline.kill_switch import PipelineKillSwitchService

REAL = Settings(_env_file=None, ads_provider=ProviderKind.REAL)


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
def order(db: Session) -> Order:
    return add_order(db, add_product(db))


def action_of(db: Session, payment: Payment) -> ExternalAction:
    return db.scalars(select(ExternalAction).where(ExternalAction.reference == payment_reference(payment.id))).one()


# --- El camino feliz -----------------------------------------------------------------------------------------------


def test_an_attempt_is_opened_at_the_provider_and_waits_for_the_customer(db: Session, order: Order):
    provider = ScriptedPaymentProvider()

    payment = start_attempt(db, order, provider)

    assert payment.status == PaymentStatus.OPEN.value and payment.attempt_number == 1
    assert payment.provider == provider.name and payment.provider_payment_ref.startswith("simpay_")
    assert payment.opened_at is not None and payment.captured_amount == 0
    assert reload(db, order).status == "AWAITING_PAYMENT", "opening a charge confirms nothing"
    action = action_of(db, payment)
    assert action.status == ActionStatus.SUCCEEDED.value and action.operation == "payment.open"
    assert action.idempotency_key == derive_idempotency_key(payment_reference(payment.id), 1)
    assert action.amount is None, "collecting is not budget spend"
    assert [r["payment_id"] for r in [provider.calls[0].payload]] == [payment.id]


def test_the_gate_decision_leaves_a_trail(db: Session, order: Order):
    start_attempt(db, order, ScriptedPaymentProvider())

    allowed = db.scalars(select(AuditLog).where(AuditLog.action == "action_gate.allow")).all()
    assert len(allowed) == 1 and allowed[0].after["side_effect_action"] == "collect_payment"
    changes = [
        a.after["status"] for a in db.scalars(select(AuditLog).where(AuditLog.action == "payment.status_changed"))
    ]
    assert changes == ["OPENING", "OPEN"]


# --- Varios intentos -----------------------------------------------------------------------------------------------


def test_a_second_attempt_cannot_start_while_the_first_is_alive(db: Session, order: Order):
    provider = ScriptedPaymentProvider()
    first = start_attempt(db, order, provider)

    with pytest.raises(ConflictError, match="still OPEN"):
        start_attempt(db, order, provider)

    assert len(payments_of(db, order)) == 1 and reload(db, first).status == "OPEN"


def test_failed_attempts_do_not_oblige_to_recreate_the_order(db: Session, order: Order):
    provider = ScriptedPaymentProvider()
    for expected_attempt in (1, 2, 3):
        attempt = start_attempt(db, order, provider)
        assert attempt.attempt_number == expected_attempt
        deliver(db, provider, PaymentEventType.PAYMENT_FAILED, attempt, failure_code="card_declined")

    fourth = start_attempt(db, order, provider)

    assert fourth.attempt_number == 4 and fourth.status == "OPEN"
    assert [p.status for p in payments_of(db, order)] == ["FAILED", "FAILED", "FAILED", "OPEN"]
    assert reload(db, order).status == "AWAITING_PAYMENT"
    keys = {a.idempotency_key for a in db.scalars(select(ExternalAction))}
    assert len(keys) == 4, "each attempt is its own operation with its own provider key"


def test_an_expired_attempt_frees_the_slot_too(db: Session, order: Order):
    provider = ScriptedPaymentProvider()
    first = start_attempt(db, order, provider)
    deliver(db, provider, PaymentEventType.PAYMENT_EXPIRED, first)

    assert start_attempt(db, order, provider).attempt_number == 2


def test_no_new_attempt_once_money_has_been_captured(db: Session, order: Order):
    provider = ScriptedPaymentProvider()
    first = start_attempt(db, order, provider)
    deliver(db, provider, PaymentEventType.PAYMENT_SUCCEEDED, first)

    with pytest.raises(ConflictError, match="PAID"):
        start_attempt(db, order, provider)


def test_no_new_attempt_for_an_order_that_already_holds_captured_money_even_if_it_is_not_paid(
    db: Session, order: Order
):
    """Una captura de un importe distinto deja el pedido sin pagar, pero hay dinero: una persona decide."""
    provider = ScriptedPaymentProvider()
    first = start_attempt(db, order, provider)
    deliver(db, provider, PaymentEventType.PAYMENT_SUCCEEDED, first, amount="10.00")
    assert reload(db, first).status == "CAPTURE_MISMATCH" and reload(db, order).status == "AWAITING_PAYMENT"

    with pytest.raises(ConflictError, match="money captured"):
        start_attempt(db, order, provider)


# --- Resultado desconocido -----------------------------------------------------------------------------------------


def test_a_timeout_after_the_provider_executed_leaves_an_unknown_outcome_that_blocks_new_attempts(
    db: Session, order: Order
):
    provider = ScriptedPaymentProvider("timeout_after")

    payment = start_attempt(db, order, provider)

    assert payment.status == PaymentStatus.UNKNOWN_OUTCOME.value, "a timeout is never a confirmed failure"
    assert action_of(db, payment).status == ActionStatus.UNKNOWN_OUTCOME.value
    with pytest.raises(OutcomeUnknownBlockError, match="unknown"):
        start_attempt(db, order, provider)
    assert len(provider.calls) == 1, "nothing was repeated blindly"


def test_the_late_response_closes_the_unknown_outcome_and_frees_nothing_by_guessing(db: Session, order: Order):
    provider = ScriptedPaymentProvider("timeout_after")
    payment = start_attempt(db, order, provider)
    action = action_of(db, payment)

    ExternalActionService(db).finish(action, ActionStatus.SUCCEEDED, response=provider.lookup(action.idempotency_key))

    payment = reload(db, payment)
    assert payment.status == "OPEN" and payment.provider_payment_ref is not None
    assert action_of(db, payment).status == ActionStatus.SUCCEEDED.value


def test_a_lookup_that_finds_the_charge_opens_the_attempt(db: Session, order: Order):
    provider = ScriptedPaymentProvider("timeout_after")
    payment = start_attempt(db, order, provider)

    status = ExternalActionService(db).reconcile(action_of(db, payment), provider, {})

    assert status is ActionStatus.SUCCEEDED
    assert reload(db, payment).status == "OPEN" and reload(db, payment).provider_payment_ref is not None


def test_a_person_who_checked_that_nothing_was_charged_frees_the_slot(db: Session, order: Order):
    provider = ScriptedPaymentProvider("timeout_before")
    payment = start_attempt(db, order, provider)
    assert payment.status == "UNKNOWN_OUTCOME"

    ExternalActionService(db).resolve(
        action_of(db, payment), succeeded=False, actor="owner@amazona.local", reason="checked the gateway dashboard"
    )

    assert reload(db, payment).status == "FAILED" and reload(db, payment).last_failure_code == "resolved_failed"
    assert start_attempt(db, order, provider).attempt_number == 2


def test_a_rejection_or_an_unreachable_provider_is_a_confirmed_failure(db: Session, order: Order):
    for behavior in ("reject", "unreachable"):
        payment = start_attempt(db, order, ScriptedPaymentProvider(behavior))
        assert payment.status == "FAILED" and payment.last_failure_code == "provider_rejected"


def test_a_process_that_dies_in_the_middle_of_the_call_leaves_the_attempt_possibly_sent(db: Session, order: Order):
    provider = ScriptedPaymentProvider("die")

    with pytest.raises(KeyboardInterrupt):
        start_attempt(db, order, provider)
    db.rollback()
    payment = payments_of(db, order)[0]

    assert payment.status == PaymentStatus.OPENING.value, "past the durability frontier: it may have left"
    assert ExternalActionService(db).mark_interrupted(payment_reference(payment.id)) is not None
    assert reload(db, payment).status == "UNKNOWN_OUTCOME"
    with pytest.raises(OutcomeUnknownBlockError):
        start_attempt(db, order, ScriptedPaymentProvider())


def test_a_process_that_dies_before_calling_leaves_nothing_sent_and_the_sweep_frees_the_slot(db: Session, order: Order):
    provider = ScriptedPaymentProvider()
    payment = PaymentAttemptService(db, settings=SIMULATION, provider=provider)
    original_execute = ExternalActionService.execute

    def die_before_the_frontier(self, action, adapter, payload):
        raise KeyboardInterrupt("died after opening the operation and before calling")

    ExternalActionService.execute = die_before_the_frontier  # type: ignore[method-assign]
    try:
        with pytest.raises(KeyboardInterrupt):
            payment.start(order.id, requester=REQUESTER)
    finally:
        ExternalActionService.execute = original_execute  # type: ignore[method-assign]
    db.rollback()
    stuck = payments_of(db, order)[0]
    assert stuck.status == "REQUESTED" and provider.calls == [], "REQUESTED guarantees that nothing was sent"

    swept = ExternalActionService(db).reconcile_interrupted(older_than=datetime.timedelta(seconds=-1))

    assert len(swept["released"]) == 1
    assert reload(db, stuck).status == "FAILED" and reload(db, stuck).last_failure_code == "not_sent"
    assert start_attempt(db, order, provider).attempt_number == 2


# --- Gobierno de la operación --------------------------------------------------------------------------------------


def test_a_kill_switch_that_is_off_stops_the_charge_before_anything_is_written(db: Session, order: Order):
    PipelineKillSwitchService(db).disable(reason="test", actor="owner@amazona.local", correlation_id="c-ks")
    provider = ScriptedPaymentProvider()

    with pytest.raises(OperationNotAllowedError, match="kill switch") as raised:
        start_attempt(db, order, provider)

    assert provider.calls == [] and payments_of(db, order) == []
    assert not raised.value.requires_approval
    assert db.scalars(select(AuditLog).where(AuditLog.action == "action_gate.deny")).one()


def test_a_kill_switch_turned_off_between_the_gate_and_the_call_sends_nothing(db: Session, order: Order):
    provider = ScriptedPaymentProvider()
    service = PaymentAttemptService(db, settings=SIMULATION, provider=provider)
    original = ExternalActionService.begin_call

    def switch_off_then_begin(self, action):
        PipelineKillSwitchService(db).disable(reason="test", actor="owner@amazona.local", correlation_id="c-ks")
        return original(self, action)

    ExternalActionService.begin_call = switch_off_then_begin  # type: ignore[method-assign]
    try:
        with pytest.raises(OperationNotAllowedError):
            service.start(order.id, requester=REQUESTER)
    finally:
        ExternalActionService.begin_call = original  # type: ignore[method-assign]

    payment = payments_of(db, order)[0]
    assert provider.calls == [], "the last check is before the irreversible effect"
    assert payment.status == "FAILED" and payment.last_failure_code == "not_sent"


def test_a_legal_no_go_of_the_product_denies_opening_the_charge(db: Session, order: Order):
    db.add(
        LegalAnalysis(
            product_id=order.items[0].product_id,
            market=order.market,
            recommendation="NO_GO",
            confidence=0.9,
            correlation_id="c",
        )
    )
    db.commit()
    provider = ScriptedPaymentProvider()

    with pytest.raises(OperationNotAllowedError, match="legal"):
        start_attempt(db, order, provider)

    assert provider.calls == [] and payments_of(db, order) == []


def test_a_legal_review_asks_for_approval_and_m44_has_no_inbox_so_it_does_not_run(db: Session, order: Order):
    db.add(
        LegalAnalysis(
            product_id=order.items[0].product_id,
            market=order.market,
            recommendation="REVIEW",
            confidence=0.5,
            correlation_id="c",
        )
    )
    db.commit()

    with pytest.raises(OperationNotAllowedError) as raised:
        start_attempt(db, order, ScriptedPaymentProvider())

    assert raised.value.requires_approval is True and any("REVIEW" in r for r in raised.value.reasons)


def test_outside_a_simulation_a_product_that_was_never_analysed_legally_is_not_sold_by_default(db: Session):
    product = add_product(db)
    order = OrderService(db, settings=REAL).create(
        customer_ref="customer-77",
        market="eu",
        lines=[__import__("order_test_support").line(product)],
        actor="t",
    )

    with pytest.raises(OperationNotAllowedError, match="no legal analysis"):
        PaymentAttemptService(db, settings=REAL, provider=ScriptedPaymentProvider()).start(
            order.id, requester=Requester(name="owner", role="OWNER")
        )


def test_the_absence_of_identity_outside_a_simulation_is_not_a_permission(db: Session):
    product = add_product(db)
    from order_test_support import line

    order = OrderService(db, settings=REAL).create(customer_ref="c-1", market="eu", lines=[line(product)], actor="t")
    db.add(LegalAnalysis(product_id=product.id, market="eu", recommendation="GO", confidence=1, correlation_id="c"))
    db.commit()

    with pytest.raises(OperationNotAllowedError, match="not allowed"):
        PaymentAttemptService(db, settings=REAL, provider=ScriptedPaymentProvider()).start(
            order.id, requester=Requester(name="anonymous", role=None)
        )


def test_an_identified_role_may_collect_without_the_approval_that_spending_needs(db: Session):
    product = add_product(db)
    from order_test_support import line

    order = OrderService(db, settings=REAL).create(customer_ref="c-1", market="eu", lines=[line(product)], actor="t")
    db.add(LegalAnalysis(product_id=product.id, market="eu", recommendation="GO", confidence=1, correlation_id="c"))
    db.commit()

    payment = PaymentAttemptService(db, settings=REAL, provider=ScriptedPaymentProvider()).start(
        order.id, requester=Requester(name="operator", role="OPERATOR")
    )

    assert payment.status == "OPEN"


def test_an_operation_the_provider_does_not_declare_is_denied_before_anything_is_written(db: Session, order: Order):
    class UndeclaredProvider(ScriptedPaymentProvider):
        name = "some-new-gateway"

    provider = UndeclaredProvider()

    with pytest.raises(OperationNotPermittedError, match="does not declare"):
        start_attempt(db, order, provider)

    assert payments_of(db, order) == []


def test_a_simulated_provider_is_not_accepted_in_production(db: Session, order: Order):
    production = Settings(_env_file=None, environment=Environment.PRODUCTION)

    with pytest.raises(OperationNotPermittedError, match="simulated"):
        start_attempt(db, order, ScriptedPaymentProvider(), settings=production)


# --- Reglas del dominio --------------------------------------------------------------------------------------------


def test_only_an_order_awaiting_payment_can_be_charged(db: Session, order: Order):
    OrderService(db, settings=SIMULATION).cancel(order.id, actor="t")

    with pytest.raises(ConflictError, match="CANCELLED"):
        start_attempt(db, order, ScriptedPaymentProvider())


def test_the_provider_must_charge_in_the_currency_of_the_order(db: Session):
    from order_test_support import create_order, line

    product = add_product(db)
    order = create_order(db, line(product, currency="CNY", unit_price="10.00"))

    with pytest.raises(ValidationError, match="does not charge in CNY"):
        start_attempt(db, order, ScriptedPaymentProvider())


def test_an_unknown_order_is_not_found(db: Session):
    from app.core.errors import NotFoundError

    with pytest.raises(NotFoundError):
        PaymentAttemptService(db, settings=SIMULATION, provider=ScriptedPaymentProvider()).start(
            "missing", requester=REQUESTER
        )


# --- Cancelar ------------------------------------------------------------------------------------------------------


def test_an_unpaid_order_with_no_live_attempt_can_be_cancelled(db: Session, order: Order):
    provider = ScriptedPaymentProvider()
    attempt = start_attempt(db, order, provider)
    with pytest.raises(ConflictError, match="still alive"):
        OrderService(db, settings=SIMULATION).cancel(order.id, actor="t")

    deliver(db, provider, PaymentEventType.PAYMENT_EXPIRED, attempt)
    cancelled = OrderService(db, settings=SIMULATION).cancel(order.id, actor="t")

    assert cancelled.status == "CANCELLED" and cancelled.cancelled_at is not None
    assert db.scalars(select(AuditLog).where(AuditLog.action == "order.cancelled")).one()
    with pytest.raises(ConflictError):
        OrderService(db, settings=SIMULATION).cancel(order.id, actor="t")  # repetir es un 409


def test_an_order_with_money_captured_cannot_be_cancelled_as_if_unpaid(db: Session, order: Order):
    provider = ScriptedPaymentProvider()
    attempt = start_attempt(db, order, provider)
    deliver(db, provider, PaymentEventType.PAYMENT_SUCCEEDED, attempt)

    with pytest.raises(ConflictError, match="PAID"):
        OrderService(db, settings=SIMULATION).cancel(order.id, actor="t")


# --- El cobro sigue a la acción en la misma transacción ---------------------------------------------------------------


def test_the_payment_observer_is_registered_for_the_namespace_of_opening_a_charge():
    from app.actions.observers import observers_for
    from app.payments.projection import PaymentOpenObserver

    found = observers_for(payment_reference("any"))

    assert len(found) == 1 and isinstance(found[0], PaymentOpenObserver)
    assert observers_for("pipeline_step:abc:marketing") == [], "the pipeline is untouched"


def test_if_the_payment_cannot_follow_the_action_the_request_never_leaves(db: Session, order: Order, monkeypatch):
    from app.payments.projection import PaymentOpenObserver

    def refuse(self, db, payment, action):
        raise RuntimeError("the payment cannot follow this action")

    monkeypatch.setattr(PaymentOpenObserver, "_begin", refuse)
    provider = ScriptedPaymentProvider()

    with pytest.raises(RuntimeError, match="cannot follow"):
        start_attempt(db, order, provider)
    db.rollback()

    assert provider.calls == [], "an action never starts without its domain"
    payment = payments_of(db, order)[0]
    assert payment.status == "REQUESTED" and action_of(db, payment).status == ActionStatus.PENDING.value
