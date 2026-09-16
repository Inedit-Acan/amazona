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


def test_create_research_run_persists_and_returns_ranked_candidates(client: TestClient):
    response = client.post("/api/research/runs", json={"category": "electronics", "max_results": 3})

    assert response.status_code == 201
    body = response.json()
    assert 1 <= len(body["candidates"]) <= 3
    scores = [c["opportunity_score"] for c in body["candidates"]]
    assert scores == sorted(scores, reverse=True)


def test_get_research_run_reconstructs_the_same_result_from_db(client: TestClient):
    created = client.post("/api/research/runs", json={"category": "home", "max_results": 5}).json()

    fetched = client.get(f"/api/research/runs/{created['correlation_id']}")

    assert fetched.status_code == 200
    assert fetched.json()["candidates"] == created["candidates"]


def test_get_research_run_404s_for_an_unknown_correlation_id(client: TestClient):
    response = client.get("/api/research/runs/does-not-exist")

    assert response.status_code == 404


def test_products_endpoint_lists_research_candidates_by_status(client: TestClient):
    client.post("/api/research/runs", json={"category": "accessories", "max_results": 5})

    response = client.get("/api/products", params={"status": "CANDIDATE"})

    assert response.status_code == 200
    products = response.json()
    assert len(products) > 0
    assert all(p["status"] == "CANDIDATE" for p in products)
    assert all(p["source"] == "research" for p in products)
