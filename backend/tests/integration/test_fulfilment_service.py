"""Repartir, comprar, enviar y cerrar un pedido pagado (Milestone 44, ADR 0028 §3, §6 y §7).

Comprar y enviar son acciones externas gobernadas con resultado desconocido explícito; la asignación de unidades es
aritmética de base de datos; y **una unidad comprada no vuelve al pool**: solo un fulfillment que nunca compró puede
devolver sus unidades, y solo por `release_allocation()`.
"""

import datetime

import pytest
from fulfilment_test_support import (
    REQUESTER,
    SIMULATION,
    ScriptedFulfilmentProvider,
    allocated,
    create_fulfillment,
    items_of,
    paid_order,
    reload,
    service,
)
from order_test_support import add_product, make_engine, session_factory
from payment_test_support import ScriptedPaymentProvider
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.actions.contract import ActionStatus
from app.actions.service import ExternalActionService
from app.budgets.service import BudgetLedgerService
from app.core.config import Settings
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.db.models.audit import AuditLog
from app.db.models.external_action import ExternalAction
from app.db.models.fulfillment import Fulfillment
from app.db.models.order import Order
from app.integrations.operating_policy import OperationNotPermittedError
from app.integrations.ports import ProviderKind
from app.money.money import Money
from app.orders import attention
from app.orders.errors import OperationNotAllowedError, OutcomeUnknownBlockError
from app.orders.fulfilment import FulfilmentRequestLine
from app.orders.fulfilment_projection import FulfilmentMovedError, fulfilment_reference
from app.orders.payment_attempts import Requester
from app.orders.refunds import RefundService
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
    return paid_order(db)


def action_of(db: Session, fulfillment: Fulfillment, phase: str) -> ExternalAction:
    return db.scalars(
        select(ExternalAction)
        .where(ExternalAction.reference == fulfilment_reference(fulfillment.id, phase))
        .order_by(ExternalAction.sequence.desc())
    ).first()  # type: ignore[return-value]


def status_of(db: Session, order: Order) -> str:
    db.expire_all()
    found = db.get(Order, order.id)
    assert found is not None
    return found.status


def reasons(db: Session, order: Order) -> list[str]:
    db.expire_all()
    return attention.attention_reasons(db, db.get(Order, order.id))  # type: ignore[arg-type]


# --- Crear: una decisión local --------------------------------------------------------------------------------


def test_a_paid_order_is_assigned_to_a_fulfillment_and_nothing_goes_out(db: Session, order: Order):
    provider = ScriptedFulfilmentProvider()

    fulfillment = create_fulfillment(db, order, provider)

    assert fulfillment.status == "READY" and fulfillment.provider == provider.name
    assert fulfillment.supplier_id is not None and fulfillment.created_by == "owner@amazona.local"
    assert [(i.order_item_id, i.quantity) for i in fulfillment.items] == [
        (item.id, q) for item, q in zip(items_of(db, order), (4, 2), strict=True)
    ]
    assert allocated(db, order) == [4, 2]
    assert provider.calls == [] and db.scalars(select(ExternalAction)).all() is not None
    assert db.scalars(select(AuditLog).where(AuditLog.action == "fulfillment.created")).one()


def test_a_line_can_be_split_among_fulfillments_until_it_is_all_assigned(db: Session, order: Order):
    provider = ScriptedFulfilmentProvider()

    create_fulfillment(db, order, provider, (3, 0))
    create_fulfillment(db, order, provider, (1, 2))

    assert allocated(db, order) == [4, 2]
    with pytest.raises(ConflictError):
        create_fulfillment(db, order, provider, (1, 0))
    assert allocated(db, order) == [4, 2]
    assert len(db.scalars(select(Fulfillment)).all()) == 2, "a request that does not fit leaves nothing behind"


def test_a_request_that_partly_fits_assigns_nothing(db: Session, order: Order):
    provider = ScriptedFulfilmentProvider()
    create_fulfillment(db, order, provider, (0, 2))

    with pytest.raises(ConflictError):
        create_fulfillment(db, order, provider, (4, 1))  # la línea 1 cabe, la 2 no

    assert allocated(db, order) == [0, 2], "all or nothing"
    assert len(db.scalars(select(Fulfillment)).all()) == 1


def test_the_same_line_twice_in_a_request_adds_up(db: Session, order: Order):
    item = items_of(db, order)[0]

    fulfillment = service(db, ScriptedFulfilmentProvider()).create(
        order.id, [FulfilmentRequestLine(item.id, 1), FulfilmentRequestLine(item.id, 2)], actor="t"
    )

    assert [(i.quantity) for i in fulfillment.items] == [3] and allocated(db, order) == [3, 0]


