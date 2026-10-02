"""La clave de intención llega al backend y hace lo que el frontend espera de ella (Milestone 44, ADR 0025 y 0028 §9).

El frontend conserva **una** `Idempotency-Key` por intención (`lib/intent-key.ts`) y la reutiliza en cada reintento. Lo
que se prueba aquí es el otro lado del contrato, por HTTP y con carreras reales:

- veinte peticiones iguales a la vez con la misma clave tienen **un** solo efecto (un pedido, una compra), y quien lo
  repite recibe la respuesta original;
- con una clave distinta por petición habría veinte efectos: por eso el cliente no puede inventar una clave por clic;
- los errores de idempotencia llevan un `code` legible por máquina (el cliente no clasifica por el texto de `detail`).
"""

import copy

import pytest
from fastapi.testclient import TestClient
from fulfilment_test_support import paid_order
from http_race_test_support import CLICKS, Api
from order_test_support import add_product, make_engine
from pg_test_support import ephemeral_postgres
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.external_action import ExternalAction
from app.db.models.fulfillment import Fulfillment
from app.db.models.idempotency_record import IdempotencyRecord
from app.db.models.order import Order, OrderItem
from app.main import app
from app.orders.fulfilment import FulfilmentRequestLine, FulfilmentService

BODY = {
    "customer_ref": "sim_intent_customer",
    "market": "eu",
    "lines": [{"product_id": "", "quantity": 2, "unit_price": {"amount": "25.00", "currency": "EUR"}}],
}


def body(product_id: str) -> dict:
    payload = copy.deepcopy(BODY)
    payload["lines"][0]["product_id"] = product_id
    return payload


# --- Veinte clics a la vez ---------------------------------------------------------------------------------------


def test_twenty_identical_clicks_with_the_same_key_create_one_order():
    with ephemeral_postgres() as engine:
        api = Api(engine)
        try:
            with Session(engine) as db:
                product_id = add_product(db).id

            responses = api.together(
                lambda client, _: client.post("/api/orders", json=body(product_id), headers={"Idempotency-Key": "k-1"})
            )

            statuses = sorted(r.status_code for r in responses)
            assert set(statuses) <= {201, 409}, statuses
            created = [r.json() for r in responses if r.status_code == 201]
            assert created and len({o["id"] for o in created}) == 1, "everyone who got an answer got the same order"
            for refused in (r for r in responses if r.status_code == 409):
                assert refused.json()["code"] == "idempotency_in_progress", refused.text
            with Session(engine) as db:
                assert db.scalar(select(func.count()).select_from(Order)) == 1
        finally:
            api.close()


def test_a_retry_after_the_burst_returns_the_original_answer_and_still_one_order():
    with ephemeral_postgres() as engine:
        api = Api(engine)
        try:
            with Session(engine) as db:
                product_id = add_product(db).id
            first = api.together(
                lambda client, _: client.post("/api/orders", json=body(product_id), headers={"Idempotency-Key": "k-1"}),
                count=8,
            )
            original = next(r.json() for r in first if r.status_code == 201)

            retry = TestClient(app).post("/api/orders", json=body(product_id), headers={"Idempotency-Key": "k-1"})

            assert retry.status_code == 201 and retry.json() == original
            assert retry.headers.get("Idempotency-Replayed") == "true"
            with Session(engine) as db:
                assert db.scalar(select(func.count()).select_from(Order)) == 1
        finally:
            api.close()


def test_without_a_held_key_twenty_clicks_would_be_twenty_orders():
    """El contraste que justifica `lib/intent-key.ts`: una clave nueva por clic no protege de nada."""
    with ephemeral_postgres() as engine:
        api = Api(engine)
        try:
            with Session(engine) as db:
                product_id = add_product(db).id

            responses = api.together(
                lambda client, i: client.post(
                    "/api/orders", json=body(product_id), headers={"Idempotency-Key": f"k-{i}"}
                )
            )

            assert [r.status_code for r in responses] == [201] * CLICKS
            with Session(engine) as db:
                assert db.scalar(select(func.count()).select_from(Order)) == CLICKS
        finally:
            api.close()


