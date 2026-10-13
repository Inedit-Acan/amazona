"""Precio de venta y costes fijos en la frontera de `POST /api/economics/runs` (M46, Commit 5b).

Antes: `sale_price = 0` llegaba a `scenarios.py` y era un 500 (`ZeroDivisionError`); un `sale_price` o un
`monthly_fixed_costs` negativo se aceptaba y se guardaba con un 201.

Ahora el endpoint exige, antes de crear nada, un precio estrictamente positivo **como importe monetario** (un precio
que `Money` redondea a 0,0000 es un precio cero) y unos costes fijos >= 0, ambos finitos: un 422 de dominio
`{"detail": <cadena>}` que no repite lo recibido (con `Field(ge=...)` el 422 de esquema lo repite, y un `NaN` no se
puede escribir en JSON: 500). Un tipo incorrecto sigue siendo el 422 de esquema de siempre. No entra al servicio, no
escribe nada. Un fallo interno de verdad sigue siendo un 500.

`raise_server_exceptions=False`: con el valor por defecto un 500 se vería como excepción dentro del test.
"""

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app

NAN, INF = float("nan"), float("inf")


@pytest.fixture()
def world():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override_get_db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app, raise_server_exceptions=False), session_factory
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def _rows(session_factory) -> dict[str, int]:
    """Filas de **cada** tabla: «no escribe nada» se mide en todas, no en las que se me ocurran."""
    with session_factory() as session:
        return {
            table.name: session.execute(select(func.count()).select_from(table)).scalar_one()
            for table in Base.metadata.sorted_tables
        }


def _product_and_quote(client: TestClient) -> tuple[str, str]:
    research = client.post("/api/research/runs", json={"category": "electronics", "max_results": 1}).json()
    product_id = research["candidates"][0]["product_id"]
    sourcing = client.post(
        "/api/sourcing/runs",
        json={
            "product_id": product_id,
            "category": "electronics",
            "destination_region": "mexico",
            "max_results": 1,
        },
    ).json()
    return product_id, sourcing["quotes"][0]["id"]


def _post(client: TestClient, body: dict):
    """`json.dumps` deja pasar NaN e Infinity, que es lo que Starlette también acepta al leer el cuerpo."""
    return client.post(
        "/api/economics/runs", content=json.dumps(body), headers={"content-type": "application/json"}
    )


def _body(product_id: str, quote_id: str, **overrides) -> dict:
    base = {"product_id": product_id, "supplier_quote_id": quote_id, "sale_price": 20.0, "units_per_order": 1}
    return base | overrides


def _assert_amount_422(response, *wrong: str) -> None:
    """El 422 de dominio de una cantidad fuera de rango: `{"detail": <cadena>}` que nombra exactamente los campos
    dados y no repite lo que mandó el cliente ni nada interno."""
    assert response.status_code == 422
    body = response.json()
    assert set(body) == {"detail"}
    assert isinstance(body["detail"], str)
    for field in ("sale_price", "monthly_fixed_costs"):
        assert (field in body["detail"]) == (field in wrong)
    for leak in ("Traceback", 'File "', "ZeroDivisionError", "ValueError", "InvalidOperation", ".py"):
        assert leak not in response.text


def _assert_schema_422(response, *fields: str) -> None:
    """Un 422 de esquema de FastAPI (tipo incorrecto), sobre exactamente los campos dados, sin nada interno."""
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert isinstance(detail, list)
    assert [error["loc"] for error in detail] == [["body", field] for field in fields]
    for leak in ("Traceback", 'File "', "ZeroDivisionError", "ValueError", "InvalidOperation", ".py"):
        assert leak not in response.text


# ---------------------------------------------------------------------------- sale_price


@pytest.mark.parametrize("price", [20.0, 19.99, 0.01, 0.0001, 0.00005])
def test_a_positive_price_is_accepted_down_to_the_smallest_the_money_type_can_hold(world, price):
    """0,0001 es el menor importe que `Money` guarda (4 decimales); 0,00005 redondea hacia arriba a él."""
    client, _ = world
    product_id, quote_id = _product_and_quote(client)

    response = client.post("/api/economics/runs", json=_body(product_id, quote_id, sale_price=price))

    assert response.status_code == 201
    assert response.json()["sale_price"] == price


@pytest.mark.parametrize(
    "price",
    [
        0,  # el defecto A: ZeroDivisionError => 500
        0.0,
        -0.0,
        -1,  # el defecto B: se aceptaba y se guardaba
        -0.5,
        -0.0001,
        -1e-300,
        0.00004,  # positivo, pero `Money` lo redondea a 0,0000: un precio cero
        1e-7,
        1e-300,
        NAN,
        INF,
        -INF,
        "NaN",  # Pydantic lee estas cadenas como número: tampoco pasan
        "Infinity",
        "-1",
        "0",
    ],
)
def test_a_price_that_is_not_strictly_positive_as_money_is_a_422_and_writes_nothing(world, price):
    client, session_factory = world
    product_id, quote_id = _product_and_quote(client)
    before = _rows(session_factory)

    response = _post(client, _body(product_id, quote_id, sale_price=price))

    _assert_amount_422(response, "sale_price")
    assert _rows(session_factory) == before


@pytest.mark.parametrize("price", ["abc", "", None, [20], {"a": 1}])
def test_a_price_of_the_wrong_type_is_a_422_and_writes_nothing(world, price):
    client, session_factory = world
    product_id, quote_id = _product_and_quote(client)
    before = _rows(session_factory)

    response = _post(client, _body(product_id, quote_id, sale_price=price))

    _assert_schema_422(response, "sale_price")
    assert _rows(session_factory) == before


