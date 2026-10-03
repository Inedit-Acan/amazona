"""Lo que el contrato de M44 promete y ninguna prueba nombraba (Milestone 44, ADR 0028).

Salió de recorrer el ADR y compararlo con las pruebas: cada prueba de abajo cubre una promesa escrita que no tenía quien
la comprobara. Reembolsos que inicia el proveedor (no existía ninguna), sellos de tiempo del futuro, el importe del
pedido como suma exacta con muchos casos, formatos de `customer_ref` que parecen datos personales, lecturas que no
escriben con datos de todos los dominios, la política de fallos del fulfillment (abandonar es una decisión humana, no un
umbral), el recorrido completo de cada tabla de transiciones y que entregar no inventa seguimiento ni transportista.
"""

import datetime
import random
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from fulfilment_test_support import (
    REQUESTER as FULFILMENT_REQUESTER,
)
from fulfilment_test_support import (
    ScriptedFulfilmentProvider,
    create_fulfillment,
    paid_order,
    reload,
    service,
)
from m44_invariants_test_support import check_invariants
from order_test_support import add_product, add_quote, add_supplier, create_order, line, make_engine, session_factory
from payment_test_support import (
    SIMULATION,
    ScriptedPaymentProvider,
    add_order,
    deliver,
    ingress,
    start_attempt,
)
from payment_test_support import reload as reload_payment
from sqlalchemy import event, inspect, select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import ConflictError, ValidationError
from app.db.models.audit import AuditLog
from app.db.models.fulfillment import Fulfillment
from app.db.models.order import Order
from app.db.models.payment import Payment, PaymentEvent, Refund
from app.db.session import get_db
from app.main import app
from app.money.money import Money
from app.orders.domain import ORDER_TRANSITIONS, OrderStatus
from app.orders.errors import OperationNotAllowedError, OutcomeUnknownBlockError
from app.orders.fulfilment_domain import FULFILLMENT_TRANSITIONS, FulfillmentStatus
from app.orders.pagination import OrderCursor
from app.orders.service import OrderService
from app.payments.port import PaymentEventType, WebhookVerificationError


