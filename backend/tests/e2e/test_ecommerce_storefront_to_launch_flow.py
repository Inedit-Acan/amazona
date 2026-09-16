"""End-to-end Fase 3 (Agentes 1-5) demo: research a category, source
suppliers, run an economic analysis, run a legal analysis, and generate
a storefront draft — verifying both the happy path (everything GO ->
storefront READY) and the blocking path (legal NO_GO -> storefront
BLOCKED, never marked ready to launch on a legally blocked product) —
driven entirely through the public HTTP API, against a clean database.
"""

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


def _run_first_three_agents(client: TestClient, category: str) -> tuple[str, dict]:
    research_run = client.post("/api/research/runs", json={"category": category, "max_results": 5}).json()
    top_candidate = research_run["candidates"][0]
    product_id = top_candidate["product_id"]

    sourcing_run = client.post(
        "/api/sourcing/runs",
        json={
            "product_id": product_id,
            "category": category,
            "destination_region": "mexico",
            "max_results": 5,
        },
    ).json()
    best_quote = sourcing_run["quotes"][0]

    client.post(
        "/api/economics/runs",
        json={"product_id": product_id, "supplier_quote_id": best_quote["id"], "sale_price": 20.0},
    )
    return product_id, best_quote


def test_healthy_chain_produces_a_ready_storefront(client: TestClient):
    product_id, _ = _run_first_three_agents(client, "electronics")

    legal_run = client.post(
        "/api/legal/runs",
        json={"product_id": product_id, "market": "us", "certification_available": True},
    ).json()
    assert legal_run["recommendation"] == "GO"

    ecommerce_response = client.post("/api/ecommerce/runs", json={"product_id": product_id, "market": "us"})
    assert ecommerce_response.status_code == 201
    storefront = ecommerce_response.json()

    assert storefront["launch_status"] == "READY"
    assert storefront["recommendation"] == "GO"
    assert storefront["data"]["catalog_entry"]["price"] == 20.0
    assert storefront["data"]["payment_gateway_plan"]["requires_human_approval"] is True

    # Reconstructable from DB.
    reconstructed = client.get(f"/api/ecommerce/runs/{storefront['correlation_id']}")
    assert reconstructed.status_code == 200
    assert reconstructed.json() == storefront

    product_storefronts = client.get(f"/api/products/{product_id}/storefronts").json()
    assert any(s["correlation_id"] == storefront["correlation_id"] for s in product_storefronts)


def test_restricted_legal_analysis_blocks_the_storefront(client: TestClient):
    product_id, _ = _run_first_three_agents(client, "accessories")

    # accessories/eu is restricted (REACH) in the fixture, no certification held.
    legal_run = client.post("/api/legal/runs", json={"product_id": product_id, "market": "eu"}).json()
    assert legal_run["recommendation"] == "NO_GO"

    ecommerce_response = client.post("/api/ecommerce/runs", json={"product_id": product_id, "market": "eu"})
    assert ecommerce_response.status_code == 201
    storefront = ecommerce_response.json()

    assert storefront["launch_status"] == "BLOCKED"
    assert storefront["recommendation"] == "NO_GO"
    assert any("legal" in risk.lower() for risk in storefront["data"]["risks"])


def test_five_agent_chain_has_five_distinct_traceable_correlation_ids(client: TestClient):
    research_run = client.post("/api/research/runs", json={"category": "electronics", "max_results": 5}).json()
    product_id = research_run["candidates"][0]["product_id"]

    sourcing_run = client.post(
        "/api/sourcing/runs",
        json={
            "product_id": product_id,
            "category": "electronics",
            "destination_region": "mexico",
            "max_results": 5,
        },
    ).json()
    best_quote = sourcing_run["quotes"][0]

    economics_run = client.post(
        "/api/economics/runs",
        json={"product_id": product_id, "supplier_quote_id": best_quote["id"], "sale_price": 20.0},
    ).json()

    legal_run = client.post(
        "/api/legal/runs",
        json={"product_id": product_id, "market": "us", "certification_available": True},
    ).json()

    storefront = client.post("/api/ecommerce/runs", json={"product_id": product_id, "market": "us"}).json()

    correlation_ids = {
        research_run["correlation_id"],
        sourcing_run["correlation_id"],
        economics_run["correlation_id"],
        legal_run["correlation_id"],
        storefront["correlation_id"],
    }
    assert len(correlation_ids) == 5

    ecommerce_audit = client.get("/api/audit", params={"correlation_id": storefront["correlation_id"]}).json()
    assert any(e["action"] == "ecommerce.run" for e in ecommerce_audit)
