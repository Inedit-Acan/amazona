"""Devolver dinero cobrado (Milestone 44, ADR 0028 §3, §5 y §7).

Un reembolso es una acción externa que ordena una persona; el límite (`Σ reembolsos ≤ cobrado`) lo pone la base de
datos; un resultado desconocido **mantiene** lo apartado y solo un fallo confirmado lo libera; y que el proveedor acepte
la petición no es que el dinero haya vuelto: lo confirma un hecho verificado.
"""

import datetime
from decimal import Decimal

import pytest
from order_test_support import add_product, add_quote, add_supplier, make_engine, session_factory
from payment_test_support import (
    REQUESTER,
    SIMULATION,
    ScriptedPaymentProvider,
    add_order,
    deliver,
    ingress,
    refunds,
    reload,
    start_attempt,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.actions.contract import ActionStatus
from app.actions.service import ExternalActionService
from app.core.config import Settings
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.db.models.audit import AuditLog
from app.db.models.external_action import ExternalAction
from app.db.models.order import Order
from app.db.models.payment import Payment, Refund
from app.db.models.product import Product
from app.integrations.ports import ProviderKind
from app.money.money import Money
from app.orders.attention import REFUND_OUTCOME_UNKNOWN, REFUND_UNCONFIRMED, attention_reasons
from app.orders.errors import OperationNotAllowedError, OutcomeUnknownBlockError
from app.orders.payment_attempts import Requester
from app.orders.refunds import RefundService
from app.payments.port import PaymentEventType
from app.payments.refund_projection import refund_reference
from app.pipeline.kill_switch import PipelineKillSwitchService

REAL = Settings(_env_file=None, ads_provider=ProviderKind.REAL)
OWNER = Requester(name="owner@amazona.local", role="OWNER")


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
    return add_order(db, add_product(db))  # 2 × 25.00 = 50.00


def captured(db: Session, order: Order, provider: ScriptedPaymentProvider) -> Payment:
    """Un cobro con los 50.00 capturados por un evento verificado."""
    payment = start_attempt(db, order, provider)
    deliver(db, provider, PaymentEventType.PAYMENT_SUCCEEDED, payment)
    payment = reload(db, payment)
    assert payment.status == "SUCCEEDED"
    return payment


def refund_of(
    db: Session, payment: Payment, provider, amount: str = "10.00", *, reason: str = "customer_request", **kwargs
) -> Refund:
    kwargs.setdefault("requester", REQUESTER)
    return RefundService(db, settings=SIMULATION, provider=provider).request(
        payment.id, amount=Money.of(amount, payment.currency), reason=reason, **kwargs
    )


def signed_refund_event(
    db: Session,
    provider,
    refund: Refund,
    kind: PaymentEventType,
    *,
    amount: str | None = None,
    by_ref: bool = True,
    event_id: str | None = None,
):
    """Lo que enviaría el proveedor: nuestro `refund_id` como referencia de cliente y, si la conoce, la suya."""
    payment = db.get(Payment, refund.payment_id)
    return provider.simulate_event(
        kind,
        provider_payment_ref=payment.provider_payment_ref,
        provider_refund_ref=refund.provider_refund_ref if by_ref else None,
        client_reference=refund.id,
        amount=Money.of(amount or str(refund.amount), refund.currency),
        event_id=event_id,
    )


def refund_event(db: Session, provider, refund: Refund, kind: PaymentEventType, **kwargs):
    headers, raw = signed_refund_event(db, provider, refund, kind, **kwargs)
    return ingress(db, provider).receive(provider.name, headers, raw)


def action_of(db: Session, refund: Refund) -> ExternalAction:
    return db.scalars(select(ExternalAction).where(ExternalAction.reference == refund_reference(refund.id))).one()


def amounts(db: Session, payment: Payment) -> tuple[Decimal, Decimal, Decimal]:
    fresh = reload(db, payment)
    return (
        Decimal(str(fresh.captured_amount)),
        Decimal(str(fresh.refund_committed_amount)),
        Decimal(str(fresh.refunded_amount)),
    )


# --- El camino feliz: aceptado no es devuelto ---------------------------------------------------------------------


def test_a_refund_is_accepted_by_the_provider_and_waits_for_its_verified_confirmation(db: Session, order: Order):
    provider = ScriptedPaymentProvider()
    payment = captured(db, order, provider)

    refund = refund_of(db, payment, provider, "10.00")

    assert refund.status == "SENDING" and refund.origin == "OPERATOR" and refund.reason == "customer_request"
    assert refund.provider_refund_ref.startswith("simref_") and refund.requested_by == REQUESTER.name
    assert amounts(db, payment) == (Decimal(50), Decimal(10), Decimal(0)), "reserved, not yet refunded"
    action = action_of(db, refund)
    assert action.status == ActionStatus.SUCCEEDED.value and action.operation == "payment.refund"
    (_, call) = provider.calls[0], provider.calls[-1]
    assert call.payload["amount"] == "10.00" and call.payload["provider_payment_ref"] == payment.provider_payment_ref
    assert reload(db, order).status == "PAID", "a refund does not touch the order"


def test_the_verified_confirmation_settles_the_refund_once(db: Session, order: Order):
    provider = ScriptedPaymentProvider()
    payment = captured(db, order, provider)
    refund = refund_of(db, payment, provider, "10.00")

    headers, raw = signed_refund_event(db, provider, refund, PaymentEventType.REFUND_SUCCEEDED, event_id="evt_refund_1")
    first = ingress(db, provider).receive(provider.name, headers, raw)
    again = ingress(db, provider).receive(provider.name, headers, raw)

    assert first.outcome == "applied" and again.duplicate
    refund = reload(db, refund)
    assert refund.status == "SUCCEEDED" and refund.finished_at is not None
    assert amounts(db, payment) == (Decimal(50), Decimal(10), Decimal(10))


def test_a_second_event_for_the_same_refund_does_not_count_the_money_twice(db: Session, order: Order):
    provider = ScriptedPaymentProvider()
    payment = captured(db, order, provider)
    refund = refund_of(db, payment, provider, "10.00")
    refund_event(db, provider, refund, PaymentEventType.REFUND_SUCCEEDED)

    other = refund_event(db, provider, refund, PaymentEventType.REFUND_SUCCEEDED)

    assert other.outcome == "stale"
    assert amounts(db, payment) == (Decimal(50), Decimal(10), Decimal(10))


def test_partial_refunds_add_up_to_what_was_captured_and_not_a_cent_more(db: Session, order: Order):
    provider = ScriptedPaymentProvider()
    payment = captured(db, order, provider)

    refund_of(db, payment, provider, "30.00")
    refund_of(db, payment, provider, "20.00")

    assert amounts(db, payment) == (Decimal(50), Decimal(50), Decimal(0))
    calls_before = len(provider.calls)
    with pytest.raises(ConflictError, match="left to refund"):
        refund_of(db, payment, provider, "0.01")
    assert len(provider.calls) == calls_before, "nothing was sent for a refund that does not fit"
    assert len(refunds(db)) == 2 and amounts(db, payment) == (Decimal(50), Decimal(50), Decimal(0))


def test_the_confirmation_arrives_even_if_the_provider_reference_was_never_stored(db: Session, order: Order):
    """La respuesta se perdió tras ejecutar: el evento trae nuestro `refund_id` y la referencia del proveedor."""
    provider = ScriptedPaymentProvider("ok", "timeout_after")
    payment = captured(db, order, provider)
    refund = refund_of(db, payment, provider, "10.00")
    assert refund.status == "UNKNOWN_OUTCOME" and refund.provider_refund_ref is None

    result = refund_event(
        db, provider, refund, PaymentEventType.REFUND_SUCCEEDED, by_ref=False, event_id="evt_late_refund"
    )

    assert result.outcome == "applied"
    refund = reload(db, refund)
    assert refund.status == "SUCCEEDED", "a verified fact closes the unknown outcome"
    assert amounts(db, payment) == (Decimal(50), Decimal(10), Decimal(10)), "counted once"
    assert len(refunds(db)) == 1, "it was matched with our refund, not recorded as one started by the provider"


# --- Qué cobros se pueden devolver --------------------------------------------------------------------------------


@pytest.mark.parametrize("status", ["OPEN", "FAILED", "EXPIRED"])
def test_a_payment_without_captured_money_cannot_be_refunded(db: Session, order: Order, status):
    provider = ScriptedPaymentProvider()
    payment = start_attempt(db, order, provider)
    if status != "OPEN":
        kind = PaymentEventType.PAYMENT_FAILED if status == "FAILED" else PaymentEventType.PAYMENT_EXPIRED
        deliver(db, provider, kind, payment)
    calls = len(provider.calls)

    with pytest.raises(ConflictError, match="only a payment with money captured"):
        refund_of(db, reload(db, payment), provider)

    assert refunds(db) == [] and len(provider.calls) == calls


def test_the_money_of_a_duplicate_or_mismatched_capture_can_be_refunded_up_to_what_was_really_captured(
    db: Session, order: Order
):
    provider = ScriptedPaymentProvider()
    first = start_attempt(db, order, provider)
    deliver(db, provider, PaymentEventType.PAYMENT_EXPIRED, first)
    second = start_attempt(db, order, provider)
    deliver(db, provider, PaymentEventType.PAYMENT_SUCCEEDED, second)
    deliver(db, provider, PaymentEventType.PAYMENT_SUCCEEDED, first)  # un segundo cobro real: DUPLICATE_CAPTURE
    first = reload(db, first)
    assert first.status == "DUPLICATE_CAPTURE"

    refund = refund_of(db, first, provider, "50.00", reason="duplicate_capture")

    assert refund.status == "SENDING" and amounts(db, first) == (Decimal(50), Decimal(50), Decimal(0))

    mismatch_order = add_order(db, add_product(db, name="Gadget"), customer="sim_other")
    odd = start_attempt(db, mismatch_order, provider)
    deliver(db, provider, PaymentEventType.PAYMENT_SUCCEEDED, odd, amount="12.50")
    odd = reload(db, odd)
    assert odd.status == "CAPTURE_MISMATCH"
    with pytest.raises(ConflictError, match="left to refund"):
        refund_of(db, odd, provider, "12.51")
    assert refund_of(db, odd, provider, "12.50", reason="capture_mismatch").status == "SENDING"


def test_money_captured_late_on_a_cancelled_order_can_be_refunded(db: Session, order: Order):
    provider = ScriptedPaymentProvider()
    payment = start_attempt(db, order, provider)
    deliver(db, provider, PaymentEventType.PAYMENT_EXPIRED, payment)
    from app.orders.service import OrderService

    OrderService(db, settings=SIMULATION).cancel(order.id, actor="t")
    deliver(db, provider, PaymentEventType.PAYMENT_SUCCEEDED, payment)
    payment = reload(db, payment)
    assert reload(db, order).status == "CANCELLED" and payment.status == "SUCCEEDED"

    refund = refund_of(db, payment, provider, "50.00", reason="order_cancelled")

    assert refund.status == "SENDING"
    assert reload(db, order).status == "CANCELLED", "the system does not reopen the order"


# --- Reglas de forma ----------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "amount, currency, reason, message",
    [
        ("0.00", "EUR", "other", "more than zero"),
        ("1.005", "EUR", "other", "whole number of cents"),
        ("5.00", "USD", "other", "is in EUR"),
        ("5.00", "EUR", "because I said so", "reason must be one of"),
    ],
)
def test_malformed_refund_requests_are_refused_before_anything_is_written(
    db: Session, order: Order, amount, currency, reason, message
):
    provider = ScriptedPaymentProvider()
    payment = captured(db, order, provider)
    calls = len(provider.calls)

    with pytest.raises(ValidationError, match=message):
        RefundService(db, settings=SIMULATION, provider=provider).request(
            payment.id, amount=Money.of(amount, currency), reason=reason, requester=REQUESTER
        )

    assert refunds(db) == [] and len(provider.calls) == calls and amounts(db, payment)[1] == 0


