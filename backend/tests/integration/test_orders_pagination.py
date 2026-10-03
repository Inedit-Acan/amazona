"""`GET /api/orders` pagina por cursor y nunca trunca en silencio (M45, P2-2).

Antes devolvía una lista: quien pedía 500 y recibía 500 no podía saber si existía el 501. Ahora devuelve una página
`{items, limit, count, has_more, next_cursor}` y se recorre siguiendo `next_cursor`. Qué se prueba, en SQLite y en un
PostgreSQL de verdad (donde los instantes son `timestamptz` y los empates y las inserciones simultáneas existen):

- 0, menos del límite, exactamente el límite, límite + 1 y varias páginas: `has_more` dice la verdad en cada caso;
- el orden es total (`created_at DESC, id ASC`): a igual instante manda el `id`, y un recorrido completo no repite ni se
  salta ningún pedido, ni siquiera cuando una página se corta en mitad de un empate;
- los pedidos creados **mientras** se recorre quedan fuera de ese recorrido y no perturban nada (con `offset` repetirían
  filas); uno nuevo aparece al empezar de nuevo;
- los parámetros inválidos son un 422 (no una página vacía ni una consulta distinta), y una página posterior al final es
  una página vacía **válida**;
- leer no escribe; no se mezclan monedas; cada pedido trae sus propios cobros, reembolsos y fulfillments; ningún dato
  personal; y el cursor es opaco y no admite inyección.
"""

import datetime
import threading
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from order_test_support import add_product, make_engine, session_factory
from pg_test_support import ephemeral_postgres
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models.fulfillment import Fulfillment, FulfillmentItem
from app.db.models.order import Order, OrderItem
from app.db.models.payment import Payment, Refund
from app.db.session import get_db
from app.main import app
from app.orders.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, InvalidCursorError, OrderCursor
from app.orders.service import OrderService

BASE = datetime.datetime(2026, 10, 3, 9, 0, tzinfo=datetime.UTC)
PAGE_KEYS = {"items", "limit", "count", "has_more", "next_cursor"}


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
def env(engine):
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


def seed(factory, product_id: str, specs: list[tuple]) -> list[str]:
    """Pedidos con `id`, instante y moneda **fijados** (los empates no se pueden provocar de otro modo).

    Cada spec es `(id, created_at, currency)` o `(id, created_at, currency, status)`."""
    with factory() as db:
        for spec in specs:
            order_id, created, currency = spec[:3]
            status = spec[3] if len(spec) > 3 else "AWAITING_PAYMENT"
            order = Order(
                id=order_id,
                customer_ref=f"sim_{order_id[-8:]}",
                market="eu",
                currency=currency,
                amount_due=Decimal("50.0000"),
                status=status,
                is_simulated=True,
                correlation_id=f"corr-{order_id[-8:]}",
                created_at=created,
            )
            order.items = [
                OrderItem(
                    line_number=1,
                    product_id=product_id,
                    quantity=2,
                    unit_price=Decimal("25.0000"),
                    line_total=Decimal("50.0000"),
                )
            ]
            db.add(order)
        db.commit()
    return [spec[0] for spec in specs]


def at(seconds: int) -> datetime.datetime:
    return BASE + datetime.timedelta(seconds=seconds)


def oid(n: int) -> str:
    return f"order-{n:06d}"


def expected_order(specs: list[tuple]) -> list[str]:
    """El orden prometido: del más reciente al más antiguo y, a igual instante, por id."""
    return [s[0] for s in sorted(specs, key=lambda s: (-s[1].timestamp(), s[0]))]


def page(client: TestClient, **params):
    response = client.get("/api/orders", params=params)
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == PAGE_KEYS, "the page says what it is: nothing more, nothing less"
    assert body["count"] == len(body["items"]) <= body["limit"]
    assert body["has_more"] == (body["next_cursor"] is not None), "there is somewhere to continue iff there is more"
    return body


def walk(client: TestClient, limit: int, **params) -> tuple[list[str], int]:
    """Recorre todo siguiendo `next_cursor`. Devuelve los ids en el orden en que llegaron y cuántas páginas hubo."""
    ids: list[str] = []
    cursor = None
    pages = 0
    while True:
        body = page(client, limit=limit, **({"cursor": cursor} if cursor else {}), **params)
        pages += 1
        ids += [o["id"] for o in body["items"]]
        if not body["has_more"]:
            return ids, pages
        cursor = body["next_cursor"]
        assert pages < 1000, "a walk that does not end"


# --- Qué dice una página: vacía, corta, justa, un pedido de más -----------------------------------------------------