@pytest.fixture()
def db():
    engine = make_engine()
    session = session_factory(engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


# --- B1: pedidos ----------------------------------------------------------------------------------------------------


def test_the_amount_due_is_the_exact_sum_of_the_lines_for_a_hundred_random_orders(db: Session):
    rnd = random.Random(44)
    product = add_product(db)
    for case in range(100):
        spec = [
            (rnd.randint(1, 9), f"{rnd.randint(0, 99999) // 100}.{rnd.randint(0, 99):02d}")
            for _ in range(rnd.randint(1, 6))
        ]
        spec = [(qty, price) for qty, price in spec if Decimal(price) > 0] or [(1, "0.01")]
        order = create_order(
            db, *[line(product, quantity=q, unit_price=p) for q, p in spec], customer_ref=f"sim_sum_{case}"
        )

        expected = sum((Decimal(price) * qty for qty, price in spec), Decimal(0))

        db.refresh(order)
        assert isinstance(order.amount_due, Decimal), "money is stored as a decimal, never as a float"
        assert order.amount_due == expected, (case, spec)
        assert sum((item.line_total for item in order.items), Decimal(0)) == order.amount_due
    assert check_invariants(db) == []


@pytest.mark.parametrize(
    "customer_ref",
    [
        "ana.garcia@example.com",
        "a@b.c",
        "Ana García",
        "Ana",  # sin el prefijo sim_ en una simulación
        "+34 600 000 000",
        "600000000 ",
        "Calle Mayor 1",
        "sim_ana garcia",
        "sim_ana@example.com",
        "sim_" + "x" * 61,  # 65 caracteres
        "",
        " ",
        "sim_\nx",
        "sim_ñandú",
        "sim_;DROP TABLE orders",
        "sim_<script>",
    ],
)
def test_a_customer_reference_that_can_carry_personal_data_is_refused_and_nothing_is_written(db: Session, customer_ref):
    product = add_product(db)

    with pytest.raises(ValidationError):
        create_order(db, line(product, quantity=1, unit_price="1.00"), customer_ref=customer_ref)

    assert db.scalars(select(Order)).all() == []


@pytest.mark.parametrize("customer_ref", ["sim_a", "sim_customer-1", "sim_a.b_c:d", "sim_" + "x" * 60])
def test_an_opaque_reference_is_accepted(db: Session, customer_ref):
    order = create_order(db, line(add_product(db), quantity=1, unit_price="1.00"), customer_ref=customer_ref)

    assert order.customer_ref == customer_ref and order.is_simulated


def test_the_orders_that_exist_never_hold_a_reference_that_looks_personal_after_any_walk(db: Session):
    """Con todo lo que crea el caso de los invariantes, ninguna referencia queda con forma de dato personal."""
    paid_order(db, customer="sim_one")
    paid_order(db, customer="sim_two")

    broken = [item for item in check_invariants(db) if "personal" in item]

    assert broken == []


def test_every_read_route_leaves_the_database_exactly_as_it_found_it_even_with_data_of_every_domain():
    engine = make_engine()
    factory = session_factory(engine)

    def override_get_db():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        with factory() as setup:
            provider = ScriptedFulfilmentProvider()
            order = paid_order(setup, customer="sim_reads")
            fulfillment = create_fulfillment(setup, order, provider)
            service(setup, provider).purchase(fulfillment.id, requester=FULFILMENT_REQUESTER)
            pay = ScriptedPaymentProvider()
            payment = setup.scalars(select(Payment)).one()
            from payment_test_support import REQUESTER

            from app.orders.refunds import RefundService

            refund = RefundService(setup, settings=SIMULATION, provider=pay).request(
                payment.id, amount=Money.of("10.00", "EUR"), reason="customer_request", requester=REQUESTER
            )
            # Un reembolso sin confirmar desde hace más de una hora: la atención se **calcula** al leer.
            setup.execute(
                update(Refund)
                .where(Refund.id == refund.id)
                .values(requested_at=datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=3))
            )
            setup.commit()
            order_id = order.id
        statements: list[str] = []
        event.listen(engine, "before_cursor_execute", lambda conn, cur, stmt, *args: statements.append(stmt))
        client = TestClient(app, raise_server_exceptions=False)

        responses = [
            client.get("/api/orders"),
            client.get(f"/api/orders/{order_id}"),
            client.get("/api/orders", params={"status": "PAID"}),
            client.get("/api/orders", params={"limit": 1}),
            # Seguir un cursor tampoco escribe: uno válido, de un instante futuro, deja pasar el pedido de arriba.
            client.get(
                "/api/orders",
                params={"cursor": OrderCursor(datetime.datetime.now(datetime.UTC), "zzz").encode()},
            ),
        ]

        assert [r.status_code for r in responses] == [200, 200, 200, 200, 200]
        assert [o["id"] for o in responses[4].json()["items"]] == [order_id]
        assert "refund_unconfirmed" in responses[1].json()["attention_reasons"], "the reason is derived at read time"
        writes = [
            s
            for s in statements
            if s.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE", "SAVEPOINT", "RELEASE"))
        ]
        assert writes == [], writes
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_settings, None)
        engine.dispose()


# --- B2: el sello de tiempo del webhook
# -----------------------------------------------------------------------------------


def signed_at(provider, payment, offset_seconds: int, event_id: str):
    stamp = datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=offset_seconds)
    return provider.simulate_event(
        PaymentEventType.PAYMENT_SUCCEEDED,
        provider_payment_ref=payment.provider_payment_ref,
        client_reference=payment.id,
        amount=Money.of(str(payment.amount), payment.currency),
        event_id=event_id,
        timestamp=stamp,
    )


@pytest.mark.parametrize("offset", [400, 3600, 86_400])
def test_a_signature_stamped_in_the_future_beyond_the_tolerance_is_rejected_and_writes_nothing(db: Session, offset):
    provider = ScriptedPaymentProvider()
    payment = start_attempt(db, add_order(db, add_product(db)), provider)
    headers, raw = signed_at(provider, payment, offset, "evt_future")

    with pytest.raises(WebhookVerificationError):
        ingress(db, provider).receive(provider.name, headers, raw)

    assert db.scalars(select(PaymentEvent)).all() == [], "a rejected event leaves no business trace"
    assert reload_payment(db, payment).status == "OPEN" and db.get(Order, payment.order_id).status == "AWAITING_PAYMENT"


