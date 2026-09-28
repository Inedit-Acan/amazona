"""Lo que el panel puede decir del gasto (Milestone 37, plan maestro §25).

Lo que estas pruebas protegen: que **no se enseñe un cero inventado**. Un
proveedor que no se ha usado hoy tiene cero llamadas medidas; un coste que el
proveedor todavía no ha comunicado es ausente, y las dos cosas se distinguen.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models.external_api_cost import ExternalApiCost
from app.db.session import get_db
from app.main import app


@pytest.fixture()
def session_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override_get_db():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield factory
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


@pytest.fixture()
def client(session_factory):
    return TestClient(app)


def add_cost(session_factory, **overrides):
    session = session_factory()
    defaults = dict(
        provider="ebay-browse",
        operation="item_summary/search",
        units=1,
        unit="requests",
        estimated_cost=0.0,
        actual_cost=None,
        currency="EUR",
        outcome="allowed",
        denied_reason=None,
        correlation_id="cid-1",
    )
    session.add(ExternalApiCost(**{**defaults, **overrides}))
    session.commit()
    session.close()


def usage_of(client: TestClient, provider: str) -> dict:
    body = client.get("/api/costs/api-usage").json()
    return next(row for row in body if row["provider"] == provider)


def test_every_provider_with_a_policy_is_listed(client: TestClient):
    """Un proveedor ausente de la lista se confundiría con uno sin política."""
    providers = {row["provider"] for row in client.get("/api/costs/api-usage").json()}

    assert {"wikimedia-pageviews", "ebay-browse", "fixtures"} <= providers


def test_an_unused_provider_shows_a_measured_zero(client: TestClient):
    row = usage_of(client, "ebay-browse")

    assert row["units_today"] == 0
    assert row["denied_today"] == 0
    assert row["last_denied_reason"] is None


def test_what_the_provider_has_not_charged_yet_is_absent_not_zero(client, session_factory):
    add_cost(session_factory, units=3)

    row = usage_of(client, "ebay-browse")

    assert row["units_today"] == 3
    assert row["estimated_cost_today"] == 0.0
    # Nulo, no cero: el proveedor todavía no ha dicho lo que cobró.
    assert row["actual_cost_today"] is None


def test_a_denial_is_visible_with_its_reason(client, session_factory):
    """Sin esto, una investigación sin señales parecería una avería."""
    add_cost(
        session_factory,
        outcome="denied",
        denied_reason="ebay-browse cobra por uso y no tiene límite de gasto autorizado",
    )

    row = usage_of(client, "ebay-browse")

    assert row["denied_today"] == 1
    assert "límite de gasto autorizado" in row["last_denied_reason"]


def test_denied_calls_do_not_count_as_consumed(client, session_factory):
    add_cost(session_factory, units=2, outcome="allowed")
    add_cost(session_factory, units=5, outcome="denied", denied_reason="sin cuota")

    row = usage_of(client, "ebay-browse")

    assert row["units_today"] == 2


def test_the_published_quota_and_our_own_cap_are_both_visible(client: TestClient):
    """Son cosas distintas: una la pone el proveedor y la otra el arriendo del
    runtime (ADR 0009)."""
    row = usage_of(client, "ebay-browse")

    assert row["quota_units_per_day"] == 5000
    assert row["max_units_per_run"] == 8


def test_with_no_authorised_budget_the_limits_are_absent(client: TestClient):
    """Presupuesto del Milestone 37: 0 €. Nada autorizado, y se dice con nulos en
    vez de con ceros, que se leerían como «autorizado cero»."""
    row = usage_of(client, "ebay-browse")

    assert row["authorised_cost_per_day"] is None
    assert row["authorised_cost_per_run"] is None


def test_each_row_says_where_its_numbers_were_checked(client: TestClient):
    for row in client.get("/api/costs/api-usage").json():
        assert row["source"]


def test_free_is_reported_as_free_and_not_as_unlimited(client: TestClient):
    row = usage_of(client, "wikimedia-pageviews")

    assert row["pricing"] == "free"
    assert row["unit"] == "requests"
