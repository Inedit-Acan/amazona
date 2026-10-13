"""La frontera de entrada de `POST /api/economics/runs` para el canal (M46, Commit 5).

Un canal que el catálogo no declara es un error de quien llama: 422, cuerpo estable, sin traceback y sin
escribir nada. Antes salía como un 500 porque `UnknownChannelError` es un `ValueError` suelto y ningún
manejador la traducía.

Estas pruebas usan `raise_server_exceptions=False`: con el valor por defecto, un 500 del servidor se
convierte en una excepción dentro del propio test y no se vería el código HTTP que recibe el cliente.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.integrations.channels import CHANNELS, UnknownChannelError
from app.main import app


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
    """Cuántas filas hay en **cada** tabla: «no escribe nada» se mide en todas, no en las que se me ocurran."""
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


def _body(product_id: str, quote_id: str, **overrides) -> dict:
    base = {"product_id": product_id, "supplier_quote_id": quote_id, "sale_price": 20.0, "units_per_order": 1}
    return base | overrides


def _assert_clean_domain_422(response) -> None:
    assert response.status_code == 422
    body = response.json()
    assert set(body) == {"detail"}
    assert isinstance(body["detail"], str)
    # Ni el nombre de la clase interna, ni un traceback, ni una ruta del servidor.
    for leak in ("UnknownChannelError", "Traceback", 'File "', "app/", "app\\", ".py"):
        assert leak not in response.text


TRANSACTIONAL = sorted(key for key, channel in CHANNELS.items() if channel.transactional)
NOT_TRANSACTIONAL = sorted(key for key, channel in CHANNELS.items() if not channel.transactional)


def test_the_catalogue_has_both_kinds_of_channel_so_the_two_tests_below_are_not_empty():
    assert "own_web" in TRANSACTIONAL
    assert NOT_TRANSACTIONAL


@pytest.mark.parametrize("channel", TRANSACTIONAL)
def test_every_declared_transactional_channel_is_accepted_and_kept_as_written(world, channel):
    client, _ = world
    product_id, quote_id = _product_and_quote(client)

    response = client.post("/api/economics/runs", json=_body(product_id, quote_id, channel=channel))

    assert response.status_code == 201
    assert response.json()["channel"] == channel


@pytest.mark.parametrize("channel", NOT_TRANSACTIONAL)
def test_a_declared_but_not_transactional_channel_keeps_its_own_422_and_writes_nothing(world, channel):
    """No es el error de este commit: ya era un 422 del dominio. Se fija para que nadie lo confunda con
    «canal desconocido» ni lo deje pasar: ahí se descubre demanda, no se vende."""
    client, session_factory = world
    product_id, quote_id = _product_and_quote(client)
    before = _rows(session_factory)

    response = client.post("/api/economics/runs", json=_body(product_id, quote_id, channel=channel))

    assert response.status_code == 422
    assert "not a transactional channel" in response.json()["detail"]
    assert "Traceback" not in response.text
    assert _rows(session_factory) == before


def test_a_request_without_channel_still_uses_the_declared_default(world):
    client, _ = world
    product_id, quote_id = _product_and_quote(client)

    response = client.post("/api/economics/runs", json=_body(product_id, quote_id))

    assert response.status_code == 201
    assert response.json()["channel"] == "own_web"


@pytest.mark.parametrize(
    "channel",
    [
        "lo-que-sea",  # un typo cualquiera
        "marketplace:amazonn",  # un typo sobre un canal que existe
        "marketplace:",  # prefijo sin plataforma
        "marketplace",  # sin el separador
        "",  # vacío
        "OWN_WEB",  # el contrato distingue mayúsculas: no se normaliza
        "Own_Web",
        " own_web",  # los espacios no se recortan
        "own_web ",
        " own_web ",
        "own_web\n",
        "own web",
        "own_web\x00",
    ],
)
def test_an_undeclared_channel_is_a_422_with_a_stable_body_and_writes_nothing(world, channel):
    client, session_factory = world
    product_id, quote_id = _product_and_quote(client)
    before = _rows(session_factory)

    response = client.post("/api/economics/runs", json=_body(product_id, quote_id, channel=channel))

    _assert_clean_domain_422(response)
    assert "no channel called" in response.json()["detail"]
    assert _rows(session_factory) == before


def test_the_message_names_the_declared_channels_so_the_client_can_correct_itself(world):
    client, _ = world
    product_id, quote_id = _product_and_quote(client)

    detail = client.post(
        "/api/economics/runs", json=_body(product_id, quote_id, channel="lo-que-sea")
    ).json()["detail"]

    assert all(key in detail for key in CHANNELS)


@pytest.mark.parametrize("channel", [5, None, ["own_web"], {"key": "own_web"}, True, 1.5])
def test_a_channel_of_the_wrong_type_is_a_422_from_the_schema_and_writes_nothing(world, channel):
    client, session_factory = world
    product_id, quote_id = _product_and_quote(client)
    before = _rows(session_factory)

    response = client.post("/api/economics/runs", json=_body(product_id, quote_id, channel=channel))

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "channel"]
    assert "Traceback" not in response.text
    assert _rows(session_factory) == before


def test_an_incomplete_payload_is_a_422_and_writes_nothing(world):
    client, session_factory = world
    product_id, _ = _product_and_quote(client)
    before = _rows(session_factory)

    response = client.post("/api/economics/runs", json={"product_id": product_id})

    assert response.status_code == 422
    assert {error["loc"][-1] for error in response.json()["detail"]} >= {"supplier_quote_id", "sale_price"}
    assert _rows(session_factory) == before


def test_two_invalid_calls_in_a_row_give_the_same_answer_and_do_not_poison_the_next_valid_one(world):
    client, session_factory = world
    product_id, quote_id = _product_and_quote(client)
    before = _rows(session_factory)

    first = client.post("/api/economics/runs", json=_body(product_id, quote_id, channel="lo-que-sea"))
    second = client.post("/api/economics/runs", json=_body(product_id, quote_id, channel="lo-que-sea"))

    _assert_clean_domain_422(first)
    _assert_clean_domain_422(second)
    assert first.json() == second.json()
    assert _rows(session_factory) == before

    valid = client.post("/api/economics/runs", json=_body(product_id, quote_id, channel="own_web"))
    assert valid.status_code == 201
    assert client.get(f"/api/economics/runs/{valid.json()['correlation_id']}").status_code == 200


def test_an_invalid_channel_does_not_hide_a_missing_product_or_quote(world):
    """El canal se comprueba primero, pero un producto inexistente con canal válido sigue siendo un 404."""
    client, session_factory = world
    before = _rows(session_factory)

    response = client.post(
        "/api/economics/runs",
        json={"product_id": "nope", "supplier_quote_id": "nope", "sale_price": 20.0, "channel": "own_web"},
    )

    assert response.status_code == 404
    assert _rows(session_factory) == before


def test_an_internal_failure_is_still_a_500_and_never_leaks_its_message(world, monkeypatch):
    """La traducción es solo del canal desconocido: no es un «todo error es culpa del cliente»."""
    client, _ = world
    product_id, quote_id = _product_and_quote(client)

    def boom(self, **kwargs):
        raise RuntimeError("internal secret detail")

    monkeypatch.setattr("app.economics.service.EconomicAnalysisService.run_analysis", boom)

    response = client.post("/api/economics/runs", json=_body(product_id, quote_id, channel="own_web"))

    assert response.status_code == 500
    assert "internal secret detail" not in response.text
    assert "RuntimeError" not in response.text


def test_an_unknown_channel_raised_inside_the_service_for_a_valid_request_is_still_a_500(world, monkeypatch):
    """Si el cliente mandó un canal declarado y el fallo es nuestro, no se le echa la culpa al cliente."""
    client, _ = world
    product_id, quote_id = _product_and_quote(client)

    def internal_typo(key):
        raise UnknownChannelError(f"no channel called {key!r}; an adapter of ours misspelled it")

    monkeypatch.setattr("app.economics.service.channel_for", internal_typo)

    response = client.post("/api/economics/runs", json=_body(product_id, quote_id, channel="own_web"))

    assert response.status_code == 500
    assert "misspelled" not in response.text