def test_a_refund_names_a_payment_of_that_order_and_one_that_exists(db: Session, order: Order):
    provider = ScriptedPaymentProvider()
    payment = captured(db, order, provider)

    with pytest.raises(NotFoundError):
        refund_of(db, payment, provider, order_id="another-order")
    with pytest.raises(NotFoundError):
        RefundService(db, settings=SIMULATION, provider=provider).request(
            "missing", amount=Money.of("1.00", "EUR"), reason="other", requester=REQUESTER
        )
    assert refund_of(db, payment, provider, order_id=order.id).status == "SENDING"


# --- Fallos confirmados y resultado desconocido -------------------------------------------------------------------


@pytest.mark.parametrize("behavior", ["reject", "unreachable"])
def test_a_confirmed_failure_releases_what_was_set_aside(db: Session, order: Order, behavior):
    provider = ScriptedPaymentProvider("ok", behavior)
    payment = captured(db, order, provider)

    refund = refund_of(db, payment, provider, "10.00")

    assert refund.status == "FAILED" and refund.failure_code == "provider_rejected"
    assert amounts(db, payment) == (Decimal(50), Decimal(0), Decimal(0)), "nothing happened, nothing is reserved"
    assert refund_of(db, payment, provider, "50.00").status == "SENDING", "the whole amount is available again"