@pytest.mark.parametrize("status", ["AWAITING_PAYMENT", "CANCELLED"])
def test_only_a_paid_order_is_fulfilled(db: Session, status):
    from payment_test_support import add_order

    unpaid = add_order(db, add_product(db, name="Gamma"), customer="sim_unpaid")
    if status == "CANCELLED":
        from app.orders.service import OrderService

        OrderService(db, settings=SIMULATION).cancel(unpaid.id, actor="t")

    item = items_of(db, unpaid)[0]
    with pytest.raises(ConflictError, match="only a paid order is fulfilled"):
        service(db, ScriptedFulfilmentProvider()).create(unpaid.id, [FulfilmentRequestLine(item.id, 1)], actor="t")

    assert allocated(db, unpaid) == [0]


def test_an_order_that_was_refunded_is_not_fulfilled(db: Session, order: Order):
    payment_ids = [p.id for p in order.__dict__.get("payments", [])] or None
    from app.db.models.payment import Payment

    payment = db.scalars(select(Payment).where(Payment.order_id == order.id)).one()
    RefundService(db, settings=SIMULATION, provider=ScriptedPaymentProvider()).request(
        payment.id, amount=Money.of("1.00", "EUR"), reason="goodwill", requester=REQUESTER
    )
    assert payment_ids is None or payment_ids

    with pytest.raises(ConflictError, match="no longer fully paid"):
        create_fulfillment(db, order, ScriptedFulfilmentProvider())

    assert allocated(db, order) == [0, 0]


def test_malformed_fulfillment_requests_are_refused(db: Session, order: Order):
    provider = ScriptedFulfilmentProvider()
    first = items_of(db, order)[0]

    with pytest.raises(ValidationError):
        service(db, provider).create(order.id, [], actor="t")
    with pytest.raises(ValidationError):
        service(db, provider).create(order.id, [FulfilmentRequestLine(first.id, 0)], actor="t")
    with pytest.raises(NotFoundError, match="has no line"):
        service(db, provider).create(order.id, [FulfilmentRequestLine("nope", 1)], actor="t")
    with pytest.raises(NotFoundError):
        service(db, provider).create("missing", [FulfilmentRequestLine(first.id, 1)], actor="t")
    assert allocated(db, order) == [0, 0]


def test_a_line_of_another_order_cannot_be_assigned(db: Session, order: Order):
    other = paid_order(db, customer="sim_other")
    foreign = items_of(db, other)[0]

    with pytest.raises(NotFoundError, match="has no line"):
        service(db, ScriptedFulfilmentProvider()).create(order.id, [FulfilmentRequestLine(foreign.id, 1)], actor="t")

    assert allocated(db, other) == [0, 0]


def test_a_fulfillment_buys_from_one_supplier(db: Session):
    from order_test_support import add_quote, add_supplier, create_order, line
    from payment_test_support import deliver, start_attempt

    first, second = add_product(db, name="One"), add_product(db, name="Two")
    quote_a, quote_b = add_quote(db, first, add_supplier(db, "Acme")), add_quote(db, second, add_supplier(db, "Beta"))
    order = create_order(db, line(first, quote=quote_a), line(second, quote=quote_b), customer_ref="sim_two_suppliers")
    provider = ScriptedPaymentProvider()
    from app.payments.port import PaymentEventType

    deliver(db, provider, PaymentEventType.PAYMENT_SUCCEEDED, start_attempt(db, order, provider))
    a, b = items_of(db, order)

    with pytest.raises(ValidationError, match="single supplier"):
        service(db, ScriptedFulfilmentProvider()).create(
            order.id, [FulfilmentRequestLine(a.id, 1), FulfilmentRequestLine(b.id, 1)], actor="t"
        )
    # Por separado, sí.
    service(db, ScriptedFulfilmentProvider()).create(order.id, [FulfilmentRequestLine(a.id, 1)], actor="t")
    service(db, ScriptedFulfilmentProvider()).create(order.id, [FulfilmentRequestLine(b.id, 1)], actor="t")


# --- Comprar --------------------------------------------------------------------------------------------------


def test_a_purchase_is_made_at_the_provider_and_the_units_stay_assigned(db: Session, order: Order):
    provider = ScriptedFulfilmentProvider()
    fulfillment = create_fulfillment(db, order, provider)

    bought = service(db, provider).purchase(fulfillment.id, requester=REQUESTER)

    assert bought.status == "PURCHASED" and bought.purchased_at is not None
    assert bought.purchase_reference.startswith("simpo_") and bought.failed_attempts == 0
    action = action_of(db, bought, "purchase")
    assert action.status == ActionStatus.SUCCEEDED.value and action.operation == "fulfillment.purchase"
    assert action.applied_at is not None, "the domain already recorded this result"
    assert len(provider.calls) == 1 and allocated(db, order) == [4, 2]
    payload = provider.calls[0].payload
    assert payload["fulfillment_id"] == fulfillment.id and len(payload["lines"]) == 2
    assert set(payload) == {"fulfillment_id", "order_id", "phase", "lines"}, "ids and quantities: no personal data"
    assert status_of(db, order) == "PAID"