def test_a_missing_price_is_a_422_and_writes_nothing(world):
    client, session_factory = world
    product_id, quote_id = _product_and_quote(client)
    before = _rows(session_factory)
    body = _body(product_id, quote_id)
    del body["sale_price"]

    response = _post(client, body)

    _assert_schema_422(response, "sale_price")
    assert _rows(session_factory) == before


# ---------------------------------------------------------------------- monthly_fixed_costs


@pytest.mark.parametrize("costs", [0, 0.0, 0.01, 500.5, 12345.67])
def test_fixed_costs_of_zero_or_more_are_accepted_and_kept(world, costs):
    client, _ = world
    product_id, quote_id = _product_and_quote(client)

    response = client.post("/api/economics/runs", json=_body(product_id, quote_id, monthly_fixed_costs=costs))

    assert response.status_code == 201
    assert response.json()["monthly_fixed_costs"] == costs


def test_omitted_fixed_costs_keep_their_declared_default(world):
    client, _ = world
    product_id, quote_id = _product_and_quote(client)

    response = client.post("/api/economics/runs", json=_body(product_id, quote_id))

    assert response.status_code == 201
    assert response.json()["monthly_fixed_costs"] == 500.0


@pytest.mark.parametrize("costs", [-1, -0.01, -0.0001, -1e-300, NAN, INF, -INF, "NaN", "Infinity", "-1"])
def test_negative_or_non_finite_fixed_costs_are_a_422_and_write_nothing(world, costs):
    """Un negativo no representa ingresos, subvenciones ni créditos: sería un coste que resta."""
    client, session_factory = world
    product_id, quote_id = _product_and_quote(client)
    before = _rows(session_factory)

    response = _post(client, _body(product_id, quote_id, monthly_fixed_costs=costs))

    _assert_amount_422(response, "monthly_fixed_costs")
    assert _rows(session_factory) == before


@pytest.mark.parametrize("costs", ["abc", "", None, [500], {"a": 1}])
def test_fixed_costs_of_the_wrong_type_are_a_422_and_write_nothing(world, costs):
    client, session_factory = world
    product_id, quote_id = _product_and_quote(client)
    before = _rows(session_factory)

    response = _post(client, _body(product_id, quote_id, monthly_fixed_costs=costs))

    _assert_schema_422(response, "monthly_fixed_costs")
    assert _rows(session_factory) == before


def test_the_message_does_not_repeat_what_the_client_sent(world):
    client, _ = world
    product_id, quote_id = _product_and_quote(client)

    response = _post(client, _body(product_id, quote_id, sale_price=-987654.321, monthly_fixed_costs=-123456.789))

    _assert_amount_422(response, "sale_price", "monthly_fixed_costs")
    assert "987654" not in response.text
    assert "123456" not in response.text


def test_both_fields_wrong_at_once_report_both_and_write_nothing(world):
    client, session_factory = world
    product_id, quote_id = _product_and_quote(client)
    before = _rows(session_factory)

    response = _post(client, _body(product_id, quote_id, sale_price=0, monthly_fixed_costs=-1))

    _assert_amount_422(response, "sale_price", "monthly_fixed_costs")
    assert _rows(session_factory) == before


# --------------------------------------------------------------------------- determinismo


def test_two_invalid_calls_in_a_row_give_the_same_answer_and_do_not_poison_the_next_valid_one(world):
    client, session_factory = world
    product_id, quote_id = _product_and_quote(client)
    before = _rows(session_factory)

    first = _post(client, _body(product_id, quote_id, sale_price=0))
    second = _post(client, _body(product_id, quote_id, sale_price=0))

    _assert_amount_422(first, "sale_price")
    _assert_amount_422(second, "sale_price")
    assert first.json() == second.json()
    assert _rows(session_factory) == before

    valid = client.post("/api/economics/runs", json=_body(product_id, quote_id, sale_price=20.0))
    assert valid.status_code == 201
    assert client.get(f"/api/economics/runs/{valid.json()['correlation_id']}").status_code == 200


def test_the_valid_run_after_invalid_ones_is_the_only_new_analysis(world):
    client, session_factory = world
    product_id, quote_id = _product_and_quote(client)
    _post(client, _body(product_id, quote_id, sale_price=-1))
    _post(client, _body(product_id, quote_id, monthly_fixed_costs=-1))
    before = _rows(session_factory)

    valid = client.post("/api/economics/runs", json=_body(product_id, quote_id))

    assert valid.status_code == 201
    after = _rows(session_factory)
    assert after["economic_analyses"] == before["economic_analyses"] + 1


# ----------------------------------------------------------------- los fallos internos siguen siéndolo


@pytest.mark.parametrize("failure", [RuntimeError("internal secret detail"), ZeroDivisionError("internal division")])
def test_an_internal_failure_after_valid_input_is_still_a_500_and_never_leaks_its_message(
    world, monkeypatch, failure
):
    """La corrección es la precondición, no un `except`: un fallo nuestro no se disfraza de error del cliente."""
    client, _ = world
    product_id, quote_id = _product_and_quote(client)

    def boom(self, **kwargs):
        raise failure

    monkeypatch.setattr("app.economics.service.EconomicAnalysisService.run_analysis", boom)

    response = client.post("/api/economics/runs", json=_body(product_id, quote_id))

    assert response.status_code == 500
    assert "internal" not in response.text
    assert type(failure).__name__ not in response.text