def test_an_empty_list_is_an_empty_page_and_says_there_is_no_more(env):
    client, _, _ = env

    body = page(client)

    assert body["items"] == [] and body["count"] == 0 and body["has_more"] is False and body["next_cursor"] is None
    assert body["limit"] == DEFAULT_PAGE_SIZE


def test_fewer_orders_than_the_limit_are_all_of_them(env):
    client, factory, product_id = env
    specs = [(oid(n), at(n), "EUR") for n in range(1, 4)]
    seed(factory, product_id, specs)

    body = page(client, limit=10)

    assert [o["id"] for o in body["items"]] == expected_order(specs) and body["has_more"] is False


def test_exactly_the_limit_is_not_truncated_and_does_not_pretend_there_is_more(env):
    client, factory, product_id = env
    specs = [(oid(n), at(n), "EUR") for n in range(1, 11)]
    seed(factory, product_id, specs)

    body = page(client, limit=10)

    assert body["count"] == 10 and body["has_more"] is False and body["next_cursor"] is None


def test_one_more_than_the_limit_says_so_and_the_next_page_has_exactly_that_one(env):
    client, factory, product_id = env
    specs = [(oid(n), at(n), "EUR") for n in range(1, 12)]
    seed(factory, product_id, specs)

    first = page(client, limit=10)
    assert first["count"] == 10 and first["has_more"] is True
    second = page(client, limit=10, cursor=first["next_cursor"])

    assert [o["id"] for o in first["items"]] + [o["id"] for o in second["items"]] == expected_order(specs)
    assert second["count"] == 1 and second["has_more"] is False and second["next_cursor"] is None


def test_several_pages_cover_everything_once_and_in_order(env):
    client, factory, product_id = env
    specs = [(oid(n), at(n), "EUR") for n in range(1, 26)]
    seed(factory, product_id, specs)

    ids, pages = walk(client, limit=10)

    assert pages == 3 and ids == expected_order(specs)
    assert len(set(ids)) == len(ids) == 25


# --- El orden es total: los empates ---------------------------------------------------------------------------------


@pytest.mark.parametrize("limit", [1, 2, 3, 5, 7, 12, 13])
def test_equal_timestamps_are_ordered_by_id_and_a_page_may_end_inside_a_tie(env, limit):
    """Doce pedidos en tres instantes: cualquier tamaño de página corta algún empate por la mitad."""
    client, factory, product_id = env
    specs = [(oid(n), at(n % 3), "EUR") for n in range(1, 13)]
    random_ids = [(f"z{n:05d}", at(1), "EUR") for n in range(3)] + [(f"a{n:05d}", at(1), "EUR") for n in range(3)]
    seed(factory, product_id, specs + random_ids)

    ids, _ = walk(client, limit=limit)

    assert ids == expected_order(specs + random_ids)
    assert len(set(ids)) == len(ids) == 18, "no duplicates and nothing skipped, even across a tie"


def test_the_same_request_twice_gives_the_same_page(env):
    client, factory, product_id = env
    seed(factory, product_id, [(oid(n), at(n % 2), "EUR") for n in range(1, 9)])

    assert page(client, limit=4) == page(client, limit=4)


# --- Los pedidos que se crean mientras se recorre -------------------------------------------------------------------


def test_orders_created_between_pages_do_not_repeat_or_skip_anything_and_a_new_walk_sees_them(env):
    client, factory, product_id = env
    specs = [(oid(n), at(n), "EUR") for n in range(1, 21)]
    seed(factory, product_id, specs)
    first = page(client, limit=8)

    # Mientras alguien lee la primera página, entran cinco pedidos más: son los más recientes.
    arrivals = [(oid(100 + n), at(1000 + n), "EUR") for n in range(5)]
    seed(factory, product_id, arrivals)
    ids = [o["id"] for o in first["items"]]
    cursor = first["next_cursor"]
    while cursor:
        body = page(client, limit=8, cursor=cursor)
        ids += [o["id"] for o in body["items"]]
        cursor = body["next_cursor"]

    assert ids == expected_order(specs), "the walk in progress is exactly what existed when it started"
    assert len(set(ids)) == len(ids)
    fresh, _ = walk(client, limit=8)
    assert fresh == expected_order(specs + arrivals), "a new walk sees the new orders, first"


