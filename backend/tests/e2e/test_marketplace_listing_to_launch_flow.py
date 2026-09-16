"""End-to-end Fase 3 (Agentes 1-6) demo: research a category, source
suppliers, run economic and legal analyses, generate a storefront, and
generate a marketplace listing — verifying the happy path (everything
GO -> listing READY, with competition data explicitly tagged
data_origin="simulated_not_sp_api" per the project's Amazon SP-API data
policy) and the review path (a category requiring platform approval ->
listing NEEDS_REVIEW) — driven entirely through the public HTTP API,
against a clean database.
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


def _run_first_four_agents(client: TestClient, category: str, market: str) -> str:
    research_run = client.post("/api/research/runs", json={"category": category, "max_results": 5}).json()
    product_id = research_run["candidates"][0]["product_id"]

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
    client.post(
        "/api/legal/runs",
        json={"product_id": product_id, "market": market, "certification_available": True},
    )
    client.post("/api/ecommerce/runs", json={"product_id": product_id, "market": market})
    return product_id


def test_healthy_chain_with_no_approval_needed_produces_a_ready_listing(client: TestClient):
    product_id = _run_first_four_agents(client, category="home", market="us")

    response = client.post(
        "/api/marketplace/runs", json={"product_id": product_id, "market": "us", "platform": "amazon"}
    )
    assert response.status_code == 201
    listing = response.json()

    assert listing["listing_status"] == "READY"
    assert listing["recommendation"] == "GO"
    assert listing["storefront_id"] is not None
    assert listing["data"]["competition_analysis"]["data_origin"] == "simulated_not_sp_api"
    assert listing["data"]["commission_breakdown"]["net_margin_per_unit"] is not None
    assert listing["data"]["inventory_policy"]["tracking_enabled"] is False

    reconstructed = client.get(f"/api/marketplace/runs/{listing['correlation_id']}")
    assert reconstructed.status_code == 200
    assert reconstructed.json() == listing

    product_listings = client.get(f"/api/products/{product_id}/marketplace-listings").json()
    assert any(item["correlation_id"] == listing["correlation_id"] for item in product_listings)


def test_category_requiring_platform_approval_needs_review(client: TestClient):
    # electronics/amazon requires category approval in the fixture.
    product_id = _run_first_four_agents(client, category="electronics", market="us")

    response = client.post(
        "/api/marketplace/runs", json={"product_id": product_id, "market": "us", "platform": "amazon"}
    )
    assert response.status_code == 201
    listing = response.json()

    assert listing["listing_status"] == "NEEDS_REVIEW"
    assert listing["recommendation"] == "REVIEW"
    assert any("approval" in note.lower() for note in listing["data"]["policy"]["notes"])


def test_six_agent_chain_has_six_distinct_traceable_correlation_ids(client: TestClient):
    research_run = client.post("/api/research/runs", json={"category": "home", "max_results": 5}).json()
    product_id = research_run["candidates"][0]["product_id"]

    sourcing_run = client.post(
        "/api/sourcing/runs",
        json={"product_id": product_id, "category": "home", "destination_region": "mexico", "max_results": 5},
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

    ecommerce_run = client.post("/api/ecommerce/runs", json={"product_id": product_id, "market": "us"}).json()

    marketplace_run = client.post(
        "/api/marketplace/runs", json={"product_id": product_id, "market": "us", "platform": "amazon"}
    ).json()

    correlation_ids = {
        research_run["correlation_id"],
        sourcing_run["correlation_id"],
        economics_run["correlation_id"],
        legal_run["correlation_id"],
        ecommerce_run["correlation_id"],
        marketplace_run["correlation_id"],
    }
    assert len(correlation_ids) == 6

    marketplace_audit = client.get(
        "/api/audit", params={"correlation_id": marketplace_run["correlation_id"]}
    ).json()
    assert any(e["action"] == "marketplace.run" for e in marketplace_audit)