def test_a_purchase_spends_the_budget_it_declared(db: Session, order: Order):
    ledger = BudgetLedgerService(db)
    ledger.authorise_budget(hard_limit=1000.0, actor="owner@amazona.local")
    provider = ScriptedFulfilmentProvider()
    fulfillment = create_fulfillment(db, order, provider)

    service(db, provider).purchase(fulfillment.id, requester=REQUESTER)

    snapshot = ledger.snapshot()
    assert snapshot is not None
    assert snapshot.reserved == pytest.approx(0.0) and snapshot.committed == pytest.approx(29.0), (
        "4 × 6.00 + 2 × 2.50 of supplier cost was set aside and then committed"
    )
    assert action_of(db, fulfillment, "purchase").amount == pytest.approx(29.0)


def test_a_purchase_that_the_budget_cannot_cover_is_denied_before_anything_goes_out(db: Session, order: Order):
    BudgetLedgerService(db).authorise_budget(hard_limit=10.0, actor="owner@amazona.local")
    provider = ScriptedFulfilmentProvider()
    fulfillment = create_fulfillment(db, order, provider)

    with pytest.raises(OperationNotAllowedError):
        service(db, provider).purchase(fulfillment.id, requester=REQUESTER)

    assert provider.calls == [] and reload(db, fulfillment).status == "READY"
    assert db.scalars(select(AuditLog).where(AuditLog.action == "action_gate.deny")).first() is not None


def test_a_purchase_whose_cost_is_unknown_is_never_made_as_if_it_were_free(db: Session):
    order = paid_order(db, with_cost=False, customer="sim_unknown_cost")
    provider = ScriptedFulfilmentProvider()
    fulfillment = create_fulfillment(db, order, provider)

    with pytest.raises(OperationNotAllowedError, match="unknown"):
        service(db, provider).purchase(fulfillment.id, requester=REQUESTER)

    assert provider.calls == [] and reload(db, fulfillment).status == "READY"


def test_only_a_ready_fulfillment_can_be_purchased(db: Session, order: Order):
    provider = ScriptedFulfilmentProvider()
    fulfillment = create_fulfillment(db, order, provider)
    service(db, provider).purchase(fulfillment.id, requester=REQUESTER)
    calls = len(provider.calls)

    with pytest.raises(ConflictError, match="needs it READY"):
        service(db, provider).purchase(fulfillment.id, requester=REQUESTER)

    assert len(provider.calls) == calls, "a purchase is never made twice"
    with pytest.raises(NotFoundError):
        service(db, provider).purchase("missing", requester=REQUESTER)


def test_a_confirmed_rejection_leaves_it_ready_to_retry_and_asks_for_attention(db: Session, order: Order):
    provider = ScriptedFulfilmentProvider("reject")
    fulfillment = create_fulfillment(db, order, provider)

    failed = service(db, provider).purchase(fulfillment.id, requester=REQUESTER)

    assert failed.status == "READY" and failed.failed_attempts == 1
    assert failed.last_failure_code == "purchase:provider_rejected" and failed.purchased_at is None
    assert allocated(db, order) == [4, 2], "nothing was bought but the units stay with the fulfillment"
    assert attention.FULFILMENT_PURCHASE_FAILED in reasons(db, order)

    retried = service(db, provider).purchase(fulfillment.id, requester=REQUESTER)

    assert retried.status == "PURCHASED" and retried.failed_attempts == 1
    first, second = (
        db.scalars(
            select(ExternalAction)
            .where(ExternalAction.operation == "fulfillment.purchase")
            .order_by(ExternalAction.sequence)
        )
    ).all()
    assert first.status == ActionStatus.FAILED_CONFIRMED.value and second.status == ActionStatus.SUCCEEDED.value
    assert first.idempotency_key != second.idempotency_key, "a deliberate retry is a new operation"
    assert attention.FULFILMENT_PURCHASE_FAILED not in reasons(db, order)


def test_an_unreachable_provider_is_a_confirmed_failure_too(db: Session, order: Order):
    provider = ScriptedFulfilmentProvider("unreachable")
    fulfillment = create_fulfillment(db, order, provider)

    assert service(db, provider).purchase(fulfillment.id, requester=REQUESTER).status == "READY"


