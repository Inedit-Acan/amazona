"""Las rutas que salen a una fuente externa no vuelven a salir al reintentar con la misma clave (ADR 0025).

Una consulta a la fuente gasta cuota y se anota en el contador de coste: un reintento tras un timeout (o un doble clic)
no debe repetirla. Las fuentes son falsas y cuentan cuántas veces se les pregunta; ninguna prueba toca la red.
"""

import datetime

import pytest
from ecb_test_support import ADMITTED, FakeFeed, rate_set, real_settings
from fastapi.testclient import TestClient
from regulatory_test_support import GPSR, FakeSource, anchor
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.db.base import Base
from app.db.models.idempotency_record import IdempotencyRecord
from app.db.session import get_db
from app.integrations.fx.ecb import FeedUnavailableError
from app.legal.regulatory import RegulatoryService
from app.main import app
from app.money.fx_refresh import FxRefreshService

TODAY = datetime.datetime.now(datetime.UTC).date()
YESTERDAY = TODAY - datetime.timedelta(days=1)
REQUIREMENT = {
    "product_scope": "Toys",
    "jurisdiction": "eu",
    "celex": GPSR,
    "regulation": "General Product Safety Regulation",
    "requirement": "A documented safety assessment must exist",
    "kind": "obligation",
}


@pytest.fixture()
def session_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, expire_on_commit=False)
    engine.dispose()


@pytest.fixture()
def client(session_factory):
    def override_get_db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_settings, None)


def use_feed(monkeypatch, feed: FakeFeed) -> None:
    monkeypatch.setattr(
        "app.api.economics.FxRefreshService", lambda db: FxRefreshService(db, real_settings(), feed=feed)
    )


def stored_keys(session_factory) -> int:
    with session_factory() as db:
        return db.query(IdempotencyRecord).count()


# --- Tipos de cambio ----------------------------------------------------------------


def test_a_retried_refresh_does_not_go_back_to_the_source(client, monkeypatch):
    feed = FakeFeed(daily=rate_set(YESTERDAY))
    use_feed(monkeypatch, feed)

    first = client.post("/api/exchange-rates/refresh", headers={"Idempotency-Key": "fx-1"})
    second = client.post("/api/exchange-rates/refresh", headers={"Idempotency-Key": "fx-1"})

    assert first.status_code == second.status_code == 200
    assert second.json() == first.json()
    assert first.json()["stored"] == len(ADMITTED)  # la segunda no recalcula «0 guardadas»: es la original
    assert second.headers["Idempotency-Replayed"] == "true"
    assert feed.daily_calls == 1


def test_without_a_key_every_refresh_still_asks_the_source(client, monkeypatch):
    feed = FakeFeed(daily=rate_set(YESTERDAY))
    use_feed(monkeypatch, feed)

    client.post("/api/exchange-rates/refresh")
    client.post("/api/exchange-rates/refresh")

    assert feed.daily_calls == 2


def test_refresh_and_backfill_do_not_share_a_key(client, monkeypatch):
    feed = FakeFeed(daily=rate_set(YESTERDAY), history=[rate_set(YESTERDAY)])
    use_feed(monkeypatch, feed)

    refresh = client.post("/api/exchange-rates/refresh", headers={"Idempotency-Key": "same"})
    backfill = client.post("/api/exchange-rates/backfill", headers={"Idempotency-Key": "same"})

    assert refresh.json()["mode"] == "daily"
    assert backfill.json()["mode"] == "backfill"
    assert (feed.daily_calls, feed.history_calls) == (1, 1)


def test_a_source_that_did_not_answer_leaves_the_key_free_for_the_retry(client, session_factory, monkeypatch):
    feed = FakeFeed(daily=FeedUnavailableError("down"))
    use_feed(monkeypatch, feed)

    failed = client.post("/api/exchange-rates/refresh", headers={"Idempotency-Key": "fx-2"})
    assert failed.status_code == 502
    assert stored_keys(session_factory) == 0  # no se guardó nada: la clave vuelve a servir

    feed.daily = rate_set(YESTERDAY)  # la fuente se recupera
    retry = client.post("/api/exchange-rates/refresh", headers={"Idempotency-Key": "fx-2"})

    assert retry.status_code == 200
    assert feed.daily_calls == 2


def test_a_deployment_that_can_reach_the_source_needs_the_key(client, monkeypatch):
    use_feed(monkeypatch, FakeFeed(daily=rate_set(YESTERDAY)))
    app.dependency_overrides[get_settings] = lambda: real_settings()

    response = client.post("/api/exchange-rates/refresh")

    assert response.status_code == 428


# --- Regulatorio ---------------------------------------------------------------------


@pytest.fixture()
def source(monkeypatch):
    fake = FakeSource({GPSR: anchor(GPSR, when=datetime.datetime.now(datetime.UTC))})
    monkeypatch.setattr(RegulatoryService, "_resolve_source", lambda self, correlation_id: fake)
    return fake


def test_a_retried_verification_does_not_ask_the_regulatory_source_again(client, source):
    requirement = client.post("/api/regulatory-requirements", json=REQUIREMENT).json()
    url = f"/api/regulatory-requirements/{requirement['id']}/verify"

    first = client.post(url, headers={"Idempotency-Key": "v-1"})
    second = client.post(url, headers={"Idempotency-Key": "v-1"})

    assert first.status_code == second.status_code == 200
    assert second.json() == first.json()
    assert second.headers["Idempotency-Replayed"] == "true"
    assert source.asked == [GPSR]


def test_the_same_key_for_another_requirement_is_a_conflict(client, source):
    first = client.post("/api/regulatory-requirements", json=REQUIREMENT).json()
    second = client.post("/api/regulatory-requirements", json={**REQUIREMENT, "requirement": "Another one"}).json()
    client.post(f"/api/regulatory-requirements/{first['id']}/verify", headers={"Idempotency-Key": "v-2"})

    other = client.post(f"/api/regulatory-requirements/{second['id']}/verify", headers={"Idempotency-Key": "v-2"})

    assert other.status_code == 409
    assert source.asked == [GPSR]


def test_verifying_something_that_does_not_exist_leaves_the_key_free(client, session_factory):
    response = client.post("/api/regulatory-requirements/nope/verify", headers={"Idempotency-Key": "v-3"})

    assert response.status_code == 404
    assert stored_keys(session_factory) == 0
