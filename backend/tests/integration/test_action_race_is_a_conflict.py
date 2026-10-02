"""Perder una carrera por una acción externa es un 409 de dominio, nunca un error interno (M45, P2-1).

El barrido de huérfanas (`reconcile-actions`) y la petición que abre un cobro o pide un reembolso pueden coincidir:
la petición ya confirmó su operación `PENDING`, y justo antes de empezar la llamada el barrido la cierra («nunca
salió»). Entonces `begin_call` lanza `ExternalActionStateError`. Esa excepción no tenía tratamiento HTTP salvo en
fulfillment: en cobros y reembolsos subía como un 500.

La carrera se reproduce sin azar: el barrido se ejecuta **desde otra sesión** en el instante exacto en que la petición
llama a `begin_call`, de modo que la petición ve su acción como `PENDING` (la copia que tiene) y pierde el
compare-and-set. Se prueba en SQLite y en un PostgreSQL de verdad (dos conexiones reales).

Lo que se afirma:

- la petición recibe un `ConflictError` (409) y no una `ExternalActionStateError` (500);
- nada salió hacia el proveedor, y el dominio queda como lo dejó el barrido (`FAILED`/`not_sent`, importe liberado);
- la clave de idempotencia **se libera** (el 409 es una negativa del dominio): se puede repetir con la misma clave;
- el tratamiento es **estrecho**: un error inesperado sigue siendo un error, no se disfraza de conflicto.
"""

import copy
import datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from order_test_support import add_product, make_engine, session_factory
from payment_test_support import (
    REQUESTER,
    SIMULATION,
    ScriptedPaymentProvider,
    add_order,
    deliver,
    payments_of,
    refunds,
    reload,
    start_attempt,
)
from pg_test_support import ephemeral_postgres
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.actions.contract import ActionStatus
from app.actions.service import ExternalActionService, ExternalActionStateError
from app.core.config import get_settings
from app.core.errors import ConflictError
from app.db.models.external_action import ExternalAction
from app.db.models.idempotency_record import IdempotencyRecord
from app.db.models.order import Order
from app.db.models.payment import Payment
from app.db.session import get_db
from app.main import app
from app.money.money import Money
from app.orders.errors import OperationNotAllowedError
from app.orders.payment_attempts import PaymentAttemptService
from app.orders.refunds import RefundService
from app.payments.port import OPERATION_OPEN, PaymentEventType
from app.payments.projection import payment_reference
from app.payments.providers.simulated import PROVIDER_NAME, SimulatedPaymentProvider
from app.pipeline.kill_switch import PipelineKillSwitchService

EVERYTHING_PENDING_IS_OLD = datetime.timedelta(seconds=-1)


@pytest.fixture(params=["sqlite", "postgres"])
def engine(request):
    if request.param == "sqlite":
        built = make_engine()
        try:
            yield built
        finally:
            built.dispose()
    else:
        with ephemeral_postgres() as built:
            yield built


@pytest.fixture()
def factory(engine) -> sessionmaker:
    return session_factory(engine)


@pytest.fixture()
def db(factory):
    with factory() as session:
        yield session


@pytest.fixture()
def order(db: Session) -> Order:
    return add_order(db, add_product(db))  # 2 × 25.00 = 50.00


def reconciler_closes_it_first(monkeypatch, factory, *, then=None):
    """Justo antes de que `begin_call` empiece, el barrido (otra sesión) libera la acción `PENDING` de esta petición."""
    original = ExternalActionService.begin_call

    def sweep_then_begin(self, action):
        with factory() as other:
            swept = ExternalActionService(other).reconcile_interrupted(older_than=EVERYTHING_PENDING_IS_OLD)
        assert len(swept["released"]) == 1, "the sweep must have taken exactly the action of this request"
        if then is not None:
            then()
        return original(self, action)

    monkeypatch.setattr(ExternalActionService, "begin_call", sweep_then_begin)


def captured(db: Session, order: Order, provider: ScriptedPaymentProvider) -> Payment:
    payment = start_attempt(db, order, provider)
    deliver(db, provider, PaymentEventType.PAYMENT_SUCCEEDED, payment)
    payment = reload(db, payment)
    assert payment.status == "SUCCEEDED"
    return payment


def request_refund(db: Session, payment: Payment, provider, amount: str = "10.00"):
    return RefundService(db, settings=SIMULATION, provider=provider).request(
        payment.id, amount=Money.of(amount, payment.currency), reason="customer_request", requester=REQUESTER
    )