def test_a_timeout_after_the_provider_executed_is_an_unknown_outcome_that_blocks_everything(db: Session, order: Order):
    provider = ScriptedFulfilmentProvider("timeout_after")
    fulfillment = create_fulfillment(db, order, provider)

    unknown = service(db, provider).purchase(fulfillment.id, requester=REQUESTER)

    assert unknown.status == "UNKNOWN_OUTCOME" and unknown.unknown_phase == "purchase"
    assert allocated(db, order) == [4, 2], "an unknown outcome gives nothing back"
    assert attention.FULFILMENT_OUTCOME_UNKNOWN in reasons(db, order)
    calls = len(provider.calls)
    with pytest.raises(OutcomeUnknownBlockError, match="unknown purchase outcome"):
        service(db, provider).purchase(fulfillment.id, requester=REQUESTER)
    with pytest.raises(OutcomeUnknownBlockError, match="cannot return to the pool"):
        service(db, provider).cancel(fulfillment.id, actor="t")
    with pytest.raises(OutcomeUnknownBlockError):
        service(db, provider).fail(fulfillment.id, actor="t")
    assert len(provider.calls) == calls, "nothing was repeated blindly"
    assert allocated(db, order) == [4, 2]


def test_the_lookup_that_finds_the_purchase_makes_it_purchased(db: Session, order: Order):
    provider = ScriptedFulfilmentProvider("timeout_after")
    fulfillment = create_fulfillment(db, order, provider)
    service(db, provider).purchase(fulfillment.id, requester=REQUESTER)

    status = ExternalActionService(db).reconcile(action_of(db, fulfillment, "purchase"), provider, {})

    assert status is ActionStatus.SUCCEEDED
    done = reload(db, fulfillment)
    assert done.status == "PURCHASED" and done.unknown_phase is None and done.purchase_reference is not None
    assert done.purchased_at is not None


def test_a_person_who_checked_that_nothing_was_bought_sends_it_back_to_ready(db: Session, order: Order):
    provider = ScriptedFulfilmentProvider("timeout_before")
    fulfillment = create_fulfillment(db, order, provider)
    assert service(db, provider).purchase(fulfillment.id, requester=REQUESTER).status == "UNKNOWN_OUTCOME"

    ExternalActionService(db).resolve(
        action_of(db, fulfillment, "purchase"), succeeded=False, actor="owner@amazona.local", reason="checked"
    )

    ready = reload(db, fulfillment)
    assert ready.status == "READY" and ready.unknown_phase is None and ready.failed_attempts == 1
    assert ready.last_failure_code == "purchase:resolved_failed"
    assert service(db, provider).purchase(fulfillment.id, requester=REQUESTER).status == "PURCHASED"


def test_a_person_who_checked_that_it_was_bought_makes_it_purchased(db: Session, order: Order):
    provider = ScriptedFulfilmentProvider("timeout_after")
    fulfillment = create_fulfillment(db, order, provider)
    service(db, provider).purchase(fulfillment.id, requester=REQUESTER)

    ExternalActionService(db).resolve(
        action_of(db, fulfillment, "purchase"), succeeded=True, actor="owner@amazona.local", reason="seen in the portal"
    )

    assert reload(db, fulfillment).status == "PURCHASED"


def test_a_process_that_dies_in_the_middle_of_the_purchase_may_have_bought(db: Session, order: Order):
    provider = ScriptedFulfilmentProvider("die")
    fulfillment = create_fulfillment(db, order, provider)

    with pytest.raises(KeyboardInterrupt):
        service(db, provider).purchase(fulfillment.id, requester=REQUESTER)
    db.rollback()

    assert reload(db, fulfillment).status == "PURCHASING", "past the durability frontier: it may have left"
    with pytest.raises(ConflictError):
        service(db, provider).cancel(fulfillment.id, actor="t")
    assert allocated(db, order) == [4, 2]
    assert ExternalActionService(db).mark_interrupted(fulfilment_reference(fulfillment.id, "purchase")) is not None
    unknown = reload(db, fulfillment)
    assert unknown.status == "UNKNOWN_OUTCOME" and unknown.unknown_phase == "purchase"


def test_a_process_that_dies_before_calling_sent_nothing_and_the_sweep_leaves_it_ready(db: Session, order: Order):
    provider = ScriptedFulfilmentProvider()
    fulfillment = create_fulfillment(db, order, provider)
    original = ExternalActionService.execute

    def die_before_the_frontier(self, action, adapter, payload):
        raise KeyboardInterrupt("died after opening the operation and before calling")

    ExternalActionService.execute = die_before_the_frontier  # type: ignore[method-assign]
    try:
        with pytest.raises(KeyboardInterrupt):
            service(db, provider).purchase(fulfillment.id, requester=REQUESTER)
    finally:
        ExternalActionService.execute = original  # type: ignore[method-assign]
    db.rollback()
    assert reload(db, fulfillment).status == "READY" and provider.calls == []

    swept = ExternalActionService(db).reconcile_interrupted(older_than=datetime.timedelta(seconds=-1))

    assert len(swept["released"]) == 1
    still = reload(db, fulfillment)
    assert still.status == "READY" and still.failed_attempts == 0, "an attempt that never left is not a failure"
    assert service(db, provider).purchase(fulfillment.id, requester=REQUESTER).status == "PURCHASED"