@pytest.mark.parametrize("offset", [-240, -30, 0, 30, 240])
def test_a_signature_within_the_tolerance_on_either_side_of_now_is_accepted(db: Session, offset):
    provider = ScriptedPaymentProvider()
    payment = start_attempt(db, add_order(db, add_product(db)), provider)
    headers, raw = signed_at(provider, payment, offset, f"evt_ok_{offset}")

    result = ingress(db, provider).receive(provider.name, headers, raw)

    assert result.outcome == "applied"


@pytest.mark.parametrize("offset", [-400, -3600])
def test_a_signature_stamped_in_the_past_beyond_the_tolerance_is_a_replay_and_is_rejected(db: Session, offset):
    provider = ScriptedPaymentProvider()
    payment = start_attempt(db, add_order(db, add_product(db)), provider)
    headers, raw = signed_at(provider, payment, offset, "evt_past")

    with pytest.raises(WebhookVerificationError):
        ingress(db, provider).receive(provider.name, headers, raw)

    assert db.scalars(select(PaymentEvent)).all() == []


# --- B3: reembolsos que inicia el proveedor
# ---------------------------------------------------------------------------------


def captured(db: Session, provider: ScriptedPaymentProvider) -> Payment:
    payment = start_attempt(db, add_order(db, add_product(db)), provider)
    deliver(db, provider, PaymentEventType.PAYMENT_SUCCEEDED, payment)
    return reload_payment(db, payment)


def dashboard_refund(db: Session, provider, payment: Payment, amount: str, ref: str, event_id: str):
    return deliver(
        db, provider, PaymentEventType.REFUND_SUCCEEDED, payment, amount=amount, refund_ref=ref, event_id=event_id
    )


def test_a_refund_the_provider_made_that_fits_is_recorded_and_counts_against_what_was_captured(db: Session):
    provider = ScriptedPaymentProvider()
    payment = captured(db, provider)

    result = dashboard_refund(db, provider, payment, "20.00", "simref_dashboard_1", "evt_dash_1")

    assert result.outcome == "applied"
    payment = reload_payment(db, payment)
    assert (payment.refund_committed_amount, payment.refunded_amount) == (Decimal("20"), Decimal("20"))
    refund = db.scalars(select(Refund)).one()
    assert refund.origin == "PROVIDER" and refund.status == "SUCCEEDED" and refund.reason == "provider_initiated"
    assert db.scalars(select(AuditLog).where(AuditLog.action == "refund.provider_initiated")).all()
    assert check_invariants(db) == []


def test_a_refund_the_provider_made_that_does_not_fit_is_kept_as_evidence_and_moves_no_total(db: Session):
    provider = ScriptedPaymentProvider()
    payment = captured(db, provider)

    result = dashboard_refund(db, provider, payment, "50.01", "simref_dashboard_big", "evt_dash_big")

    assert result.outcome == "conflict"
    payment = reload_payment(db, payment)
    assert (payment.refund_committed_amount, payment.refunded_amount) == (Decimal(0), Decimal(0))
    assert db.scalars(select(Refund)).all() == []
    stored = db.scalars(select(PaymentEvent).where(PaymentEvent.provider_event_id == "evt_dash_big")).one()
    assert stored.processing_status == "CONFLICT" and stored.amount == Decimal("50.01"), "the evidence is whole"
    assert db.scalars(select(AuditLog).where(AuditLog.action == "refund.provider_refund_does_not_fit")).all()
    assert check_invariants(db) == []


def test_two_refunds_by_the_provider_cannot_together_exceed_what_was_captured(db: Session):
    provider = ScriptedPaymentProvider()
    payment = captured(db, provider)

    first = dashboard_refund(db, provider, payment, "30.00", "simref_dash_a", "evt_dash_a")
    second = dashboard_refund(db, provider, payment, "30.00", "simref_dash_b", "evt_dash_b")

    assert (first.outcome, second.outcome) == ("applied", "conflict")
    payment = reload_payment(db, payment)
    assert payment.refunded_amount == Decimal("30") <= payment.captured_amount
    assert check_invariants(db) == []