def test_a_timeout_after_the_provider_executed_keeps_the_reservation_and_blocks_new_refunds(db: Session, order: Order):
    provider = ScriptedPaymentProvider("ok", "timeout_after")
    payment = captured(db, order, provider)

    refund = refund_of(db, payment, provider, "10.00")

    assert refund.status == "UNKNOWN_OUTCOME", "a timeout is never a confirmed failure"
    assert amounts(db, payment) == (Decimal(50), Decimal(10), Decimal(0)), "an unknown outcome releases nothing"
    assert action_of(db, refund).status == ActionStatus.UNKNOWN_OUTCOME.value
    calls = len(provider.calls)
    with pytest.raises(OutcomeUnknownBlockError, match="unknown outcome"):
        refund_of(db, payment, provider, "5.00")
    assert len(provider.calls) == calls, "nothing was repeated blindly" and len(refunds(db)) == 1
    assert REFUND_OUTCOME_UNKNOWN in attention_reasons(db, reload(db, order))


def test_the_lookup_that_finds_the_refund_sends_it_back_to_waiting_for_the_fact(db: Session, order: Order):
    provider = ScriptedPaymentProvider("ok", "timeout_after")
    payment = captured(db, order, provider)
    refund = refund_of(db, payment, provider, "10.00")

    status = ExternalActionService(db).reconcile(action_of(db, refund), provider, {})

    assert status is ActionStatus.SUCCEEDED
    refund = reload(db, refund)
    assert refund.status == "SENDING" and refund.provider_refund_ref is not None
    assert amounts(db, payment)[1] == 10