def test_a_kill_switch_that_is_off_stops_the_purchase_before_anything_is_written(db: Session, order: Order):
    provider = ScriptedFulfilmentProvider()
    fulfillment = create_fulfillment(db, order, provider)
    PipelineKillSwitchService(db).disable(reason="test", actor="owner@amazona.local", correlation_id="c-ks")

    with pytest.raises(OperationNotAllowedError, match="kill switch"):
        service(db, provider).purchase(fulfillment.id, requester=REQUESTER)

    assert provider.calls == [] and reload(db, fulfillment).status == "READY"
    assert db.scalars(select(ExternalAction).where(ExternalAction.operation == "fulfillment.purchase")).all() == []


def test_a_kill_switch_turned_off_between_the_gate_and_the_call_sends_nothing(db: Session, order: Order):
    provider = ScriptedFulfilmentProvider()
    fulfillment = create_fulfillment(db, order, provider)
    original = ExternalActionService.begin_call

    def switch_off_then_begin(self, action):
        PipelineKillSwitchService(db).disable(reason="test", actor="owner@amazona.local", correlation_id="c-ks")
        return original(self, action)

    ExternalActionService.begin_call = switch_off_then_begin  # type: ignore[method-assign]
    try:
        with pytest.raises(OperationNotAllowedError):
            service(db, provider).purchase(fulfillment.id, requester=REQUESTER)
    finally:
        ExternalActionService.begin_call = original  # type: ignore[method-assign]

    still = reload(db, fulfillment)
    assert provider.calls == [] and still.status == "READY" and still.failed_attempts == 0


def test_a_legal_no_go_of_the_product_denies_the_purchase(db: Session, order: Order):
    from app.db.models.legal_analysis import LegalAnalysis

    db.add(
        LegalAnalysis(
            product_id=items_of(db, order)[0].product_id,
            market=order.market,
            recommendation="NO_GO",
            confidence=1,
            correlation_id="c",
        )
    )
    db.commit()
    provider = ScriptedFulfilmentProvider()
    fulfillment = create_fulfillment(db, order, provider)

    with pytest.raises(OperationNotAllowedError, match="legal"):
        service(db, provider).purchase(fulfillment.id, requester=REQUESTER)

    assert provider.calls == []


def test_an_economic_no_go_vetoes_a_purchase_because_it_spends(db: Session, order: Order):
    from app.db.models.economic_analysis import EconomicAnalysis
    from app.db.models.supplier_quote import SupplierQuote

    item = items_of(db, order)[0]
    quote = db.scalars(select(SupplierQuote).where(SupplierQuote.product_id == item.product_id)).first()
    db.add(
        EconomicAnalysis(
            product_id=item.product_id,
            supplier_quote_id=quote.id,
            sale_price=10.0,
            monthly_fixed_costs=500.0,
            margin_percent=0.0,
            recommendation="NO_GO",
            confidence=0.9,
            data={"scenarios": {}},
            correlation_id="c",
        )
    )
    db.commit()
    provider = ScriptedFulfilmentProvider()
    fulfillment = create_fulfillment(db, order, provider)

    with pytest.raises(OperationNotAllowedError, match="economics"):
        service(db, provider).purchase(fulfillment.id, requester=REQUESTER)

    assert provider.calls == []


def test_outside_a_simulation_a_role_asks_for_approval_and_m44_has_no_inbox(db: Session):
    order = paid_order(db, customer="sim_real")
    provider = ScriptedFulfilmentProvider()
    fulfillment = create_fulfillment(db, order, provider)

    with pytest.raises(OperationNotAllowedError) as raised:
        service(db, provider, settings=REAL).purchase(fulfillment.id, requester=Requester("owner", "OWNER"))

    assert provider.calls == [] and reload(db, fulfillment).status == "READY"
    assert raised.value.reasons


def test_an_operation_the_provider_does_not_declare_is_denied_before_anything_is_written(db: Session, order: Order):
    class Foreign(ScriptedFulfilmentProvider):
        name = "some-real-carrier"

    provider = Foreign()
    fulfillment = create_fulfillment(db, order, ScriptedFulfilmentProvider())

    with pytest.raises(OperationNotPermittedError):
        service(db, provider).purchase(fulfillment.id, requester=REQUESTER)

    assert provider.calls == [] and reload(db, fulfillment).status == "READY"


def test_a_fulfillment_is_not_purchased_through_another_provider(db: Session, order: Order):
    fulfillment = create_fulfillment(db, order, ScriptedFulfilmentProvider())
    from sqlalchemy import update

    db.execute(update(Fulfillment).where(Fulfillment.id == fulfillment.id).values(provider="another-provider"))
    db.commit()
    provider = ScriptedFulfilmentProvider()

    with pytest.raises(ConflictError, match="belongs to another-provider"):
        service(db, provider).purchase(fulfillment.id, requester=REQUESTER)

    assert provider.calls == []