def test_the_same_provider_refund_reported_twice_under_two_event_ids_counts_once(db: Session):
    provider = ScriptedPaymentProvider()
    payment = captured(db, provider)

    first = dashboard_refund(db, provider, payment, "20.00", "simref_dash_same", "evt_dash_x")
    second = dashboard_refund(db, provider, payment, "20.00", "simref_dash_same", "evt_dash_y")

    assert first.outcome == "applied" and second.outcome == "stale"
    assert len(db.scalars(select(Refund)).all()) == 1
    assert reload_payment(db, payment).refunded_amount == Decimal("20")
    assert check_invariants(db) == []


def test_a_refund_by_the_provider_after_an_operator_refund_still_respects_the_arithmetic(db: Session):
    from payment_test_support import REQUESTER

    from app.orders.refunds import RefundService

    provider = ScriptedPaymentProvider()
    payment = captured(db, provider)
    RefundService(db, settings=SIMULATION, provider=provider).request(
        payment.id, amount=Money.of("40.00", "EUR"), reason="customer_request", requester=REQUESTER
    )

    result = dashboard_refund(db, provider, payment, "20.00", "simref_dash_over", "evt_dash_over")

    assert result.outcome == "conflict", "40 reserved by an operator refund + 20 would exceed the 50 captured"
    payment = reload_payment(db, payment)
    assert payment.refund_committed_amount == Decimal("40")
    assert check_invariants(db) == []


# --- B4: fulfillment
# ----------------------------------------------------------------------------------------------------


def test_confirmed_failures_pile_up_and_the_fulfillment_never_abandons_itself(db: Session):
    """Abandonar un fulfillment (`FAILED`) es una **decisión humana** (ADR 0028 §6), posible solo tras al menos un fallo
    confirmado: no hay un umbral que lo haga solo. Tres fallos confirmados lo dejan `READY`, con las unidades
    asignadas."""
    order = paid_order(db, customer="sim_failures")
    provider = ScriptedFulfilmentProvider("reject", "reject", "reject")
    fulfillment = create_fulfillment(db, order, provider)

    for attempt in (1, 2, 3):
        assert service(db, provider).purchase(fulfillment.id, requester=FULFILMENT_REQUESTER).status == "READY"
        assert reload(db, fulfillment).failed_attempts == attempt

    assert reload(db, fulfillment).status == "READY", "three confirmed failures do not abandon it by themselves"
    assert check_invariants(db) == []
    assert service(db, provider).fail(fulfillment.id, actor="owner@amazona.local").status == "FAILED"
    assert check_invariants(db) == []


def test_a_person_cannot_abandon_a_fulfillment_that_has_not_failed(db: Session):
    order = paid_order(db, customer="sim_notfailed")
    fulfillment = create_fulfillment(db, order, ScriptedFulfilmentProvider())

    with pytest.raises(ConflictError, match="has not failed"):
        service(db, ScriptedFulfilmentProvider()).fail(fulfillment.id, actor="owner@amazona.local")


def test_delivering_does_not_invent_a_tracking_reference_or_a_carrier(db: Session):
    order = paid_order(db, customer="sim_tracking")
    provider = ScriptedFulfilmentProvider()
    fulfillment = create_fulfillment(db, order, provider)
    assert fulfillment.tracking_reference is None and fulfillment.shipped_at is None
    service(db, provider).purchase(fulfillment.id, requester=FULFILMENT_REQUESTER)
    assert reload(db, fulfillment).tracking_reference is None, "nothing shipped, no tracking"
    shipped = service(db, provider).ship(fulfillment.id, requester=FULFILMENT_REQUESTER)
    tracking = shipped.tracking_reference
    assert tracking and tracking.startswith("simtrk_"), "the reference is the one the provider answered"

    delivered = service(db, provider).complete(fulfillment.id, actor="owner@amazona.local")

    assert delivered.tracking_reference == tracking, "delivering did not touch it"
    assert delivered.completed_by == "owner@amazona.local", "the delivery is a person's confirmation"
    columns = {column["name"] for column in inspect(db.get_bind()).get_columns("fulfillments")}
    assert not columns & {"carrier", "carrier_name", "carrier_id", "tracking_url", "eta", "promised_at"}, columns