def test_a_stress_of_creations_during_a_walk_never_repeats_and_never_loses_what_was_there():
    """Un hilo crea pedidos sin parar mientras otro recorre: sobre un PostgreSQL de verdad, con transacciones."""
    with ephemeral_postgres() as pg_engine:
        factory = session_factory(pg_engine)
        with factory() as db:
            product_id = add_product(db).id
        original = [(oid(n), at(n), "EUR") for n in range(1, 301)]
        seed(factory, product_id, original)

        def override_get_db():
            session = factory()
            try:
                yield session
            finally:
                session.close()

        app.dependency_overrides[get_db] = override_get_db
        stop = threading.Event()
        created: list[str] = []

        def writer() -> None:
            n = 0
            while not stop.is_set():
                n += 1
                now = datetime.datetime.now(datetime.UTC)
                created.extend(seed(factory, product_id, [(oid(10_000 + n), now, "USD")]))

        thread = threading.Thread(target=writer)
        try:
            client = TestClient(app, raise_server_exceptions=False)
            thread.start()
            ids, pages = walk(client, limit=25)
        finally:
            stop.set()
            thread.join(timeout=30)
            app.dependency_overrides.pop(get_db, None)

        assert len(created) > 0, "the writer really ran during the walk"
        assert len(set(ids)) == len(ids), "no order twice, whatever was created in between"
        assert set(expected_order(original)) <= set(ids), "nothing that existed at the start was lost"
        originals_in_order = [i for i in ids if i in set(expected_order(original))]
        assert originals_in_order == expected_order(original)
        assert pages >= 12


# --- Parámetros inválidos y páginas posteriores al final ------------------------------------------------------------


@pytest.mark.parametrize("limit", ["0", "-1", "abc", "1.5", "", str(MAX_PAGE_SIZE + 1), "100000"])
def test_an_invalid_limit_is_a_422_and_not_a_page(env, limit):
    client, factory, product_id = env
    seed(factory, product_id, [(oid(1), at(1), "EUR")])

    response = client.get("/api/orders", params={"limit": limit})

    assert response.status_code == 422, response.text


def test_the_maximum_limit_is_allowed_and_one_more_is_not(env):
    client, factory, product_id = env
    seed(factory, product_id, [(oid(1), at(1), "EUR")])

    assert client.get("/api/orders", params={"limit": MAX_PAGE_SIZE}).status_code == 200
    assert client.get("/api/orders", params={"limit": MAX_PAGE_SIZE + 1}).status_code == 422


def test_offset_is_refused_loudly_instead_of_returning_the_wrong_page(env):
    client, factory, product_id = env
    seed(factory, product_id, [(oid(n), at(n), "EUR") for n in range(1, 4)])

    response = client.get("/api/orders", params={"limit": 1, "offset": 1})

    assert response.status_code == 422 and "next_cursor" in response.text


def test_an_unknown_status_is_still_a_422(env):
    client, _, _ = env

    assert client.get("/api/orders", params={"status": "NOPE"}).status_code == 422


def inject(value: str) -> str:
    import base64
    import json

    return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")


@pytest.mark.parametrize(
    "cursor",
    [
        "not-a-cursor",
        "!!!!",
        "a" * 400,
        "%27%3B%20DROP%20TABLE%20orders%3B--",
        "e30",  # `{}`: JSON válido, no es un cursor
        "W10",  # `[]`
        inject("x"),
        "eyJ2IjoyLCJ0IjoiMjAyNi0xMC0wM1QwOTowMDowMCswMDowMCIsImkiOiJhIn0",  # versión 2
        "eyJ2IjoxLCJ0Ijoibm8iLCJpIjoiYSJ9",  # instante que no lo es
        "eyJ2IjoxLCJ0IjoiMjAyNi0xMC0wM1QwOTowMDowMCswMDowMCIsImkiOiInOyBEUk9QIFRBQkxFIG9yZGVyczstLSJ9",  # id con SQL
        "eyJ2IjoxLCJ0IjoiMjAyNi0xMC0wM1QwOTowMDowMCswMDowMCIsImkiOjV9",  # id que no es texto
    ],
)
def test_an_invalid_cursor_is_a_422_never_an_empty_page_or_another_query(env, cursor):
    client, factory, product_id = env
    seed(factory, product_id, [(oid(n), at(n), "EUR") for n in range(1, 4)])

    response = client.get("/api/orders", params={"cursor": cursor})

    assert response.status_code == 422, response.text
    assert "items" not in response.text


def test_a_cursor_never_comes_from_the_status_it_was_asked_with_but_from_a_position(env):
    """El cursor es una posición en el orden: sirve con o sin filtro de estado."""
    client, factory, product_id = env
    specs = [(oid(n), at(n), "EUR", "PAID" if n % 2 else "CANCELLED") for n in range(1, 21)]
    seed(factory, product_id, specs)

    paid, _ = walk(client, limit=3, status="PAID")

    assert paid == [s[0] for s in sorted(specs, key=lambda s: (-s[1].timestamp(), s[0])) if s[3] == "PAID"]