# --- Enviar ---------------------------------------------------------------------------------------------------


def purchased(db: Session, order: Order, provider: ScriptedFulfilmentProvider, quantities=(4, 2)) -> Fulfillment:
    fulfillment = create_fulfillment(db, order, provider, quantities)
    return service(db, provider).purchase(fulfillment.id, requester=REQUESTER)


def test_a_purchased_fulfillment_is_shipped_at_zero_declared_cost(db: Session, order: Order):
    provider = ScriptedFulfilmentProvider()
    fulfillment = purchased(db, order, provider)

    shipped = service(db, provider).ship(fulfillment.id, requester=REQUESTER)

    assert shipped.status == "SHIPPED" and shipped.shipped_at is not None
    assert shipped.tracking_reference.startswith("simtrk_")
    action = action_of(db, shipped, "ship")
    assert action.status == ActionStatus.SUCCEEDED.value and action.operation == "fulfillment.ship"
    assert action.amount is None, "a shipment declared at zero spends nothing"


def test_only_a_purchased_fulfillment_can_be_shipped(db: Session, order: Order):
    provider = ScriptedFulfilmentProvider()
    fulfillment = create_fulfillment(db, order, provider)

    with pytest.raises(ConflictError, match="needs it PURCHASED"):
        service(db, provider).ship(fulfillment.id, requester=REQUESTER)
    assert provider.calls == []


def test_a_shipment_that_fails_goes_back_to_purchased_and_the_units_stay_assigned(db: Session, order: Order):
    provider = ScriptedFulfilmentProvider("ok", "reject")
    fulfillment = purchased(db, order, provider)

    failed = service(db, provider).ship(fulfillment.id, requester=REQUESTER)

    assert failed.status == "PURCHASED", "it was bought: it is not a FAILED fulfillment"
    assert failed.failed_attempts == 1 and failed.last_failure_code == "ship:provider_rejected"
    assert allocated(db, order) == [4, 2] and failed.purchased_at is not None
    assert attention.FULFILMENT_SHIP_FAILED in reasons(db, order)
    with pytest.raises(ConflictError):
        service(db, provider).cancel(fulfillment.id, actor="t")
    with pytest.raises(ConflictError):
        service(db, provider).fail(fulfillment.id, actor="t")
    assert allocated(db, order) == [4, 2], "a bought unit does not return to the pool"

    again = service(db, provider).ship(fulfillment.id, requester=REQUESTER)

    assert again.status == "SHIPPED" and again.failed_attempts == 1
    assert attention.FULFILMENT_SHIP_FAILED not in reasons(db, order)


def test_a_timeout_after_the_shipment_is_an_unknown_ship_outcome(db: Session, order: Order):
    provider = ScriptedFulfilmentProvider("ok", "timeout_after")
    fulfillment = purchased(db, order, provider)

    unknown = service(db, provider).ship(fulfillment.id, requester=REQUESTER)

    assert unknown.status == "UNKNOWN_OUTCOME" and unknown.unknown_phase == "ship"
    with pytest.raises(OutcomeUnknownBlockError):
        service(db, provider).ship(fulfillment.id, requester=REQUESTER)
    assert allocated(db, order) == [4, 2]

    ExternalActionService(db).reconcile(action_of(db, fulfillment, "ship"), provider, {})

    assert reload(db, fulfillment).status == "SHIPPED"


def test_a_person_who_checked_that_nothing_was_shipped_sends_it_back_to_purchased(db: Session, order: Order):
    provider = ScriptedFulfilmentProvider("ok", "timeout_before")
    fulfillment = purchased(db, order, provider)
    service(db, provider).ship(fulfillment.id, requester=REQUESTER)

    ExternalActionService(db).resolve(
        action_of(db, fulfillment, "ship"), succeeded=False, actor="owner@amazona.local", reason="checked"
    )

    back = reload(db, fulfillment)
    assert back.status == "PURCHASED" and back.unknown_phase is None and back.failed_attempts == 1
    assert service(db, provider).ship(fulfillment.id, requester=REQUESTER).status == "SHIPPED"


def test_an_order_refunded_after_the_purchase_is_not_shipped(db: Session, order: Order):
    provider = ScriptedFulfilmentProvider()
    fulfillment = purchased(db, order, provider)
    from app.db.models.payment import Payment

    payment = db.scalars(select(Payment).where(Payment.order_id == order.id)).one()
    RefundService(db, settings=SIMULATION, provider=ScriptedPaymentProvider()).request(
        payment.id, amount=Money.of("50.00", "EUR"), reason="customer_request", requester=REQUESTER
    )
    calls = len(provider.calls)

    with pytest.raises(ConflictError, match="no longer fully paid"):
        service(db, provider).ship(fulfillment.id, requester=REQUESTER)

    assert len(provider.calls) == calls
    assert attention.REFUNDED_ORDER_IN_FULFILMENT in reasons(db, order)