def force(db: Session, fulfillment: Fulfillment, status: str, *, failed: int = 0) -> None:
    """Deja el fulfillment en `status` con las columnas que sus restricciones exigen (solo para probar negativas)."""
    now = datetime.datetime.now(datetime.UTC)
    values: dict = {"status": status, "failed_attempts": failed, "unknown_phase": None}
    if status in ("PURCHASED", "SHIPPING", "SHIPPED", "COMPLETED"):
        values["purchased_at"] = now
    if status in ("SHIPPED", "COMPLETED"):
        values["shipped_at"] = now
    if status == "COMPLETED":
        values.update(completed_at=now, completed_by="owner@amazona.local", closed_at=now)
    if status == "UNKNOWN_OUTCOME":
        values["unknown_phase"] = "purchase"
    if status in ("CANCELLED", "FAILED"):
        values["closed_at"] = now
    db.execute(update(Fulfillment).where(Fulfillment.id == fulfillment.id).values(**values))
    db.commit()


ALLOWED = {
    # operación → (estados desde los que se puede, comprobación extra)
    "purchase": {"READY"},
    "ship": {"PURCHASED"},
    "complete": {"SHIPPED"},
    "cancel": {"READY"},
    "fail": {"READY"},
}


@pytest.mark.parametrize("status", [s.value for s in FulfillmentStatus])
@pytest.mark.parametrize("operation", list(ALLOWED))
def test_every_operation_is_refused_from_every_state_that_does_not_allow_it_and_changes_nothing(
    db: Session, status, operation
):
    order = paid_order(db, customer=f"sim_{operation}_{status.lower()}")
    provider = ScriptedFulfilmentProvider()
    fulfillment = create_fulfillment(db, order, provider)
    force(db, fulfillment, status, failed=1)  # con un fallo previo: `fail` solo se permite desde READY y tras fallar
    calls = len(provider.calls)
    service_ = service(db, provider)

    def act():
        if operation == "purchase":
            return service_.purchase(fulfillment.id, requester=FULFILMENT_REQUESTER)
        if operation == "ship":
            return service_.ship(fulfillment.id, requester=FULFILMENT_REQUESTER)
        if operation == "complete":
            return service_.complete(fulfillment.id, actor="owner@amazona.local")
        if operation == "cancel":
            return service_.cancel(fulfillment.id, actor="owner@amazona.local")
        return service_.fail(fulfillment.id, actor="owner@amazona.local")

    if status in ALLOWED[operation]:
        act()  # una operación permitida se ejecuta (y deja el estado que le toca)
        assert reload(db, fulfillment).status != status or operation in ("purchase", "ship")
        return
    before = reload(db, fulfillment)
    snapshot = (before.status, before.failed_attempts, before.unknown_phase)

    with pytest.raises((ConflictError, OutcomeUnknownBlockError, OperationNotAllowedError)):
        act()

    after = reload(db, fulfillment)
    assert (after.status, after.failed_attempts, after.unknown_phase) == snapshot, "a refused operation changes nothing"
    assert len(provider.calls) == calls, "and nothing is sent to the provider"


# --- Alcanzabilidad de las tablas de transición
# ----------------------------------------------------------------------------


def reachable(table: dict, start) -> set:
    seen, frontier = {start}, [start]
    while frontier:
        for target in table[frontier.pop()]:
            if target not in seen:
                seen.add(target)
                frontier.append(target)
    return seen


def test_every_fulfillment_state_can_be_reached_and_every_transition_leads_somewhere_defined():
    assert set(FULFILLMENT_TRANSITIONS) == set(FulfillmentStatus), "every state has a row in the table"
    assert reachable(FULFILLMENT_TRANSITIONS, FulfillmentStatus.READY) == set(FulfillmentStatus), "no unreachable state"
    for source, targets in FULFILLMENT_TRANSITIONS.items():
        assert targets <= set(FulfillmentStatus)
        assert source not in targets, f"{source} cannot move to itself"
    terminal = {s for s, targets in FULFILLMENT_TRANSITIONS.items() if not targets}
    assert terminal == {FulfillmentStatus.COMPLETED, FulfillmentStatus.FAILED, FulfillmentStatus.CANCELLED}


def test_every_order_state_can_be_reached_and_paid_is_only_reached_from_awaiting_payment():
    assert set(ORDER_TRANSITIONS) == set(OrderStatus)
    assert reachable(ORDER_TRANSITIONS, OrderStatus.AWAITING_PAYMENT) == set(OrderStatus)
    entering_paid = {s for s, targets in ORDER_TRANSITIONS.items() if OrderStatus.PAID in targets}
    assert entering_paid == {OrderStatus.AWAITING_PAYMENT}
    assert not ORDER_TRANSITIONS[OrderStatus.COMPLETED] and not ORDER_TRANSITIONS[OrderStatus.CANCELLED]


