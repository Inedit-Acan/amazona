import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app


@pytest.fixture()
def client():
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
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def test_create_pipeline_run_completes_all_nine_steps(client: TestClient):
    response = client.post(
        "/api/pipeline/runs",
        json={"category": "home", "sale_price": 50.0, "destination_region": "mexico"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "COMPLETED"
    assert body["product_id"] is not None
    assert set(body["steps"].keys()) == {
        "research",
        "sourcing",
        "economics",
        "legal",
        "ecommerce",
        "marketplace",
        "marketing",
        "operations",
        "cfo",
    }


def test_create_pipeline_run_is_partial_for_an_unknown_category(client: TestClient):
    response = client.post(
        "/api/pipeline/runs",
        json={"category": "does-not-exist", "sale_price": 50.0, "destination_region": "mexico"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "PARTIAL"
    assert body["failed_step"] == "research"


def test_get_pipeline_run_reconstructs_the_same_result_from_db(client: TestClient):
    created = client.post(
        "/api/pipeline/runs",
        json={"category": "home", "sale_price": 50.0, "destination_region": "mexico"},
    ).json()

    fetched = client.get(f"/api/pipeline/runs/{created['correlation_id']}")

    assert fetched.status_code == 200
    assert fetched.json() == created


def test_get_pipeline_run_404s_for_an_unknown_correlation_id(client: TestClient):
    response = client.get("/api/pipeline/runs/does-not-exist")

    assert response.status_code == 404


def test_list_pipeline_runs_returns_existing_runs_most_recent_first(client: TestClient):
    first = client.post(
        "/api/pipeline/runs",
        json={"category": "home", "sale_price": 50.0, "destination_region": "mexico"},
    ).json()
    second = client.post(
        "/api/pipeline/runs",
        json={"category": "electronics", "sale_price": 50.0, "destination_region": "mexico"},
    ).json()

    response = client.get("/api/pipeline/runs")

    assert response.status_code == 200
    correlation_ids = [item["correlation_id"] for item in response.json()]
    assert correlation_ids.index(second["correlation_id"]) < correlation_ids.index(first["correlation_id"])