def test_a_person_who_checked_that_nothing_was_refunded_releases_the_reservation(db: Session, order: Order):
    provider = ScriptedPaymentProvider("ok", "timeout_before")
    payment = captured(db, order, provider)
    refund = refund_of(db, payment, provider, "10.00")
    assert refund.status == "UNKNOWN_OUTCOME"

    ExternalActionService(db).resolve(
        action_of(db, refund), succeeded=False, actor="owner@amazona.local", reason="checked the gateway dashboard"
    )

    refund = reload(db, refund)
    assert refund.status == "FAILED" and refund.failure_code == "resolved_failed"
    assert amounts(db, payment) == (Decimal(50), Decimal(0), Decimal(0))
    assert refund_of(db, payment, provider, "10.00").status == "SENDING"


def test_a_person_who_checked_that_the_refund_happened_keeps_it_and_waits_for_the_fact(db: Session, order: Order):
    provider = ScriptedPaymentProvider("ok", "timeout_after")
    payment = captured(db, order, provider)
    refund = refund_of(db, payment, provider, "10.00")

    ExternalActionService(db).resolve(
        action_of(db, refund), succeeded=True, actor="owner@amazona.local", reason="seen in the gateway dashboard"
    )

    assert reload(db, refund).status == "SENDING" and amounts(db, payment)[1] == 10


def test_a_process_that_dies_in_the_middle_of_the_call_keeps_the_amount_reserved(db: Session, order: Order):
    provider = ScriptedPaymentProvider("ok", "die")
    payment = captured(db, order, provider)

    with pytest.raises(KeyboardInterrupt):
        refund_of(db, payment, provider, "10.00")
    db.rollback()
    refund = refunds(db)[0]

    assert refund.status == "SENDING", "past the durability frontier: it may have left"
    assert amounts(db, payment)[1] == 10
    assert ExternalActionService(db).mark_interrupted(refund_reference(refund.id)) is not None
    assert reload(db, refund).status == "UNKNOWN_OUTCOME" and amounts(db, payment)[1] == 10