# --- Entregar y cerrar el pedido ------------------------------------------------------------------------------


def shipped(db: Session, order: Order, provider: ScriptedFulfilmentProvider, quantities) -> Fulfillment:
    fulfillment = purchased(db, order, provider, quantities)
    return service(db, provider).ship(fulfillment.id, requester=REQUESTER)


def test_the_delivery_is_confirmed_by_a_person_and_the_order_closes_when_everything_is_delivered(
    db: Session, order: Order
):
    provider = ScriptedFulfilmentProvider()
    first = shipped(db, order, provider, (4, 0))
    second = shipped(db, order, provider, (0, 2))

    done_first = service(db, provider).complete(first.id, actor="owner@amazona.local")

    assert done_first.status == "COMPLETED" and done_first.completed_by == "owner@amazona.local"
    assert status_of(db, order) == "PAID", "one of two fulfillments is not the whole order"

    service(db, provider).complete(second.id, actor="owner@amazona.local")

    assert status_of(db, order) == "COMPLETED" and db.get(Order, order.id).completed_at is not None  # type: ignore[union-attr]
    assert db.scalars(select(AuditLog).where(AuditLog.action == "order.completed")).one()


def test_a_fulfillment_that_does_not_cover_everything_does_not_close_the_order(db: Session, order: Order):
    provider = ScriptedFulfilmentProvider()
    only = shipped(db, order, provider, (4, 0))

    service(db, provider).complete(only.id, actor="t")

    assert status_of(db, order) == "PAID"


def test_only_a_shipped_fulfillment_is_delivered_and_only_once(db: Session, order: Order):
    provider = ScriptedFulfilmentProvider()
    purchased_only = purchased(db, order, provider)
    with pytest.raises(ConflictError, match="only a shipped one is delivered"):
        service(db, provider).complete(purchased_only.id, actor="t")
    service(db, provider).ship(purchased_only.id, requester=REQUESTER)
    service(db, provider).complete(purchased_only.id, actor="t")

    with pytest.raises(ConflictError):
        service(db, provider).complete(purchased_only.id, actor="t")


# --- Devolver unidades al pool: solo si nunca se compró -------------------------------------------------------


def test_cancelling_before_buying_gives_the_units_back_to_the_pool(db: Session, order: Order):
    provider = ScriptedFulfilmentProvider()
    fulfillment = create_fulfillment(db, order, provider)

    cancelled = service(db, provider).cancel(fulfillment.id, actor="owner@amazona.local")

    assert cancelled.status == "CANCELLED" and cancelled.closed_at is not None
    assert allocated(db, order) == [0, 0]
    again = create_fulfillment(db, order, provider)
    assert again.status == "READY" and allocated(db, order) == [4, 2], "the units can be assigned again"
    with pytest.raises(ConflictError):
        service(db, provider).cancel(fulfillment.id, actor="t")
    assert allocated(db, order) == [4, 2], "cancelling twice does not release twice"


@pytest.mark.parametrize("progress", ["purchased", "shipped", "completed"])
def test_a_bought_fulfillment_cannot_give_its_units_back(db: Session, order: Order, progress):
    provider = ScriptedFulfilmentProvider()
    fulfillment = purchased(db, order, provider)
    if progress != "purchased":
        service(db, provider).ship(fulfillment.id, requester=REQUESTER)
    if progress == "completed":
        service(db, provider).complete(fulfillment.id, actor="t")

    with pytest.raises(ConflictError):
        service(db, provider).cancel(fulfillment.id, actor="t")
    with pytest.raises(ConflictError):
        service(db, provider).fail(fulfillment.id, actor="t")

    assert allocated(db, order) == [4, 2]
    with pytest.raises(ConflictError):
        create_fulfillment(db, order, provider, (1, 0))


def test_a_fulfillment_whose_purchase_failed_can_be_abandoned_and_gives_its_units_back(db: Session, order: Order):
    provider = ScriptedFulfilmentProvider("reject")
    fulfillment = create_fulfillment(db, order, provider)
    service(db, provider).purchase(fulfillment.id, requester=REQUESTER)

    failed = service(db, provider).fail(fulfillment.id, actor="owner@amazona.local")

    assert failed.status == "FAILED" and failed.purchased_at is None
    assert allocated(db, order) == [0, 0]


def test_a_fulfillment_that_has_not_failed_cannot_be_declared_failed(db: Session, order: Order):
    provider = ScriptedFulfilmentProvider()
    fulfillment = create_fulfillment(db, order, provider)

    with pytest.raises(ConflictError, match="has not failed: cancel it instead"):
        service(db, provider).fail(fulfillment.id, actor="t")

    assert reload(db, fulfillment).status == "READY" and allocated(db, order) == [4, 2]


