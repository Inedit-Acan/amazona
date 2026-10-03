"""Pedidos por HTTP (Milestone 44, ADR 0028 §9 y §10).

Las rutas se usan de verdad (TestClient). Qué se promete: que crear exige `Idempotency-Key` **siempre** (también en
simulación), que repetir la petición no crea otro pedido, que ninguna ruta acepta un campo «pagado» y que las
lecturas no escriben.
"""

import copy

import pytest
from fastapi.testclient import TestClient
from order_test_support import add_product, make_engine, session_factory
from sqlalchemy import event

from app.core.config import get_settings
from app.db.models.idempotency_record import IdempotencyRecord
from app.db.models.order import Order
from app.db.session import get_db
from app.main import app

BODY = {
    "customer_ref": "sim_api_customer",
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
        product = add_product(db)
    try:
        yield TestClient(app, raise_server_exceptions=False), factory, product.id
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_settings, None)
        engine.dispose()


def body(product_id: str, **overrides) -> dict:
    """Una copia profunda: un test que muta el cuerpo no puede contaminar a los demás."""
    payload = copy.deepcopy(BODY)
    payload["lines"][0]["product_id"] = product_id
    payload.update(overrides)
    return payload


def test_creating_an_order_without_an_idempotency_key_is_refused_even_in_a_simulation(env):
    client, factory, product_id = env

    response = client.post("/api/orders", json=body(product_id))

    assert response.status_code == 428
    with factory() as db:
        assert db.query(Order).count() == 0


def test_an_order_is_created_with_exact_amounts_and_no_personal_data(env):
    client, _, product_id = env

    response = client.post("/api/orders", json=body(product_id), headers={"Idempotency-Key": "k-1"})

    assert response.status_code == 201, response.text
    order = response.json()
    assert order["status"] == "AWAITING_PAYMENT" and order["is_simulated"] is True
    assert order["amount_due"] == {"amount": "50.0000", "currency": "EUR"}
    assert order["customer_ref"] == "sim_api_customer"
    assert order["items"][0]["line_number"] == 1 and order["items"][0]["unit_cost"] is None
    assert order["attention_required"] is False and order["attention_reasons"] == []
    assert not {"email", "name", "phone", "address"} & set(order)


def test_repeating_the_same_request_with_the_same_key_returns_the_same_order(env):
    client, factory, product_id = env
    first = client.post("/api/orders", json=body(product_id), headers={"Idempotency-Key": "k-1"})

    again = client.post("/api/orders", json=body(product_id), headers={"Idempotency-Key": "k-1"})

    assert again.status_code == 201 and again.json() == first.json()
    assert again.headers.get("Idempotency-Replayed") == "true"
    with factory() as db:
        assert db.query(Order).count() == 1


def test_the_same_key_with_another_request_is_a_conflict_and_creates_nothing(env):
    client, factory, product_id = env
    client.post("/api/orders", json=body(product_id), headers={"Idempotency-Key": "k-1"})

    other = client.post(
        "/api/orders", json=body(product_id, customer_ref="sim_someone_else"), headers={"Idempotency-Key": "k-1"}
    )

    assert other.status_code == 409
    with factory() as db:
        assert db.query(Order).count() == 1


def test_a_new_key_is_a_new_order(env):
    client, factory, product_id = env
    client.post("/api/orders", json=body(product_id), headers={"Idempotency-Key": "k-1"})

    second = client.post("/api/orders", json=body(product_id), headers={"Idempotency-Key": "k-2"})

    assert second.status_code == 201
    with factory() as db:
        assert db.query(Order).count() == 2


def test_a_refused_order_frees_its_key(env):
    client, factory, product_id = env
    bad = client.post(
        "/api/orders", json=body(product_id, customer_ref="ana@example.com"), headers={"Idempotency-Key": "k-1"}
    )
    assert bad.status_code in (422, 400)

    good = client.post("/api/orders", json=body(product_id), headers={"Idempotency-Key": "k-1"})

    assert good.status_code == 201, "a refusal did nothing, so the key serves again"
    with factory() as db:
        assert db.query(IdempotencyRecord).count() == 1


@pytest.mark.parametrize(
    "mutation",
    [
        {"customer_ref": "Ana García"},
        {"market": ""},
        {"lines": []},
        {"status": "PAID"},  # ningún campo «pagado»: la forma de la petición lo rechaza
        {"paid": True},
        {"email": "ana@example.com"},
    ],
)
def test_a_body_with_a_forbidden_field_or_a_bad_shape_is_refused(env, mutation):
    client, factory, product_id = env

    response = client.post("/api/orders", json={**body(product_id), **mutation}, headers={"Idempotency-Key": "k-bad"})

    assert response.status_code in (400, 422)
    with factory() as db:
        assert db.query(Order).count() == 0


@pytest.mark.parametrize("amount", ["12.5", 12.5, "-1", "abc", "1e3", ""])
def test_an_amount_must_be_a_decimal_string_never_a_json_number(env, amount):
    client, _, product_id = env
    payload = body(product_id)
    payload["lines"][0]["unit_price"]["amount"] = amount

    response = client.post("/api/orders", json=payload, headers={"Idempotency-Key": "k-amt"})

    if amount == "12.5":
        assert response.status_code == 201
    else:
        assert response.status_code in (400, 422), f"{amount!r} must be refused"


def test_listing_and_reading_orders(env):
    client, _, product_id = env
    created = client.post("/api/orders", json=body(product_id), headers={"Idempotency-Key": "k-1"}).json()

    listed = client.get("/api/orders").json()
    one = client.get(f"/api/orders/{created['id']}")
    paid = client.get("/api/orders", params={"status": "PAID"}).json()

    assert [o["id"] for o in listed["items"]] == [created["id"]] and paid["items"] == []
    assert listed["has_more"] is False and listed["next_cursor"] is None, "a page says whether it is the whole list"
    assert one.status_code == 200 and one.json()["id"] == created["id"]
    assert client.get("/api/orders/missing").status_code == 404
    assert client.get("/api/orders", params={"status": "NOPE"}).status_code == 422


def test_no_route_under_orders_can_mark_an_order_as_paid(env):
    spec = app.openapi()
    routes = {
        (method.upper(), path)
        for path, item in spec["paths"].items()
        if path.startswith("/api/orders")
        for method in item
    }

    assert ("POST", "/api/orders") in routes and ("GET", "/api/orders/{order_id}") in routes
    assert not [route for route in routes if "paid" in route[1] or "pay" in route[1].split("/")[-1:]]
    assert {m for m, _ in routes} <= {"GET", "POST"}, "no PUT/PATCH/DELETE can rewrite an order's state"


def test_getting_orders_writes_nothing(env):
    client, factory, product_id = env
    created = client.post("/api/orders", json=body(product_id), headers={"Idempotency-Key": "k-1"}).json()
    writes: list[str] = []
    with factory() as db:
        event.listen(db.get_bind(), "before_cursor_execute", lambda c, cur, stmt, *a: writes.append(stmt))

    client.get("/api/orders")
    client.get(f"/api/orders/{created['id']}")

    assert not [s for s in writes if s.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))]
