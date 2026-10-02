"""Fulfillments por HTTP (Milestone 44, ADR 0028 §6 y §9).

Las rutas se usan de verdad (TestClient). Qué se promete: que repartir, comprar y enviar exigen `Idempotency-Key`
**siempre** (también en simulación), que repetir la petición no compra ni envía dos veces, que el cliente pide una
operación y nunca declara un estado, que un fulfillment comprado no devuelve sus unidades y que las lecturas no
escriben.
"""

import pytest
from fastapi.testclient import TestClient
from fulfilment_test_support import paid_order
from order_test_support import make_engine, session_factory
from sqlalchemy import event, func, select

from app.core.config import get_settings
from app.db.models.external_action import ExternalAction
from app.db.models.fulfillment import Fulfillment
from app.db.models.order import Order, OrderItem
from app.db.session import get_db
from app.main import app
from app.orders.fulfilment_projection import fulfilment_reference


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
        order = paid_order(db)
        order_id = order.id
        lines = [(i.id, i.quantity) for i in db.scalars(select(OrderItem).order_by(OrderItem.line_number))]
    try:
        yield TestClient(app, raise_server_exceptions=False), factory, order_id, lines
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_settings, None)
        engine.dispose()


def cover(lines, quantities=(4, 2)) -> dict:
    return {
        "lines": [
            {"order_item_id": item_id, "quantity": q} for (item_id, _), q in zip(lines, quantities, strict=True) if q
        ]
    }


def create(client, order_id, lines, quantities=(4, 2), key="ful-1"):
    return client.post(
        f"/api/orders/{order_id}/fulfillments", json=cover(lines, quantities), headers={"Idempotency-Key": key}
    )


def act(client, fulfillment_id: str, verb: str, key: str | None = None):
    headers = {"Idempotency-Key": key} if key else {}
    return client.post(f"/api/fulfillments/{fulfillment_id}/{verb}", headers=headers)


def allocated(factory) -> list[int]:
    with factory() as db:
        return [i.allocated_quantity for i in db.scalars(select(OrderItem).order_by(OrderItem.line_number))]


def actions(factory) -> int:
    with factory() as db:
        return (
            db.scalar(
                select(func.count())
                .select_from(ExternalAction)
                .where(ExternalAction.reference.like("order_fulfilment:%"))
            )
            or 0
        )


# --- Repartir --------------------------------------------------------------------------------------------------


def test_assigning_without_an_idempotency_key_is_refused_even_in_a_simulation(env):
    client, factory, order_id, lines = env

    response = client.post(f"/api/orders/{order_id}/fulfillments", json=cover(lines))

    assert response.status_code == 428
    assert allocated(factory) == [0, 0]
    with factory() as db:
        assert db.scalars(select(Fulfillment)).all() == []


def test_a_paid_order_is_assigned_and_shown_with_its_fulfillment(env):
    client, factory, order_id, lines = env

    response = create(client, order_id, lines)

    assert response.status_code == 201, response.text
    made = response.json()
    assert made["status"] == "READY" and made["order_id"] == order_id and made["failed_attempts"] == 0
    assert [(i["line_number"], i["quantity"]) for i in made["items"]] == [(1, 4), (2, 2)]
    assert allocated(factory) == [4, 2] and actions(factory) == 0, "assigning goes nowhere: it is a local decision"
    shown = client.get(f"/api/orders/{order_id}").json()
    assert [f["id"] for f in shown["fulfillments"]] == [made["id"]]
    assert [i["allocated_quantity"] for i in shown["items"]] == [4, 2]


def test_the_same_key_is_the_same_fulfillment_and_another_key_cannot_assign_more_than_there_is(env):
    client, factory, order_id, lines = env
    first = create(client, order_id, lines, (3, 0), key="ful-1")

    again = create(client, order_id, lines, (3, 0), key="ful-1")
    other = create(client, order_id, lines, (1, 2), key="ful-2")
    too_much = create(client, order_id, lines, (1, 0), key="ful-3")

    assert again.status_code == 201 and again.json() == first.json()
    assert again.headers.get("Idempotency-Replayed") == "true"
    assert other.status_code == 201 and other.json()["id"] != first.json()["id"]
    assert too_much.status_code == 409
    assert allocated(factory) == [4, 2]
    with factory() as db:
        assert len(db.scalars(select(Fulfillment)).all()) == 2