def test_the_database_itself_refuses_to_cancel_what_was_bought(db: Session, order: Order):
    from sqlalchemy import update
    from sqlalchemy.exc import IntegrityError

    provider = ScriptedFulfilmentProvider()
    fulfillment = purchased(db, order, provider)

    with pytest.raises(IntegrityError, match="a_purchased_unit_never_returns_to_the_pool"):
        db.execute(update(Fulfillment).where(Fulfillment.id == fulfillment.id).values(status="CANCELLED"))
    db.rollback()
    assert reload(db, fulfillment).status == "PURCHASED"


# --- El observador --------------------------------------------------------------------------------------------


def test_the_fulfilment_observer_is_registered_for_its_namespace():
    from app.actions.observers import observers_for
    from app.orders.fulfilment_projection import FulfilmentActionObserver

    found = observers_for(fulfilment_reference("any", "purchase"))

    assert len(found) == 1 and isinstance(found[0], FulfilmentActionObserver)


def test_if_the_fulfillment_cannot_follow_the_action_the_request_never_leaves(db: Session, order: Order, monkeypatch):
    from app.orders.fulfilment_projection import FulfilmentActionObserver

    provider = ScriptedFulfilmentProvider()
    fulfillment = create_fulfillment(db, order, provider)

    def refuse(self, db, fulfillment, action, phase):
        raise RuntimeError("the fulfillment cannot follow this action")

    monkeypatch.setattr(FulfilmentActionObserver, "_begin", refuse)

    with pytest.raises(RuntimeError, match="cannot follow"):
        service(db, provider).purchase(fulfillment.id, requester=REQUESTER)
    db.rollback()

    assert provider.calls == [] and reload(db, fulfillment).status == "READY"
    assert action_of(db, fulfillment, "purchase").status == ActionStatus.PENDING.value


def test_a_purchase_that_starts_on_a_cancelled_fulfillment_never_leaves(db: Session, order: Order):
    """La carrera de la ADR, reproducida a mano: se cancela justo después de pasar el gate y antes de la frontera."""
    provider = ScriptedFulfilmentProvider()
    fulfillment = create_fulfillment(db, order, provider)
    original = ExternalActionService.begin_call

    def cancel_then_begin(self, action):
        from app.orders import allocation
        from app.orders.fulfilment_domain import FulfillmentStatus

        assert allocation.release_allocation(db, fulfillment.id, to=FulfillmentStatus.CANCELLED)
        db.commit()
        return original(self, action)

    ExternalActionService.begin_call = cancel_then_begin  # type: ignore[method-assign]
    try:
        with pytest.raises(FulfilmentMovedError, match="not READY"):
            service(db, provider).purchase(fulfillment.id, requester=REQUESTER)
    finally:
        ExternalActionService.begin_call = original  # type: ignore[method-assign]
    db.rollback()

    assert provider.calls == [], "the observer refused: nothing was sent for a fulfillment that was cancelled"
    assert reload(db, fulfillment).status == "CANCELLED" and allocated(db, order) == [0, 0]
    action = action_of(db, fulfillment, "purchase")
    assert action.status == ActionStatus.FAILED_CONFIRMED.value, "the operation is closed without effect"
    assert not db.scalars(select(AuditLog).where(AuditLog.action.like("fulfillment.anomaly.%"))).all(), (
        "a cancelled fulfillment is a place where nothing was sent: not an anomaly"
    )


def test_a_request_that_finds_the_operation_already_started_by_another_is_a_409_not_an_internal_error(
    db: Session, order: Order
):
    """Dos peticiones comparten la misma acción `PENDING` (su referencia es la del fulfillment y la fase): gana quien
    la pasa a `CALLING`. La que pierde no es un fallo ni un resultado desconocido: es un 409 y no sale nada de ella."""
    provider = ScriptedFulfilmentProvider()
    fulfillment = create_fulfillment(db, order, provider)
    original = ExternalActionService.execute

    def another_request_started_first(self, action, adapter, payload):
        self.begin_call(action)  # la otra petición pasa la acción a CALLING antes que esta
        return original(self, action, adapter, payload)

    ExternalActionService.execute = another_request_started_first  # type: ignore[method-assign]
    try:
        with pytest.raises(ConflictError, match="already carrying out the purchase"):
            service(db, provider).purchase(fulfillment.id, requester=REQUESTER)
    finally:
        ExternalActionService.execute = original  # type: ignore[method-assign]
    db.rollback()

    assert provider.calls == [], "the request that lost sent nothing"
    assert reload(db, fulfillment).status == "PURCHASING", "the state is the one the other request left"
