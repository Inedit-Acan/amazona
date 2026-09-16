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
    run = client.post("/api/research/runs", json={"category": "electronics", "max_results": 1}).json()
    return run["candidates"][0]["product_id"]


def test_create_sourcing_run_persists_and_returns_ranked_quotes(client: TestClient):
    product_id = _create_product(client)

    response = client.post(
        "/api/sourcing/runs",
        json={
            "product_id": product_id,
            "category": "electronics",
            "destination_region": "mexico",
            "max_results": 3,
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert 1 <= len(body["quotes"]) <= 3
    costs = [q["total_landed_cost_per_unit"] for q in body["quotes"]]
    assert costs == sorted(costs)


def test_get_sourcing_run_reconstructs_the_same_result_from_db(client: TestClient):
    product_id = _create_product(client)
    created = client.post(
        "/api/sourcing/runs",
        json={
            "product_id": product_id,
            "category": "electronics",
            "destination_region": "mexico",
            "max_results": 3,
        },
    ).json()

    fetched = client.get(f"/api/sourcing/runs/{created['correlation_id']}")

    assert fetched.status_code == 200
    assert fetched.json()["quotes"] == created["quotes"]


def test_get_sourcing_run_404s_for_an_unknown_correlation_id(client: TestClient):
    response = client.get("/api/sourcing/runs/does-not-exist")

    assert response.status_code == 404


def test_create_sourcing_run_404s_for_an_unknown_product(client: TestClient):
    response = client.post(
        "/api/sourcing/runs",
        json={
            "product_id": "does-not-exist",
            "category": "electronics",
            "destination_region": "mexico",
            "max_results": 3,
        },
    )

    assert response.status_code == 404


def test_list_product_suppliers_returns_existing_quotes_for_a_product(client: TestClient):
    product_id = _create_product(client)
    client.post(
        "/api/sourcing/runs",
        json={
            "product_id": product_id,
            "category": "electronics",
            "destination_region": "mexico",
            "max_results": 3,
        },
    )

    response = client.get(f"/api/products/{product_id}/suppliers")

    assert response.status_code == 200
    quotes = response.json()
    assert len(quotes) > 0
    assert all(q["product_id"] == product_id for q in quotes)