def test_the_key_with_other_lines_is_refused_and_nothing_is_assigned_twice(env):
    client, factory, order_id, lines = env
    create(client, order_id, lines, (1, 0), key="ful-1")

    response = create(client, order_id, lines, (2, 0), key="ful-1")

    assert response.status_code in (409, 422)
    assert allocated(factory) == [1, 0]


def test_an_order_that_is_not_paid_is_not_fulfilled(env):
    client, factory, order_id, lines = env
    with factory() as db:
        db.get(Order, order_id).status = "AWAITING_PAYMENT"  # type: ignore[union-attr]
        db.commit()

    response = create(client, order_id, lines)

    assert response.status_code == 409 and "only a paid order" in response.json()["detail"]
    assert allocated(factory) == [0, 0]


@pytest.mark.parametrize(
    "body",
    [
        {"lines": []},
        {"lines": [{"order_item_id": "x", "quantity": 0}]},
        {"lines": [{"order_item_id": "x", "quantity": -1}]},
        {"lines": [{"order_item_id": "x", "quantity": "many"}]},
        {"lines": [{"order_item_id": "", "quantity": 1}]},
        {"lines": [{"order_item_id": "x", "quantity": 1, "status": "PURCHASED"}], "status": "SHIPPED"},
        {},
    ],
)
def test_malformed_requests_are_refused_and_the_body_cannot_declare_a_state(env, body):
    client, factory, order_id, _ = env

    response = client.post(f"/api/orders/{order_id}/fulfillments", json=body, headers={"Idempotency-Key": "k"})

    assert response.status_code == 422
    assert allocated(factory) == [0, 0]


def test_unknown_orders_lines_and_fulfillments_are_404(env):
    client, _, order_id, lines = env

    assert create(client, "missing-order", lines).status_code == 404
    unknown_line = client.post(
        f"/api/orders/{order_id}/fulfillments",
        json={"lines": [{"order_item_id": "no-such-line", "quantity": 1}]},
        headers={"Idempotency-Key": "k"},
    )
    assert unknown_line.status_code == 404
    for verb in ("purchase", "ship"):
        assert act(client, "missing", verb, key=f"k-{verb}").status_code == 404
    for verb in ("complete", "cancel", "fail"):
        assert act(client, "missing", verb).status_code == 404


# --- Comprar y enviar --------------------------------------------------------------------------------------------


def test_buying_and_shipping_need_a_key_even_in_a_simulation_and_do_nothing_without_it(env):
    client, factory, order_id, lines = env
    made = create(client, order_id, lines).json()

    bought = act(client, made["id"], "purchase")
    shipped = act(client, made["id"], "ship")

    assert bought.status_code == 428 and shipped.status_code == 428
    assert actions(factory) == 0
    with factory() as db:
        assert db.get(Fulfillment, made["id"]).status == "READY"  # type: ignore[union-attr]


def test_a_purchase_and_a_shipment_go_through_the_whole_pipeline_and_the_order_closes(env):
    client, factory, order_id, lines = env
    made = create(client, order_id, lines).json()

    bought = act(client, made["id"], "purchase", key="buy-1")
    shipped = act(client, made["id"], "ship", key="ship-1")
    done = act(client, made["id"], "complete")

    assert bought.status_code == 200 and bought.json()["status"] == "PURCHASED"
    assert bought.json()["purchase_reference"] and bought.json()["purchased_at"]
    assert shipped.status_code == 200 and shipped.json()["status"] == "SHIPPED"
    assert shipped.json()["tracking_reference"].startswith("simtrk_")
    assert done.status_code == 200 and done.json()["status"] == "COMPLETED" and done.json()["completed_by"]
    assert client.get(f"/api/orders/{order_id}").json()["status"] == "COMPLETED"
    with factory() as db:
        for phase in ("purchase", "ship"):
            reference = fulfilment_reference(made["id"], phase)
            assert (
                db.scalars(select(ExternalAction).where(ExternalAction.reference == reference)).one().status
                == "SUCCEEDED"
            )


def test_the_same_key_buys_once_and_replays_the_same_answer(env):
    client, factory, order_id, lines = env
    made = create(client, order_id, lines).json()

    first = act(client, made["id"], "purchase", key="buy-1")
    again = act(client, made["id"], "purchase", key="buy-1")

    assert again.status_code == 200 and again.json() == first.json()
    assert again.headers.get("Idempotency-Replayed") == "true"
    assert actions(factory) == 1, "the provider was asked once"


