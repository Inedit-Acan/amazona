"""La procedencia en la frontera de `POST /api/exchange-rates` (M46, Commit 5b).

Antes: `ExchangeRateCreate.provenance` era una cadena libre y el endpoint hacía `SupplierFactProvenance(valor)`: un
valor fuera del enum lanzaba un `ValueError` del enum que ningún manejador traducía (500).

Ahora el esquema usa el enum canónico `SupplierFactProvenance`: un valor fuera de él es un 422 de FastAPI antes de
entrar en el endpoint. Se compara tal cual: no se normaliza, no se sustituye por un valor por defecto y no se infiere.
`unknown` está en el enum pero el dominio (`ExchangeRate`) ya lo rechaza —«una tasa que nadie sostiene»—: sigue
siendo su 422 de dominio, con su mensaje. Un fallo interno de verdad sigue siendo un 500.

`raise_server_exceptions=False`: con el valor por defecto un 500 se vería como excepción dentro del test.
"""

import datetime
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models.exchange_rate import ExchangeRate as ExchangeRateRow
from app.db.session import get_db
from app.main import app
from app.sourcing.provenance import STORABLE, SupplierFactProvenance


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


def _stored_provenances(session_factory) -> list[str]:
    with session_factory() as session:
        return [row.provenance for row in session.scalars(select(ExchangeRateRow))]


def _body(**overrides) -> dict:
    base = {
        "base_currency": "USD",
        "quote_currency": "EUR",
        "rate": "0.92",
        "effective_date": (datetime.datetime.now(datetime.UTC).date() - datetime.timedelta(days=1)).isoformat(),
    }
    body = base | overrides
    return {key: value for key, value in body.items() if value != "__omit__"}


def _post(client: TestClient, body: dict):
    return client.post("/api/exchange-rates", content=json.dumps(body), headers={"content-type": "application/json"})


def _assert_enum_422(response) -> None:
    """Un 422 de esquema de FastAPI sobre `provenance`, sin nada interno."""
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert isinstance(detail, list)
    assert [error["loc"] for error in detail] == [["body", "provenance"]]
    for leak in ("Traceback", 'File "', "ValueError", "SupplierFactProvenance", ".py"):
        assert leak not in response.text


STORABLE_WITHOUT_ISSUER = sorted(p.value for p in STORABLE if p is not SupplierFactProvenance.THIRD_PARTY_VERIFIED)


def test_the_enum_has_the_values_these_tests_expect():
    """Si alguien añade un valor al enum canónico, estas listas dejan de cubrirlo y hay que mirarlas."""
    assert {p.value for p in SupplierFactProvenance} == {
        "third_party_verified",
        "supplier_claim",
        "declared",
        "amazona_estimate",
        "simulated",
        "unknown",
    }
    assert STORABLE_WITHOUT_ISSUER == ["amazona_estimate", "declared", "simulated", "supplier_claim"]


@pytest.mark.parametrize("provenance", STORABLE_WITHOUT_ISSUER)
def test_every_storable_provenance_is_accepted_and_stored_as_written(world, provenance):
    client, session_factory = world

    response = _post(client, _body(provenance=provenance))

    assert response.status_code == 201
    assert response.json()["provenance"] == provenance
    assert _stored_provenances(session_factory) == [provenance]


def test_a_third_party_provenance_with_its_issuer_is_accepted(world):
    client, session_factory = world

    response = _post(client, _body(provenance="third_party_verified", declared_by="Banco de prueba"))

    assert response.status_code == 201
    assert response.json()["provenance"] == "third_party_verified"
    assert _stored_provenances(session_factory) == ["third_party_verified"]


def test_an_omitted_provenance_keeps_its_declared_default(world):
    client, session_factory = world

    response = _post(client, _body(provenance="__omit__"))

    assert response.status_code == 201
    assert response.json()["provenance"] == "declared"
    assert _stored_provenances(session_factory) == ["declared"]