def test_a_page_after_the_end_is_a_valid_empty_page_not_an_error(env):
    client, factory, product_id = env
    specs = [(oid(n), at(n), "EUR") for n in range(1, 4)]
    seed(factory, product_id, specs)
    oldest = min(specs, key=lambda s: s[1])
    past_the_end = OrderCursor(created_at=oldest[1], order_id=oldest[0]).encode()

    body = page(client, cursor=past_the_end)

    assert body["items"] == [] and body["count"] == 0 and body["has_more"] is False and body["next_cursor"] is None


def test_a_cursor_from_the_future_or_the_far_past_is_just_a_position(env):
    client, factory, product_id = env
    specs = [(oid(n), at(n), "EUR") for n in range(1, 4)]
    seed(factory, product_id, specs)

    everything = page(client, cursor=OrderCursor(at(10_000), "zzz").encode())
    nothing = page(client, cursor=OrderCursor(at(-10_000), "a").encode())

    assert [o["id"] for o in everything["items"]] == expected_order(specs)
    assert nothing["items"] == [] and nothing["has_more"] is False


# --- Leer no escribe ------------------------------------------------------------------------------------------------


def test_walking_the_whole_list_writes_nothing(env, engine):
    client, factory, product_id = env
    seed(factory, product_id, [(oid(n), at(n % 4), "EUR") for n in range(1, 31)])
    statements: list[str] = []
    event.listen(engine, "before_cursor_execute", lambda conn, cur, stmt, *a: statements.append(stmt))

    walk(client, limit=7)
    client.get("/api/orders", params={"cursor": "garbage"})

    writes = [
        s for s in statements if s.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE", "SAVEPOINT", "RELEASE"))
    ]
    assert statements and writes == [], writes


# --- Lo que trae cada pedido ----------------------------------------------------------------------------------------


def test_every_order_carries_its_own_payments_refunds_and_fulfillments_across_pages(env):
    client, factory, product_id = env
    specs = [(oid(n), at(n), "EUR", "PAID") for n in range(1, 7)]
    seed(factory, product_id, specs)
    with factory() as db:
        for n in (2, 3, 5):
            order = db.get(Order, oid(n))
            payment = Payment(
                order_id=order.id,
                attempt_number=1,
                provider="simulated-payments",
                status="SUCCEEDED",
                amount=Decimal("50.0000"),
                currency="EUR",
                captured_amount=Decimal("50.0000"),
                refund_committed_amount=Decimal(n),
                refunded_amount=Decimal(n),
                correlation_id=f"pay-{n}",
            )
            db.add(payment)
            db.flush()
            db.add(
                Refund(
                    payment_id=payment.id,
                    provider="simulated-payments",
                    origin="OPERATOR",
                    status="SUCCEEDED",
                    amount=Decimal(n),
                    currency="EUR",
                    reason="customer_request",
                    correlation_id=f"ref-{n}",
                    requested_at=at(n),
                    finished_at=at(n),
                )
            )
        for n in (3, 4):
            order = db.get(Order, oid(n))
            fulfillment = Fulfillment(
                order_id=order.id,
                provider="simulated-fulfilment",
                status="READY",
                created_by="test",
                correlation_id=f"ful-{n}",
            )
            db.add(fulfillment)
            db.flush()
            db.add(FulfillmentItem(fulfillment_id=fulfillment.id, order_item_id=order.items[0].id, quantity=2))
        db.commit()

    seen: dict[str, dict] = {}
    cursor = None
    while True:
        body = page(client, limit=2, **({"cursor": cursor} if cursor else {}))
        seen.update({o["id"]: o for o in body["items"]})
        if not body["has_more"]:
            break
        cursor = body["next_cursor"]

    assert set(seen) == {s[0] for s in specs}
    for n in range(1, 7):
        order = seen[oid(n)]
        assert len(order["payments"]) == (1 if n in (2, 3, 5) else 0), n
        assert len(order["refunds"]) == (1 if n in (2, 3, 5) else 0), n
        assert len(order["fulfillments"]) == (1 if n in (3, 4) else 0), n
        assert len(order["items"]) == 1
        for refund in order["refunds"]:
            assert Decimal(refund["amount"]["amount"]) == Decimal(n), "the refund of this order, not of its neighbour"
        for fulfillment in order["fulfillments"]:
            assert fulfillment["order_id"] == oid(n)


