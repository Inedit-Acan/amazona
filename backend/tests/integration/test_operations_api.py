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


def _create_product(client: TestClient) -> str:
    research = client.post("/api/research/runs", json={"category": "home", "max_results": 1}).json()
    return research["candidates"][0]["product_id"]


def test_create_operations_run_persists_and_returns_the_report(client: TestClient):
    product_id = _create_product(client)

    response = client.post("/api/operations/runs", json={"product_id": product_id, "market": "us"})

    assert response.status_code == 201
    body = response.json()
    assert body["operations_status"] in {"READY", "NEEDS_REVIEW", "BLOCKED"}
    assert body["data"]["order"]["tracking"]["stages"]
    assert "support_ticket_example" in body["data"]


def test_get_operations_run_reconstructs_the_same_result_from_db(client: TestClient):
    product_id = _create_product(client)

    created = client.post("/api/operations/runs", json={"product_id": product_id, "market": "us"}).json()

    fetched = client.get(f"/api/operations/runs/{created['correlation_id']}")

    assert fetched.status_code == 200
    assert fetched.json() == created


def test_get_operations_run_404s_for_an_unknown_correlation_id(client: TestClient):
    response = client.get("/api/operations/runs/does-not-exist")

    assert response.status_code == 404


def test_create_operations_run_404s_for_an_unknown_product(client: TestClient):
    response = client.post("/api/operations/runs", json={"product_id": "does-not-exist", "market": "us"})

    assert response.status_code == 404


def test_list_product_operations_returns_existing_runs(client: TestClient):
    product_id = _create_product(client)

    client.post("/api/operations/runs", json={"product_id": product_id, "market": "us"})

    response = client.get(f"/api/products/{product_id}/operations")

    assert response.status_code == 200
    records = response.json()
    assert len(records) > 0
    assert all(item["product_id"] == product_id for item in records)
