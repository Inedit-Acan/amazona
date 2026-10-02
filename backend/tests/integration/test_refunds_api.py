"""Reembolsos por HTTP (Milestone 44, ADR 0028 §5 y §9).

La ruta ordena una devolución; **nunca** da por devuelto el dinero: eso lo confirma un hecho verificado que entra por la
misma puerta que el webhook de cobro. Solo OWNER y ADMIN pueden pedirla (el inventario de autorización de
`test_api_authorization.py` lo hace cumplir rol por rol).
"""

import copy

import pytest
from fastapi.testclient import TestClient
from order_test_support import add_product, make_engine, session_factory
from sqlalchemy import select

from app.core.config import get_settings
from app.db.models.payment import Payment, PaymentEvent, Refund
from app.db.session import get_db
from app.main import app
from app.money.money import Money
from app.payments.port import PaymentEventType
from app.payments.providers.simulated import PROVIDER_NAME, SimulatedPaymentProvider

BODY = {
    "customer_ref": "sim_http_customer",
    "market": "eu",
    "lines": [{"product_id": "", "quantity": 2, "unit_price": {"amount": "25.00", "currency": "EUR"}}],
}


@pytest.fixture()
def env():
    engine = make_engine()
    factory = session_factory(engine)

    def override_get_db():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    with factory() as db:
        product_id = add_product(db).id
    try:
        yield TestClient(app, raise_server_exceptions=False), factory, product_id
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_settings, None)
        engine.dispose()


def paid_order(client: TestClient, product_id: str, key: str = "order-1") -> tuple[dict, dict]:
    body = copy.deepcopy(BODY)
    body["lines"][0]["product_id"] = product_id
    order = client.post("/api/orders", json=body, headers={"Idempotency-Key": key}).json()
    payment = client.post(f"/api/orders/{order['id']}/payments", headers={"Idempotency-Key": f"pay-{key}"}).json()
    headers, raw = SimulatedPaymentProvider(operations={}).simulate_event(
        PaymentEventType.PAYMENT_SUCCEEDED,
        provider_payment_ref=payment["provider_payment_ref"],
        client_reference=payment["id"],
        amount=Money.of("50.00", "EUR"),
    )
    assert client.post(f"/api/payments/webhooks/{PROVIDER_NAME}", content=raw, headers=headers).status_code == 200
    return order, payment


def ask_refund(client, order_id, payment_id, amount="10.00", key="refund-1", reason="customer_request"):
    return client.post(
        f"/api/orders/{order_id}/refunds",
        json={"payment_id": payment_id, "amount": {"amount": amount, "currency": "EUR"}, "reason": reason},
        headers={"Idempotency-Key": key},
    )


def confirm(client, refund: dict, payment: dict, kind=PaymentEventType.REFUND_SUCCEEDED, amount="10.00"):
    headers, raw = SimulatedPaymentProvider(operations={}).simulate_event(
        kind,
        provider_payment_ref=payment["provider_payment_ref"],
        provider_refund_ref=refund["provider_refund_ref"],
        client_reference=refund["id"],
        amount=Money.of(amount, "EUR"),
    )
    return client.post(f"/api/payments/webhooks/{PROVIDER_NAME}", content=raw, headers=headers)


def test_a_refund_needs_an_idempotency_key_even_in_a_simulation(env):
    client, factory, product_id = env
    order, payment = paid_order(client, product_id)

    response = client.post(
        f"/api/orders/{order['id']}/refunds",
        json={"payment_id": payment["id"], "amount": {"amount": "10.00", "currency": "EUR"}, "reason": "other"},
    )

    assert response.status_code == 428
    with factory() as db:
        assert db.scalars(select(Refund)).all() == []


def test_a_refund_is_ordered_and_the_order_shows_it_as_sent_but_not_as_refunded(env):
    client, _, product_id = env
    order, payment = paid_order(client, product_id)

    response = ask_refund(client, order["id"], payment["id"])

    assert response.status_code == 201, response.text
    refund = response.json()
    assert refund["status"] == "SENDING" and refund["origin"] == "OPERATOR" and refund["reason"] == "customer_request"
    assert refund["amount"] == {"amount": "10.0000", "currency": "EUR"}
    shown = client.get(f"/api/orders/{order['id']}").json()
    assert shown["status"] == "PAID" and [r["id"] for r in shown["refunds"]] == [refund["id"]]
    only = shown["payments"][0]
    assert only["refund_committed_amount"]["amount"] == "10.0000" and only["refunded_amount"]["amount"] == "0.0000"