def test_twenty_identical_purchase_clicks_with_the_same_key_buy_once():
    with ephemeral_postgres() as engine:
        api = Api(engine)
        try:
            with Session(engine) as db:
                order = paid_order(db)
                items = list(db.scalars(select(OrderItem).where(OrderItem.order_id == order.id)))
                fulfillment_id = (
                    FulfilmentService(db)
                    .create(
                        order.id, [FulfilmentRequestLine(i.id, i.quantity) for i in items], actor="owner@amazona.local"
                    )
                    .id
                )

            responses = api.together(
                lambda client, _: client.post(
                    f"/api/fulfillments/{fulfillment_id}/purchase", headers={"Idempotency-Key": "buy-1"}
                )
            )

            statuses = sorted(r.status_code for r in responses)
            assert set(statuses) <= {200, 409}, statuses
            assert 200 in statuses, "someone got the answer"
            with Session(engine) as db:
                purchases = db.scalars(
                    select(ExternalAction).where(
                        ExternalAction.reference == f"order_fulfilment:{fulfillment_id}:purchase"
                    )
                ).all()
                assert len(purchases) == 1 and purchases[0].status == "SUCCEEDED", [p.status for p in purchases]
                assert db.get(Fulfillment, fulfillment_id).status == "PURCHASED"  # type: ignore[union-attr]
        finally:
            api.close()


# --- El código que el cliente lee ---------------------------------------------------------------------------------


@pytest.fixture()
def env():
    engine = make_engine()
    api = Api(engine)
    with api.factory() as db:
        product_id = add_product(db).id
    try:
        yield TestClient(app, raise_server_exceptions=False), api.factory, product_id
    finally:
        api.close()
        engine.dispose()


def test_a_missing_key_says_so_with_a_code(env):
    client, _, product_id = env

    response = client.post("/api/orders", json=body(product_id))

    assert response.status_code == 428 and response.json()["code"] == "idempotency_key_required"


def test_the_same_key_with_another_body_says_so_with_a_code(env):
    client, _, product_id = env
    client.post("/api/orders", json=body(product_id), headers={"Idempotency-Key": "k-1"})
    other = body(product_id)
    other["lines"][0]["quantity"] = 3

    response = client.post("/api/orders", json=other, headers={"Idempotency-Key": "k-1"})

    assert response.status_code == 409 and response.json()["code"] == "idempotency_conflict"


@pytest.mark.parametrize(
    "state, code",
    [("IN_PROGRESS", "idempotency_in_progress"), ("UNKNOWN_OUTCOME", "idempotency_outcome_unknown")],
)
def test_a_key_in_progress_or_with_an_unknown_outcome_says_which_with_a_code(env, state, code):
    client, factory, product_id = env
    assert client.post("/api/orders", json=body(product_id), headers={"Idempotency-Key": "k-1"}).status_code == 201
    with factory() as db:
        done = db.scalars(select(IdempotencyRecord)).one()
        db.add(
            IdempotencyRecord(
                scope=done.scope, actor_hash=done.actor_hash, key="k-2", request_hash=done.request_hash, status=state
            )
        )
        db.commit()

    response = client.post("/api/orders", json=body(product_id), headers={"Idempotency-Key": "k-2"})

    assert response.status_code == 409 and response.json()["code"] == code, response.text
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Order)) == 1, "the stuck key never ran the work again"


def test_a_business_refusal_has_no_idempotency_code(env):
    """Un 409 de negocio (no es un problema de la clave) no lleva `code` de idempotencia: el cliente no lo confunde."""
    client, _, product_id = env
    order = client.post("/api/orders", json=body(product_id), headers={"Idempotency-Key": "k-1"}).json()

    refused = client.post(
        f"/api/orders/{order['id']}/fulfillments",
        json={"lines": [{"order_item_id": order["items"][0]["id"], "quantity": 1}]},
        headers={"Idempotency-Key": "f-1"},
    )

    assert refused.status_code == 409, refused.text
    assert "code" not in refused.json(), "a business conflict is not an idempotency conflict"