def test_an_order_with_a_live_payment_attempt_or_captured_money_is_never_cancelled_as_unpaid(db: Session):
    provider = ScriptedPaymentProvider()
    live = add_order(db, add_product(db, name="live"), customer="sim_live")
    start_attempt(db, live, provider)
    with pytest.raises(ConflictError):
        OrderService(db, settings=SIMULATION).cancel(live.id, actor="owner@amazona.local")
    paid = add_order(db, add_product(db, name="paid"), customer="sim_paid")
    deliver(db, provider, PaymentEventType.PAYMENT_SUCCEEDED, start_attempt(db, paid, provider))
    with pytest.raises(ConflictError):
        OrderService(db, settings=SIMULATION).cancel(paid.id, actor="owner@amazona.local")

    assert db.get(Order, live.id).status == "AWAITING_PAYMENT" and db.get(Order, paid.id).status == "PAID"
    assert check_invariants(db) == []


def test_an_order_without_any_payment_attempt_can_be_cancelled_and_is_then_terminal(db: Session):
    order = create_order(db, line(add_product(db), quantity=1, unit_price="9.99"), customer_ref="sim_cancel")

    cancelled = OrderService(db, settings=SIMULATION).cancel(order.id, actor="owner@amazona.local")

    assert cancelled.status == "CANCELLED" and cancelled.cancelled_at is not None and cancelled.paid_at is None
    with pytest.raises(ConflictError):
        OrderService(db, settings=SIMULATION).cancel(order.id, actor="owner@amazona.local")
    assert check_invariants(db) == []
    add_quote  # noqa: B018 - importado para que el módulo de apoyo no parezca sin uso
    add_supplier  # noqa: B018


# --- El cuerpo bruto de un webhook no se guarda
# ----------------------------------------------------------------------------


def test_an_event_keeps_a_whitelist_of_fields_and_a_hash_never_the_raw_body(db: Session):
    provider = ScriptedPaymentProvider()
    payment = start_attempt(db, add_order(db, add_product(db)), provider)
    headers, raw = provider.simulate_event(
        PaymentEventType.PAYMENT_SUCCEEDED,
        provider_payment_ref=payment.provider_payment_ref,
        client_reference=payment.id,
        amount=Money.of("50.00", "EUR"),
        event_id="evt_whitelist",
    )

    ingress(db, provider).receive(provider.name, headers, raw)

    stored = db.scalars(select(PaymentEvent)).one()
    everything = " ".join(str(getattr(stored, column.name)) for column in PaymentEvent.__table__.columns)
    assert raw.decode("utf-8") not in everything, "the raw body is nowhere in the row"
    assert stored.data is None or set(stored.data) <= {"failure_code", "livemode", "attempt", "reason"}
    assert len(stored.payload_hash) == 64


def test_an_order_that_holds_captured_money_but_is_not_paid_cannot_be_cancelled_as_if_unpaid(db: Session):
    """Una captura de un importe distinto deja el pedido sin pagar **y** con dinero cobrado (ADR 0028 §4): cancelarlo lo
    dejaría huérfano. Lo frena la comprobación de dinero capturado, no la tabla de transiciones (el pedido sigue
    `AWAITING_PAYMENT`), y por eso esta prueba existe: la mutación que la quita sobrevivía a todas las demás."""
    provider = ScriptedPaymentProvider()
    order = add_order(db, add_product(db), customer="sim_mismatch")
    payment = start_attempt(db, order, provider)
    deliver(db, provider, PaymentEventType.PAYMENT_SUCCEEDED, payment, amount="49.00")

    payment = reload_payment(db, payment)
    assert payment.status == "CAPTURE_MISMATCH" and db.get(Order, order.id).status == "AWAITING_PAYMENT"
    with pytest.raises(ConflictError, match="money captured"):
        OrderService(db, settings=SIMULATION).cancel(order.id, actor="owner@amazona.local")

    assert db.get(Order, order.id).status == "AWAITING_PAYMENT" and db.get(Order, order.id).cancelled_at is None
    assert check_invariants(db) == []