# --- Cobros ---------------------------------------------------------------------------------------------------------


def test_a_payment_that_loses_the_race_with_the_sweep_is_a_conflict_and_sends_nothing(
    db: Session, factory, order: Order, monkeypatch
):
    provider = ScriptedPaymentProvider()
    reconciler_closes_it_first(monkeypatch, factory)

    with pytest.raises(ConflictError, match="another process"):
        PaymentAttemptService(db, settings=SIMULATION, provider=provider).start(order.id, requester=REQUESTER)

    assert provider.calls == [], "the request lost the race before the call: nothing was sent"
    payment = payments_of(db, order)[0]
    assert payment.status == "FAILED" and payment.last_failure_code == "not_sent"
    action = db.scalars(select(ExternalAction)).one()
    assert action.status == ActionStatus.FAILED_CONFIRMED.value and action.resolved_by == "reconciler"

    monkeypatch.undo()
    assert start_attempt(db, order, provider).attempt_number == 2, "the slot is free again"


def test_the_kill_switch_answer_survives_a_sweep_that_already_closed_the_unsent_payment(
    db: Session, factory, order: Order, monkeypatch
):
    provider = ScriptedPaymentProvider()

    def turn_the_kill_switch_off():
        PipelineKillSwitchService(db).disable(reason="test", actor="owner@amazona.local", correlation_id="c-ks")

    reconciler_closes_it_first(monkeypatch, factory, then=turn_the_kill_switch_off)

    with pytest.raises(OperationNotAllowedError, match="kill switch"):
        PaymentAttemptService(db, settings=SIMULATION, provider=provider).start(order.id, requester=REQUESTER)

    assert provider.calls == []
    payment = payments_of(db, order)[0]
    assert payment.status == "FAILED" and payment.last_failure_code == "not_sent"


def test_an_unexpected_error_opening_a_payment_is_not_disguised_as_a_conflict(db: Session, order: Order, monkeypatch):
    def explode(self, action, adapter, payload):
        raise RuntimeError("a bug, not a race")

    monkeypatch.setattr(ExternalActionService, "execute", explode)

    with pytest.raises(RuntimeError, match="a bug"):
        start_attempt(db, order, ScriptedPaymentProvider())


# --- Reembolsos -----------------------------------------------------------------------------------------------------


def test_a_refund_that_loses_the_race_with_the_sweep_is_a_conflict_and_sets_nothing_aside(
    db: Session, factory, order: Order, monkeypatch
):
    provider = ScriptedPaymentProvider()
    payment = captured(db, order, provider)
    calls = len(provider.calls)
    reconciler_closes_it_first(monkeypatch, factory)

    with pytest.raises(ConflictError, match="another process"):
        request_refund(db, payment, provider)

    assert len(provider.calls) == calls, "nothing was sent to the provider"
    refund = refunds(db)[0]
    assert refund.status == "FAILED" and refund.failure_code == "not_sent"
    payment = reload(db, payment)
    assert Decimal(str(payment.refund_committed_amount)) == 0 and Decimal(str(payment.refunded_amount)) == 0

    monkeypatch.undo()
    assert request_refund(db, payment, provider).status == "SENDING", "the amount can be asked for again"


def test_the_kill_switch_answer_survives_a_sweep_that_already_released_the_unsent_refund(
    db: Session, factory, order: Order, monkeypatch
):
    provider = ScriptedPaymentProvider()
    payment = captured(db, order, provider)
    calls = len(provider.calls)

    def turn_the_kill_switch_off():
        PipelineKillSwitchService(db).disable(reason="test", actor="owner@amazona.local", correlation_id="c-ks")

    reconciler_closes_it_first(monkeypatch, factory, then=turn_the_kill_switch_off)

    with pytest.raises(OperationNotAllowedError, match="kill switch"):
        request_refund(db, payment, provider)

    assert len(provider.calls) == calls
    refund = refunds(db)[0]
    assert refund.status == "FAILED" and refund.failure_code == "not_sent"
    assert Decimal(str(reload(db, payment).refund_committed_amount)) == 0


def test_an_unexpected_error_asking_for_a_refund_is_not_disguised_as_a_conflict(
    db: Session, order: Order, monkeypatch
):
    provider = ScriptedPaymentProvider()
    payment = captured(db, order, provider)

    def explode(self, action, adapter, payload):
        raise RuntimeError("a bug, not a race")

    monkeypatch.setattr(ExternalActionService, "execute", explode)

    with pytest.raises(RuntimeError, match="a bug"):
        request_refund(db, payment, provider)