def test_currencies_are_never_mixed_and_amounts_stay_exact(env):
    client, factory, product_id = env
    specs = [(oid(n), at(n), "EUR" if n % 3 else "USD") for n in range(1, 31)]
    seed(factory, product_id, specs)

    totals: dict[str, Decimal] = {}
    cursor = None
    while True:
        body = page(client, limit=7, **({"cursor": cursor} if cursor else {}))
        for order in body["items"]:
            due = order["amount_due"]
            totals[due["currency"]] = totals.get(due["currency"], Decimal(0)) + Decimal(due["amount"])
            assert isinstance(due["amount"], str), "money travels as a string, never a float"
            assert all(i["unit_price"]["currency"] == due["currency"] for i in order["items"])
        if not body["has_more"]:
            break
        cursor = body["next_cursor"]

    assert totals == {"EUR": Decimal("50") * 20, "USD": Decimal("50") * 10}


# --- Privacidad y forma del cursor ----------------------------------------------------------------------------------


def test_no_personal_data_in_a_page_and_only_the_columns_the_screen_needs(env):
    client, factory, product_id = env
    seed(factory, product_id, [(oid(n), at(n), "EUR") for n in range(1, 4)])

    body = page(client)

    for order in body["items"]:
        assert set(order) == {
            "id", "customer_ref", "market", "status", "is_simulated", "amount_due", "items", "payments", "refunds",
            "fulfillments", "created_at", "paid_at", "completed_at", "cancelled_at", "correlation_id",
            "attention_required", "attention_reasons",
        }  # fmt: skip
        assert order["customer_ref"].startswith("sim_") and "@" not in order["customer_ref"]
    text = str(body)
    assert "@" not in text and "email" not in text.lower() and "phone" not in text.lower()


def test_the_cursor_is_opaque_and_carries_only_a_position(env):
    client, factory, product_id = env
    seed(factory, product_id, [(oid(n), at(n), "EUR") for n in range(1, 6)])

    cursor = page(client, limit=2)["next_cursor"]

    assert "order-" not in cursor and "2026" not in cursor, "it is not meant to be read or built by the client"
    assert "sim_" not in cursor
    decoded = OrderCursor.decode(cursor)
    instant = decoded.created_at
    if instant.tzinfo is not None:  # PostgreSQL lo devuelve en la zona de la sesión: es el mismo instante
        instant = instant.astimezone(datetime.UTC).replace(tzinfo=None)
    assert decoded.order_id == oid(4) and instant == at(4).replace(tzinfo=None)


@pytest.mark.parametrize(
    "created",
    [datetime.datetime(2026, 10, 3, 9, 0, 0, 123456, tzinfo=datetime.UTC), datetime.datetime(2026, 1, 1, 0, 0)],
)
def test_a_cursor_round_trips_exactly_with_or_without_time_zone(created):
    cursor = OrderCursor(created_at=created, order_id="abc-123")

    assert OrderCursor.decode(cursor.encode()) == cursor


def test_decoding_refuses_what_it_did_not_issue():
    for bad in ("", "x", "e30", "?" * 10, "a" * 300):
        with pytest.raises(InvalidCursorError):
            OrderCursor.decode(bad)


# --- El contrato ----------------------------------------------------------------------------------------------------


def test_the_published_contract_is_a_page_with_a_maximum_and_no_offset():
    document = app.openapi()
    operation = document["paths"]["/api/orders"]["get"]
    parameters = {p["name"]: p for p in operation["parameters"]}
    schema_ref = operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    schema = document["components"]["schemas"][schema_ref.rsplit("/", 1)[1]]

    assert set(schema["properties"]) == PAGE_KEYS and set(schema["required"]) == PAGE_KEYS
    assert "offset" not in parameters, "offset is refused, so it is not advertised"
    assert parameters["limit"]["schema"]["maximum"] == MAX_PAGE_SIZE and parameters["limit"]["schema"]["minimum"] == 1
    assert {"limit", "cursor", "status"} == set(parameters)


def test_there_is_no_way_left_to_list_orders_that_truncates_without_saying_so():
    """Una guardia contra la vuelta atrás: el servicio solo lista por páginas, y toda página dice si hay más."""
    assert not hasattr(OrderService, "list"), "an unpaginated lister is how P2-2 happened"
    assert hasattr(OrderService, "list_page")


def test_the_service_refuses_a_limit_outside_its_bounds_even_when_called_directly(engine):
    with Session(engine) as db:
        for bad in (0, -5, MAX_PAGE_SIZE + 1):
            with pytest.raises(Exception, match="limit must be between"):
                OrderService(db).list_page(limit=bad)