def test_another_key_cannot_buy_what_is_already_bought(env):
    client, factory, order_id, lines = env
    made = create(client, order_id, lines).json()
    act(client, made["id"], "purchase", key="buy-1")

    again = act(client, made["id"], "purchase", key="buy-2")

    assert again.status_code == 409 and "needs it READY" in again.json()["detail"]
    assert actions(factory) == 1


def test_a_shipment_before_the_purchase_is_a_409_that_sends_nothing(env):
    client, factory, order_id, lines = env
    made = create(client, order_id, lines).json()

    response = act(client, made["id"], "ship", key="ship-1")

    assert response.status_code == 409 and "needs it PURCHASED" in response.json()["detail"]
    assert actions(factory) == 0


def test_the_delivery_of_something_not_shipped_is_a_409(env):
    client, _, order_id, lines = env
    made = create(client, order_id, lines).json()

    assert act(client, made["id"], "complete").status_code == 409
    act(client, made["id"], "purchase", key="buy-1")
    assert act(client, made["id"], "complete").status_code == 409


def test_a_refunded_order_is_not_shipped_over_http(env):
    client, factory, order_id, lines = env
    made = create(client, order_id, lines).json()
    act(client, made["id"], "purchase", key="buy-1")
    with factory() as db:
        from app.db.models.payment import Payment

        payment = db.scalars(select(Payment)).one()
        payment.refund_committed_amount = payment.captured_amount  # lo que dejaría un reembolso ordenado
        db.commit()

    response = act(client, made["id"], "ship", key="ship-1")

    assert response.status_code == 409 and "no longer fully paid" in response.json()["detail"]
    with factory() as db:
        assert db.get(Fulfillment, made["id"]).status == "PURCHASED"  # type: ignore[union-attr]


# --- Cancelar y abandonar -----------------------------------------------------------------------------------------


def test_cancelling_before_buying_gives_the_units_back_and_repeating_it_is_a_409(env):
    client, factory, order_id, lines = env
    made = create(client, order_id, lines).json()

    cancelled = act(client, made["id"], "cancel")
    again = act(client, made["id"], "cancel")

    assert cancelled.status_code == 200 and cancelled.json()["status"] == "CANCELLED"
    assert again.status_code == 409
    assert allocated(factory) == [0, 0]
    assert create(client, order_id, lines, key="ful-2").status_code == 201, "the units went back to the pool"


def test_a_bought_fulfillment_cannot_be_cancelled_and_keeps_its_units(env):
    client, factory, order_id, lines = env
    made = create(client, order_id, lines).json()
    act(client, made["id"], "purchase", key="buy-1")

    response = act(client, made["id"], "cancel")

    assert response.status_code == 409
    assert allocated(factory) == [4, 2]


def test_a_fulfillment_that_has_not_failed_cannot_be_declared_failed(env):
    client, factory, order_id, lines = env
    made = create(client, order_id, lines).json()

    response = act(client, made["id"], "fail")

    assert response.status_code == 409 and "has not failed" in response.json()["detail"]
    assert allocated(factory) == [4, 2]


# --- Lecturas --------------------------------------------------------------------------------------------------


def test_reading_orders_with_fulfillments_writes_nothing(env):
    client, factory, order_id, lines = env
    made = create(client, order_id, lines).json()
    act(client, made["id"], "purchase", key="buy-1")
    writes: list[str] = []
    with factory() as db:
        event.listen(db.get_bind(), "before_cursor_execute", lambda c, cur, stmt, *a: writes.append(stmt))

    client.get("/api/orders")
    client.get(f"/api/orders/{order_id}")

    assert not [s for s in writes if s.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))]


def test_no_route_can_state_the_outcome_of_a_purchase_or_a_shipment():
    spec = app.openapi()
    routes = {
        (method.upper(), path)
        for path, item in spec["paths"].items()
        if path.startswith("/api/fulfillments")
        for method in item
    }

    assert routes == {
        ("POST", f"/api/fulfillments/{{fulfillment_id}}/{verb}")
        for verb in ("purchase", "ship", "complete", "cancel", "fail")
    }, "no GET, PUT or PATCH: a fulfillment is only moved by an operation, never rewritten"
    for verb in ("purchase", "ship", "complete", "cancel", "fail"):
        post = spec["paths"][f"/api/fulfillments/{{fulfillment_id}}/{verb}"]["post"]
        assert "requestBody" not in post, "the client asks for an operation and never states a result"