def test_the_state_error_itself_is_what_the_race_raises_so_the_tests_above_prove_the_translation(
    db: Session, factory, order: Order, monkeypatch
):
    """Control: sin traducción, la carrera de estas pruebas produce exactamente `ExternalActionStateError`."""
    reconciler_closes_it_first(monkeypatch, factory)
    service = ExternalActionService(db)
    provider = ScriptedPaymentProvider()
    payment = Payment(
        order_id=order.id,
        attempt_number=1,
        provider=provider.name,
        status="REQUESTED",
        amount=order.amount_due,
        currency=order.currency,
        correlation_id="c-control",
    )
    db.add(payment)
    db.flush()
    payload = {"payment_id": payment.id, "order_id": order.id, "amount": "50.00", "currency": "EUR"}
    action = service.open(
        reference=payment_reference(payment.id),
        adapter=provider,
        operation=OPERATION_OPEN,
        amount=None,
        payload=payload,
        correlation_id="c-control",
    )
    db.commit()

    with pytest.raises(ExternalActionStateError):
        service.execute(action, provider, payload)


# --- Por HTTP: un 409 con la clave liberada, nunca un 500 ------------------------------------------------------------

BODY = {
    "customer_ref": "sim_http_customer",
    "market": "eu",
    "lines": [{"product_id": "", "quantity": 2, "unit_price": {"amount": "25.00", "currency": "EUR"}}],
}


@pytest.fixture()
def http():
    sqlite_engine = make_engine()
    sqlite_factory = session_factory(sqlite_engine)

    def override_get_db():
        session = sqlite_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    with sqlite_factory() as db:
        product_id = add_product(db).id
    try:
        yield TestClient(app, raise_server_exceptions=False), sqlite_factory, product_id
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_settings, None)
        sqlite_engine.dispose()


def new_order(client: TestClient, product_id: str) -> dict:
    body = copy.deepcopy(BODY)
    body["lines"][0]["product_id"] = product_id
    return client.post("/api/orders", json=body, headers={"Idempotency-Key": "order-1"}).json()


def test_over_http_losing_the_race_opening_a_payment_is_a_409_and_the_key_serves_again(http, monkeypatch):
    client, factory, product_id = http
    order = new_order(client, product_id)
    reconciler_closes_it_first(monkeypatch, factory)

    lost = client.post(f"/api/orders/{order['id']}/payments", headers={"Idempotency-Key": "pay-1"})

    assert lost.status_code == 409, lost.text
    assert "another process" in lost.json()["detail"]
    with factory() as db:
        record = db.scalars(select(IdempotencyRecord).where(IdempotencyRecord.key == "pay-1")).all()
        assert record == [], "a domain refusal releases the key: it is not an unknown outcome"

    monkeypatch.undo()
    retried = client.post(f"/api/orders/{order['id']}/payments", headers={"Idempotency-Key": "pay-1"})
    assert retried.status_code == 201, retried.text
    assert retried.json()["attempt_number"] == 2


def test_over_http_losing_the_race_asking_for_a_refund_is_a_409_and_the_key_serves_again(http, monkeypatch):
    client, factory, product_id = http
    order = new_order(client, product_id)
    payment = client.post(f"/api/orders/{order['id']}/payments", headers={"Idempotency-Key": "pay-1"}).json()
    headers, raw = SimulatedPaymentProvider(operations={}).simulate_event(
        PaymentEventType.PAYMENT_SUCCEEDED,
        provider_payment_ref=payment["provider_payment_ref"],
        client_reference=payment["id"],
        amount=Money.of("50.00", "EUR"),
    )
    assert client.post(f"/api/payments/webhooks/{PROVIDER_NAME}", content=raw, headers=headers).status_code == 200
    reconciler_closes_it_first(monkeypatch, factory)
    body = {"payment_id": payment["id"], "amount": {"amount": "10.00", "currency": "EUR"}, "reason": "customer_request"}

    lost = client.post(f"/api/orders/{order['id']}/refunds", json=body, headers={"Idempotency-Key": "refund-1"})

    assert lost.status_code == 409, lost.text
    assert "another process" in lost.json()["detail"]
    with factory() as db:
        assert db.scalars(select(IdempotencyRecord).where(IdempotencyRecord.key == "refund-1")).all() == []

    monkeypatch.undo()
    retried = client.post(f"/api/orders/{order['id']}/refunds", json=body, headers={"Idempotency-Key": "refund-1"})
    assert retried.status_code == 201, retried.text
