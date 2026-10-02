"""Cobros y webhook por HTTP (Milestone 44, ADR 0028 §1, §2 y §9).

Las rutas se usan de verdad (TestClient). El webhook **no lleva el token de nadie**: se autentica por la firma de su
cuerpo, así que sigue funcionando cuando el despliegue exige identidad en todo lo demás. El simulador firma con la
clave efímera de este proceso, que es la misma que usa la ruta.
"""

import copy
import json

import pytest
from fastapi.testclient import TestClient
from order_test_support import add_product, make_engine, session_factory
from sqlalchemy import select

from app.core.config import Settings, get_settings
from app.db.models.payment import Payment, PaymentEvent
from app.db.session import get_db
from app.main import app
from app.money.money import Money
from app.payments.port import PaymentEventType
from app.payments.providers.simulated import PROVIDER_NAME, SIGNATURE_HEADER, SimulatedPaymentProvider

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


def new_order(client: TestClient, product_id: str, key: str = "order-1") -> dict:
    body = copy.deepcopy(BODY)
    body["lines"][0]["product_id"] = product_id
    response = client.post("/api/orders", json=body, headers={"Idempotency-Key": key})
    assert response.status_code == 201, response.text
    return response.json()


def open_payment(client: TestClient, order_id: str, key: str = "pay-1"):
    return client.post(f"/api/orders/{order_id}/payments", headers={"Idempotency-Key": key})


def signed_event(event_type: PaymentEventType, payment: dict, *, amount: str = "50.00", event_id: str | None = None):
    provider = SimulatedPaymentProvider(operations={})
    headers, raw = provider.simulate_event(
        event_type,
        provider_payment_ref=payment["provider_payment_ref"],
        client_reference=payment["id"],
        amount=Money.of(amount, "EUR") if event_type is PaymentEventType.PAYMENT_SUCCEEDED else None,
        event_id=event_id,
    )
    return headers, raw


def post_event(client: TestClient, headers: dict, raw: bytes, provider: str = PROVIDER_NAME):
    return client.post(f"/api/payments/webhooks/{provider}", content=raw, headers=headers)


# --- Abrir un intento de cobro -----------------------------------------------------------------------------------


def test_opening_a_charge_needs_an_idempotency_key_even_in_a_simulation(env):
    client, factory, product_id = env
    order = new_order(client, product_id)

    response = client.post(f"/api/orders/{order['id']}/payments")

    assert response.status_code == 428
    with factory() as db:
        assert db.scalars(select(Payment)).all() == []


def test_a_charge_is_opened_and_the_order_shows_the_attempt_but_is_not_paid(env):
    client, _, product_id = env
    order = new_order(client, product_id)

    response = open_payment(client, order["id"])

    assert response.status_code == 201, response.text
    payment = response.json()
    assert payment["status"] == "OPEN" and payment["attempt_number"] == 1
    assert payment["amount"] == {"amount": "50.0000", "currency": "EUR"}
    assert payment["captured_amount"]["amount"] == "0.0000"
    shown = client.get(f"/api/orders/{order['id']}").json()
    assert shown["status"] == "AWAITING_PAYMENT" and [p["id"] for p in shown["payments"]] == [payment["id"]]


def test_the_same_key_is_the_same_intention_and_a_new_key_while_the_attempt_lives_is_refused(env):
    client, factory, product_id = env
    order = new_order(client, product_id)
    first = open_payment(client, order["id"], key="pay-1")

    again = open_payment(client, order["id"], key="pay-1")
    other = open_payment(client, order["id"], key="pay-2")

    assert again.status_code == 201 and again.json() == first.json()
    assert again.headers.get("Idempotency-Replayed") == "true"
    assert other.status_code == 409 and "still OPEN" in other.json()["detail"]
    with factory() as db:
        assert len(db.scalars(select(Payment)).all()) == 1


def test_after_a_failed_attempt_a_new_key_is_a_new_attempt(env):
    client, _, product_id = env
    order = new_order(client, product_id)
    first = open_payment(client, order["id"], key="pay-1").json()
    headers, raw = signed_event(PaymentEventType.PAYMENT_FAILED, first)
    assert post_event(client, headers, raw).status_code == 200

    second = open_payment(client, order["id"], key="pay-2")

    assert second.status_code == 201 and second.json()["attempt_number"] == 2 and second.json()["status"] == "OPEN"
    replay = open_payment(client, order["id"], key="pay-1")
    assert replay.json()["id"] == first["id"], "the first key still means the first intention"


def test_charging_an_unknown_order_is_a_404_and_the_key_serves_again(env):
    client, _, _ = env

    assert open_payment(client, "missing", key="pay-x").status_code == 404


# --- El webhook ----------------------------------------------------------------------------------------------------


def test_a_verified_webhook_pays_the_order(env):
    client, _, product_id = env
    order = new_order(client, product_id)
    payment = open_payment(client, order["id"]).json()
    headers, raw = signed_event(PaymentEventType.PAYMENT_SUCCEEDED, payment)

    response = post_event(client, headers, raw)

    assert response.status_code == 200 and response.json() == {"status": "applied", "duplicate": False}
    shown = client.get(f"/api/orders/{order['id']}").json()
    assert shown["status"] == "PAID" and shown["paid_at"] is not None
    assert shown["payments"][0]["status"] == "SUCCEEDED" and shown["attention_required"] is False


