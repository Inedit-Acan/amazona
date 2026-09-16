"""End-to-end Milestone 10 (Agente CFO) demo: run the economics agent
(Agente 3) for several products with a mix of GO and NO_GO outcomes, add a
marketing campaign, then generate a catalog-wide CFO financial-health
report and verify it reflects everything real that was persisted — driven
entirely through the public HTTP API, against a clean database."""

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


def _research_and_source(client: TestClient, category: str) -> tuple[str, str]:
    research_run = client.post("/api/research/runs", json={"category": category, "max_results": 5}).json()
    product_id = research_run["candidates"][0]["product_id"]
    sourcing_run = client.post(
        "/api/sourcing/runs",
        json={"product_id": product_id, "category": category, "destination_region": "mexico", "max_results": 5},
    ).json()
    return product_id, sourcing_run["quotes"][0]["id"]


def test_cfo_report_aggregates_a_mixed_catalog(client: TestClient):
    # Two GO products, one NO_GO product (sale price below landed cost).
    correlation_ids = set()

    product_go_1, quote_go_1 = _research_and_source(client, "home")
    econ_go_1 = client.post(
        "/api/economics/runs",
        json={"product_id": product_go_1, "supplier_quote_id": quote_go_1, "sale_price": 50.0},
    ).json()
    assert econ_go_1["recommendation"] == "GO"
    correlation_ids.add(econ_go_1["correlation_id"])

    product_go_2, quote_go_2 = _research_and_source(client, "accessories")
    econ_go_2 = client.post(
        "/api/economics/runs",
        json={"product_id": product_go_2, "supplier_quote_id": quote_go_2, "sale_price": 50.0},
    ).json()
    assert econ_go_2["recommendation"] == "GO"
    correlation_ids.add(econ_go_2["correlation_id"])

    product_no_go, quote_no_go = _research_and_source(client, "home")
    econ_no_go = client.post(
        "/api/economics/runs",
        json={"product_id": product_no_go, "supplier_quote_id": quote_no_go, "sale_price": 1.0},
    ).json()
    assert econ_no_go["recommendation"] == "NO_GO"
    correlation_ids.add(econ_no_go["correlation_id"])

    client.post(
        "/api/legal/runs",
        json={"product_id": product_go_1, "market": "us", "certification_available": True},
    )
    client.post("/api/ecommerce/runs", json={"product_id": product_go_1, "market": "us"})
    client.post(
        "/api/marketplace/runs", json={"product_id": product_go_1, "market": "us", "platform": "amazon"}
    )
    marketing_run = client.post(
        "/api/marketing/runs",
        json={"product_id": product_go_1, "market": "us", "platform": "google", "daily_budget": 20.0},
    ).json()
    assert marketing_run["campaign_status"] == "READY"
    correlation_ids.add(marketing_run["correlation_id"])

    cfo_response = client.post("/api/cfo/runs")
    assert cfo_response.status_code == 201
    cfo_report = cfo_response.json()
    correlation_ids.add(cfo_report["correlation_id"])

    assert cfo_report["data"]["total_products_analyzed"] == 3
    assert cfo_report["data"]["go_count"] == 2
    assert cfo_report["data"]["no_go_count"] == 1
    assert cfo_report["data"]["total_campaigns"] == 1
    assert cfo_report["data"]["total_daily_budget"] == 20.0
    assert cfo_report["financial_health_status"] == "AT_RISK"

    # Full traceability: every run has a distinct correlation_id, and the
    # CFO run is reconstructable via the audit trail.
    assert len(correlation_ids) == 5

    cfo_audit = client.get("/api/audit", params={"correlation_id": cfo_report["correlation_id"]}).json()
    assert any(e["action"] == "cfo.run" for e in cfo_audit)

    reconstructed = client.get(f"/api/cfo/runs/{cfo_report['correlation_id']}")
    assert reconstructed.status_code == 200
    assert reconstructed.json() == cfo_report