def test_the_same_key_is_the_same_refund_and_another_key_is_another_one(env):
    client, factory, product_id = env
    order, payment = paid_order(client, product_id)
    first = ask_refund(client, order["id"], payment["id"], key="refund-1")

    again = ask_refund(client, order["id"], payment["id"], key="refund-1")
    other = ask_refund(client, order["id"], payment["id"], key="refund-2")

    assert again.status_code == 201 and again.json() == first.json()
    assert again.headers.get("Idempotency-Replayed") == "true"
    assert other.status_code == 201 and other.json()["id"] != first.json()["id"]
    with factory() as db:
        assert len(db.scalars(select(Refund)).all()) == 2


def test_the_key_with_another_amount_is_refused_and_nothing_is_refunded_twice(env):
    client, factory, product_id = env
    order, payment = paid_order(client, product_id)
    ask_refund(client, order["id"], payment["id"], key="refund-1", amount="10.00")

    response = ask_refund(client, order["id"], payment["id"], key="refund-1", amount="20.00")

    assert response.status_code in (409, 422)
    with factory() as db:
        assert len(db.scalars(select(Refund)).all()) == 1


def test_more_than_what_was_captured_is_a_409_that_changes_nothing(env):
    client, factory, product_id = env
    order, payment = paid_order(client, product_id)

    too_much = ask_refund(client, order["id"], payment["id"], amount="50.01", key="refund-big")

    assert too_much.status_code == 409 and "left to refund" in too_much.json()["detail"]
    with factory() as db:
        assert db.scalars(select(Refund)).all() == []
        assert str(db.scalars(select(Payment)).one().refund_committed_amount) in ("0", "0.0000", "0E-4")


def test_the_confirmation_comes_through_the_webhook_and_not_through_the_route(env):
    client, _, product_id = env
    order, payment = paid_order(client, product_id)
    refund = ask_refund(client, order["id"], payment["id"]).json()

    response = confirm(client, refund, payment)

    assert response.status_code == 200 and response.json()["status"] == "applied"
    shown = client.get(f"/api/orders/{order['id']}").json()
    assert shown["refunds"][0]["status"] == "SUCCEEDED" and shown["refunds"][0]["finished_at"] is not None
    assert shown["payments"][0]["refunded_amount"]["amount"] == "10.0000"


def test_a_refund_of_a_payment_that_is_not_of_that_order_is_a_404(env):
    client, _, product_id = env
    order, payment = paid_order(client, product_id)

    assert ask_refund(client, "another-order", payment["id"]).status_code == 404
    assert ask_refund(client, order["id"], "missing-payment").status_code == 404


@pytest.mark.parametrize(
    "amount, reason",
    [("0", "other"), ("-5.00", "other"), ("abc", "other"), ("5.00", "free text with a name")],
)
def test_malformed_refunds_are_rejected(env, amount, reason):
    client, factory, product_id = env
    order, payment = paid_order(client, product_id)

    response = ask_refund(client, order["id"], payment["id"], amount=amount, reason=reason)

    assert response.status_code in (400, 409, 422)
    with factory() as db:
        assert db.scalars(select(Refund)).all() == []


def test_the_body_cannot_say_a_refund_happened(env):
    client, _, product_id = env
    order, payment = paid_order(client, product_id)

    response = client.post(
        f"/api/orders/{order['id']}/refunds",
        json={
            "payment_id": payment["id"],
            "amount": {"amount": "10.00", "currency": "EUR"},
            "reason": "other",
            "status": "SUCCEEDED",
            "refunded_amount": "10.00",
        },
        headers={"Idempotency-Key": "k"},
    )

    assert response.status_code == 422, "extra fields are refused: the browser never states the outcome"


def test_a_refund_changes_no_event_table_row_by_itself(env):
    client, factory, product_id = env
    order, payment = paid_order(client, product_id)
    with factory() as db:
        before = len(db.scalars(select(PaymentEvent)).all())

    ask_refund(client, order["id"], payment["id"])

    with factory() as db:
        assert len(db.scalars(select(PaymentEvent)).all()) == before, "only the provider's facts are events"