def test_a_process_that_dies_before_calling_leaves_nothing_sent_and_the_sweep_releases_the_amount(
    db: Session, order: Order
):
    provider = ScriptedPaymentProvider()
    payment = captured(db, order, provider)
    original = ExternalActionService.execute

    def die_before_the_frontier(self, action, adapter, payload):
        raise KeyboardInterrupt("died after opening the operation and before calling")

    ExternalActionService.execute = die_before_the_frontier  # type: ignore[method-assign]
    calls = len(provider.calls)
    try:
        with pytest.raises(KeyboardInterrupt):
            refund_of(db, payment, provider, "10.00")
    finally:
        ExternalActionService.execute = original  # type: ignore[method-assign]
    db.rollback()
    stuck = refunds(db)[0]
    assert stuck.status == "REQUESTED" and len(provider.calls) == calls, "REQUESTED guarantees that nothing was sent"
    assert amounts(db, payment)[1] == 10

    swept = ExternalActionService(db).reconcile_interrupted(older_than=datetime.timedelta(seconds=-1))

    assert len(swept["released"]) == 1
    assert reload(db, stuck).status == "FAILED" and reload(db, stuck).failure_code == "not_sent"
    assert amounts(db, payment)[1] == 0


def test_the_provider_denying_the_refund_releases_the_amount_and_a_later_success_is_a_conflict(
    db: Session, order: Order
):
    provider = ScriptedPaymentProvider()
    payment = captured(db, order, provider)
    refund = refund_of(db, payment, provider, "10.00")

    failed = refund_event(db, provider, refund, PaymentEventType.REFUND_FAILED, event_id="evt_refund_failed")

    assert failed.outcome == "applied"
    assert reload(db, refund).status == "FAILED" and amounts(db, payment) == (Decimal(50), Decimal(0), Decimal(0))
    contradiction = refund_event(db, provider, refund, PaymentEventType.REFUND_SUCCEEDED)
    assert contradiction.outcome == "conflict", "the evidence is kept and a person looks at it"
    assert amounts(db, payment) == (Decimal(50), Decimal(0), Decimal(0))


def test_a_confirmation_for_another_amount_is_kept_as_a_conflict_and_changes_no_total(db: Session, order: Order):
    provider = ScriptedPaymentProvider()
    payment = captured(db, order, provider)
    refund = refund_of(db, payment, provider, "10.00")

    result = refund_event(db, provider, refund, PaymentEventType.REFUND_SUCCEEDED, amount="9.00")

    assert result.outcome == "conflict"
    assert reload(db, refund).status == "SENDING" and amounts(db, payment) == (Decimal(50), Decimal(10), Decimal(0))


# --- Gobierno de la operación -------------------------------------------------------------------------------------


def test_a_kill_switch_that_is_off_stops_the_refund_before_anything_is_written(db: Session, order: Order):
    provider = ScriptedPaymentProvider()
    payment = captured(db, order, provider)
    PipelineKillSwitchService(db).disable(reason="test", actor="owner@amazona.local", correlation_id="c-ks")
    calls = len(provider.calls)

    with pytest.raises(OperationNotAllowedError, match="kill switch"):
        refund_of(db, payment, provider)

    assert refunds(db) == [] and len(provider.calls) == calls and amounts(db, payment)[1] == 0
    assert db.scalars(select(AuditLog).where(AuditLog.action == "action_gate.deny")).first() is not None


def test_a_kill_switch_turned_off_between_the_gate_and_the_call_sends_nothing_and_releases_the_amount(
    db: Session, order: Order
):
    provider = ScriptedPaymentProvider()
    payment = captured(db, order, provider)
    original = ExternalActionService.begin_call

    def switch_off_then_begin(self, action):
        PipelineKillSwitchService(db).disable(reason="test", actor="owner@amazona.local", correlation_id="c-ks")
        return original(self, action)

    calls = len(provider.calls)
    ExternalActionService.begin_call = switch_off_then_begin  # type: ignore[method-assign]
    try:
        with pytest.raises(OperationNotAllowedError):
            refund_of(db, payment, provider)
    finally:
        ExternalActionService.begin_call = original  # type: ignore[method-assign]

    refund = refunds(db)[0]
    assert len(provider.calls) == calls, "the last check is before the irreversible effect"
    assert refund.status == "FAILED" and refund.failure_code == "not_sent"
    assert amounts(db, payment)[1] == 0


