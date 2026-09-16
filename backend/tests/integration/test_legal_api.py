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
    research = client.post("/api/research/runs", json={"category": "accessories", "max_results": 1}).json()
    return research["candidates"][0]["product_id"]


def test_create_legal_analysis_run_persists_and_returns_the_report(client: TestClient):
    product_id = _create_product(client)

    response = client.post(
        "/api/legal/runs", json={"product_id": product_id, "market": "eu"}
    )

    assert response.status_code == 201
    body = response.json()
    assert body["recommendation"] in {"GO", "REVIEW", "NO_GO"}
    assert "terms_and_conditions" in body["data"]


def test_get_legal_analysis_run_reconstructs_the_same_result_from_db(client: TestClient):
    product_id = _create_product(client)

    created = client.post("/api/legal/runs", json={"product_id": product_id, "market": "eu"}).json()

    fetched = client.get(f"/api/legal/runs/{created['correlation_id']}")

    assert fetched.status_code == 200
    assert fetched.json() == created


def test_get_legal_analysis_run_404s_for_an_unknown_correlation_id(client: TestClient):
    response = client.get("/api/legal/runs/does-not-exist")

    assert response.status_code == 404


def test_create_legal_analysis_run_404s_for_an_unknown_product(client: TestClient):
    response = client.post(
        "/api/legal/runs", json={"product_id": "does-not-exist", "market": "eu"}
    )

    assert response.status_code == 404


def test_list_product_legal_returns_existing_analyses_for_a_product(client: TestClient):
    product_id = _create_product(client)

    client.post("/api/legal/runs", json={"product_id": product_id, "market": "eu"})

    response = client.get(f"/api/products/{product_id}/legal")

    assert response.status_code == 200
    analyses = response.json()
    assert len(analyses) > 0
    assert all(a["product_id"] == product_id for a in analyses)