def test_unknown_is_in_the_enum_but_keeps_its_own_domain_422_and_writes_nothing(world):
    """No hay una segunda lista: el esquema acepta el enum entero y el dominio decide qué se puede guardar."""
    client, session_factory = world
    before = _rows(session_factory)

    response = _post(client, _body(provenance="unknown"))

    assert response.status_code == 422
    assert isinstance(response.json()["detail"], str)
    assert "cannot be declared unknown" in response.json()["detail"]
    assert _rows(session_factory) == before


def test_a_third_party_provenance_without_issuer_keeps_its_own_domain_422(world):
    client, session_factory = world
    before = _rows(session_factory)

    response = _post(client, _body(provenance="third_party_verified"))

    assert response.status_code == 422
    assert "must name the issuer" in response.json()["detail"]
    assert _rows(session_factory) == before


@pytest.mark.parametrize(
    "provenance",
    [
        "nope",  # el defecto C: ValueError => 500
        "",
        "DECLARED",  # el contrato distingue mayúsculas: no se normaliza
        "Declared",
        "SIMULATED",
        " declared",  # los espacios no se recortan
        "declared ",
        " declared ",
        "declared\n",
        "declared\x00",
        "third-party-verified",
        "third_party_verified ",
        "declare",
        "declared,simulated",
    ],
)
def test_a_provenance_outside_the_enum_is_a_422_before_the_endpoint_and_writes_nothing(world, provenance):
    client, session_factory = world
    before = _rows(session_factory)

    response = _post(client, _body(provenance=provenance))

    _assert_enum_422(response)
    assert _rows(session_factory) == before
    assert _stored_provenances(session_factory) == []  # ni normalizada ni sustituida por «declared»


@pytest.mark.parametrize("provenance", [None, 5, 1.5, True, [], ["declared"], {}, {"value": "declared"}])
def test_a_provenance_of_the_wrong_type_is_a_422_and_writes_nothing(world, provenance):
    client, session_factory = world
    before = _rows(session_factory)

    response = _post(client, _body(provenance=provenance))

    _assert_enum_422(response)
    assert _rows(session_factory) == before


def test_an_incomplete_payload_is_a_422_and_writes_nothing(world):
    client, session_factory = world
    before = _rows(session_factory)

    response = _post(client, {"provenance": "declared"})

    assert response.status_code == 422
    assert {error["loc"][-1] for error in response.json()["detail"]} >= {
        "base_currency",
        "quote_currency",
        "rate",
        "effective_date",
    }
    assert _rows(session_factory) == before


def test_two_invalid_calls_in_a_row_give_the_same_answer_and_do_not_poison_the_next_valid_one(world):
    client, session_factory = world
    before = _rows(session_factory)

    first = _post(client, _body(provenance="nope"))
    second = _post(client, _body(provenance="nope"))

    _assert_enum_422(first)
    _assert_enum_422(second)
    assert first.json() == second.json()
    assert _rows(session_factory) == before

    valid = _post(client, _body(provenance="declared"))
    assert valid.status_code == 201
    listed = client.get("/api/exchange-rates").json()
    assert [rate["provenance"] for rate in listed] == ["declared"]


@pytest.mark.parametrize("failure", [RuntimeError("internal secret detail"), ValueError("internal value detail")])
def test_an_internal_failure_after_valid_input_is_still_a_500_and_never_leaks_its_message(
    world, monkeypatch, failure
):
    """Ni un `RuntimeError` ni un `ValueError` internos se disfrazan de error del cliente."""
    client, session_factory = world
    before = _rows(session_factory)

    def boom(**kwargs):
        raise failure

    monkeypatch.setattr("app.api.economics.ExchangeRate", boom)

    response = _post(client, _body(provenance="declared"))

    assert response.status_code == 500
    assert "internal" not in response.text
    assert type(failure).__name__ not in response.text
    assert _rows(session_factory) == before