def test_a_refund_ignores_the_legal_and_economic_no_go_of_the_product(db: Session, order: Order):
    """Devolver un cobro es una obligación: un `NO_GO` posterior del producto no la veta."""
    from app.db.models.economic_analysis import EconomicAnalysis
    from app.db.models.legal_analysis import LegalAnalysis

    provider = ScriptedPaymentProvider()
    payment = captured(db, order, provider)
    product_id = order.items[0].product_id
    quote = add_quote(db, db.get(Product, product_id), add_supplier(db))
    db.add(
        LegalAnalysis(
            product_id=product_id, market=order.market, recommendation="NO_GO", confidence=1, correlation_id="c"
        )
    )
    db.add(
        EconomicAnalysis(
            product_id=product_id,
            supplier_quote_id=quote.id,
            sale_price=25.0,
            monthly_fixed_costs=500.0,
            margin_percent=0.0,
            recommendation="NO_GO",
            confidence=0.9,
            data={"scenarios": {}},
            correlation_id="c",
        )
    )
    db.commit()

    assert refund_of(db, payment, provider).status == "SENDING"


def test_a_refund_consumes_no_operating_budget(db: Session, order: Order):
    from app.budgets.service import BudgetLedgerService

    provider = ScriptedPaymentProvider()
    payment = captured(db, order, provider)

    refund_of(db, payment, provider, "50.00")

    ledger = BudgetLedgerService(db)
    assert ledger.find_budget() is None, "no budget was needed, none was created, none was spent"


def test_the_absence_of_identity_outside_a_simulation_is_not_a_permission(db: Session, order: Order):
    provider = ScriptedPaymentProvider()
    payment = captured(db, order, provider)

    with pytest.raises(OperationNotAllowedError, match="not allowed"):
        RefundService(db, settings=REAL, provider=provider).request(
            payment.id, amount=Money.of("1.00", "EUR"), reason="other", requester=Requester(name="anonymous", role=None)
        )

    assert refunds(db) == []


def test_an_identified_role_may_refund_without_the_approval_that_spending_needs(db: Session, order: Order):
    provider = ScriptedPaymentProvider()
    payment = captured(db, order, provider)

    refund = RefundService(db, settings=REAL, provider=provider).request(
        payment.id, amount=Money.of("1.00", "EUR"), reason="other", requester=OWNER
    )

    assert refund.status == "SENDING"


def test_a_payment_taken_by_another_provider_is_not_refunded_by_this_one(db: Session, order: Order):
    provider = ScriptedPaymentProvider()
    payment = captured(db, order, provider)
    from sqlalchemy import update

    db.execute(update(Payment).where(Payment.id == payment.id).values(provider="some-other-gateway"))
    db.commit()

    with pytest.raises(ConflictError, match="was taken by some-other-gateway"):
        refund_of(db, payment, provider)


# --- Atención -----------------------------------------------------------------------------------------------------


def test_a_refund_the_provider_never_confirms_asks_for_attention_after_a_while(db: Session, order: Order):
    provider = ScriptedPaymentProvider()
    payment = captured(db, order, provider)
    refund_of(db, payment, provider)

    fresh = reload(db, order)
    assert REFUND_UNCONFIRMED not in attention_reasons(db, fresh)
    later = datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=2)
    assert REFUND_UNCONFIRMED in attention_reasons(db, fresh, now=later)


def test_a_confirmed_refund_asks_for_no_attention(db: Session, order: Order):
    provider = ScriptedPaymentProvider()
    payment = captured(db, order, provider)
    refund = refund_of(db, payment, provider)
    refund_event(db, provider, refund, PaymentEventType.REFUND_SUCCEEDED)

    later = datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=2)
    assert attention_reasons(db, reload(db, order), now=later) == []


# --- El observador ------------------------------------------------------------------------------------------------


def test_the_refund_observer_is_registered_for_the_namespace_of_refunds():
    from app.actions.observers import observers_for
    from app.payments.refund_projection import RefundActionObserver

    found = observers_for(refund_reference("any"))

    assert len(found) == 1 and isinstance(found[0], RefundActionObserver)


def test_if_the_refund_cannot_follow_the_action_the_request_never_leaves(db: Session, order: Order, monkeypatch):
    from app.payments.refund_projection import RefundActionObserver

    provider = ScriptedPaymentProvider()
    payment = captured(db, order, provider)

    def refuse(self, db, refund, action):
        raise RuntimeError("the refund cannot follow this action")

    monkeypatch.setattr(RefundActionObserver, "_begin", refuse)
    calls = len(provider.calls)

    with pytest.raises(RuntimeError, match="cannot follow"):
        refund_of(db, payment, provider)
    db.rollback()

    assert len(provider.calls) == calls, "an action never starts without its domain"
    refund = refunds(db)[0]
    assert refund.status == "REQUESTED" and action_of(db, refund).status == ActionStatus.PENDING.value