def test_a_repeated_webhook_is_a_200_that_changes_nothing(env):
    client, factory, product_id = env
    order = new_order(client, product_id)
    payment = open_payment(client, order["id"]).json()
    headers, raw = signed_event(PaymentEventType.PAYMENT_SUCCEEDED, payment, event_id="evt_http")
    post_event(client, headers, raw)

    again = post_event(client, headers, raw)

    assert again.status_code == 200 and again.json() == {"status": "applied", "duplicate": True}
    with factory() as db:
        assert len(db.scalars(select(PaymentEvent)).all()) == 1


def test_an_event_that_cannot_be_verified_is_a_400_with_a_fixed_message_and_writes_nothing(env):
    client, factory, product_id = env
    order = new_order(client, product_id)
    payment = open_payment(client, order["id"]).json()
    headers, raw = signed_event(PaymentEventType.PAYMENT_SUCCEEDED, payment)

    tampered = post_event(client, headers, raw + b" ")
    unsigned = post_event(client, {}, raw)
    garbage = post_event(client, {SIGNATURE_HEADER: "t=1,v1=zz"}, raw)

    for response in (tampered, unsigned, garbage):
        assert response.status_code == 400 and response.json() == {"detail": "invalid webhook"}
    with factory() as db:
        assert db.scalars(select(PaymentEvent)).all() == []
    assert client.get(f"/api/orders/{order['id']}").json()["status"] == "AWAITING_PAYMENT"


def test_the_same_event_id_with_other_content_is_a_409(env):
    client, _, product_id = env
    order = new_order(client, product_id)
    payment = open_payment(client, order["id"]).json()
    first = signed_event(PaymentEventType.PAYMENT_SUCCEEDED, payment, event_id="evt_same")
    other = signed_event(PaymentEventType.PAYMENT_SUCCEEDED, payment, amount="49.00", event_id="evt_same")
    post_event(client, *first)

    response = post_event(client, *other)

    assert response.status_code == 409
    assert client.get(f"/api/orders/{order['id']}").json()["payments"][0]["captured_amount"]["amount"] == "50.0000"


def test_a_provider_that_is_not_enabled_is_a_404(env):
    client, _, product_id = env
    order = new_order(client, product_id)
    payment = open_payment(client, order["id"]).json()
    headers, raw = signed_event(PaymentEventType.PAYMENT_SUCCEEDED, payment)

    assert post_event(client, headers, raw, provider="some-real-gateway").status_code == 404


def test_an_oversized_body_is_a_413(env):
    client, _, _ = env

    response = post_event(client, {"content-type": "application/json"}, b"x" * (64 * 1024 + 1))

    assert response.status_code == 413


def test_the_webhook_needs_no_token_even_where_everything_else_demands_one(env):
    """Se autentica por la firma del cuerpo: un despliegue que exige identidad no la pide aquí."""
    client, _, product_id = env
    order = new_order(client, product_id)
    payment = open_payment(client, order["id"]).json()
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None, require_auth=True)
    headers, raw = signed_event(PaymentEventType.PAYMENT_SUCCEEDED, payment)

    assert client.get("/api/orders").status_code == 401, "the rest of the API does ask for identity"
    assert post_event(client, headers, raw).status_code == 200


def test_a_forged_event_for_the_simulated_provider_cannot_be_signed_from_outside_the_process(env):
    client, factory, product_id = env
    order = new_order(client, product_id)
    payment = open_payment(client, order["id"]).json()
    outsider = SimulatedPaymentProvider(signing_key=b"an outsider guessing a key......!", operations={})
    headers, raw = outsider.simulate_event(
        PaymentEventType.PAYMENT_SUCCEEDED,
        provider_payment_ref=payment["provider_payment_ref"],
        client_reference=payment["id"],
        amount=Money.of("50.00", "EUR"),
    )

    response = post_event(client, headers, raw)

    assert response.status_code == 400
    assert client.get(f"/api/orders/{order['id']}").json()["status"] == "AWAITING_PAYMENT"


def test_no_route_lets_the_browser_say_a_payment_happened(env):
    spec = app.openapi()
    writes = {
        (method.upper(), path)
        for path, item in spec["paths"].items()
        if path.startswith(("/api/orders", "/api/payments"))
        for method in item
        if method != "get"
    }

    assert writes == {
        ("POST", "/api/orders"),
        ("POST", "/api/orders/{order_id}/payments"),
        ("POST", "/api/orders/{order_id}/refunds"),
        ("POST", "/api/orders/{order_id}/cancel"),
        ("POST", "/api/payments/webhooks/{provider}"),
    }
    for path, item in spec["paths"].items():
        if path.startswith("/api/orders"):
            for method, operation in item.items():
                body = operation.get("requestBody")
                if body:
                    schema = json.dumps(body)
                    assert "paid" not in schema and "captured" not in schema, (
                        f"{method} {path} could set a payment state"
                    )


# --- Cancelar -------------------------------------------------------------------------------------------------------


def test_cancelling_an_unpaid_order_and_repeating_it(env):
    client, _, product_id = env
    order = new_order(client, product_id)

    first = client.post(f"/api/orders/{order['id']}/cancel")
    again = client.post(f"/api/orders/{order['id']}/cancel")

    assert first.status_code == 200 and first.json()["status"] == "CANCELLED"
    assert again.status_code == 409, "repeating a state transition is a conflict"


def test_an_order_with_a_live_charge_cannot_be_cancelled(env):
    client, _, product_id = env
    order = new_order(client, product_id)
    open_payment(client, order["id"])

    response = client.post(f"/api/orders/{order['id']}/cancel")

    assert response.status_code == 409 and "still alive" in response.json()["detail"]
