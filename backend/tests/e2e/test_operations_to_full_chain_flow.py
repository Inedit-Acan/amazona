"""End-to-end Fase 3 (Agentes 1-8, todos los agentes operativos)
demo: research a category, run all seven prior agents, and generate an
operations report — verifying the healthy path (AI resolves the sample
support ticket) and the escalation path (a restricted/non-cleared legal
status escalates the ticket to a human and/or blocks operations).
Driven entirely through the public HTTP API, against a clean database.
This test closes out Fase 3: it is the last agent in the chain.
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


def test_full_eight_agent_chain_ai_resolves_the_support_ticket(client: TestClient):
    # 1. Research (Agente 1).
    research_run = client.post("/api/research/runs", json={"category": "home", "max_results": 5}).json()
    product_id = research_run["candidates"][0]["product_id"]

    # 2. Sourcing (Agente 2).
    sourcing_run = client.post(
        "/api/sourcing/runs",
        json={"product_id": product_id, "category": "home", "destination_region": "mexico", "max_results": 5},
    ).json()
    best_quote = sourcing_run["quotes"][0]

    # 3. Economics (Agente 3).
    economics_run = client.post(
        "/api/economics/runs",
        json={"product_id": product_id, "supplier_quote_id": best_quote["id"], "sale_price": 50.0},
    ).json()
    assert economics_run["recommendation"] == "GO"

    # 4. Legal (Agente 4), cleared.
    legal_run = client.post(
        "/api/legal/runs",
        json={"product_id": product_id, "market": "us", "certification_available": True},
    ).json()
    assert legal_run["recommendation"] == "GO"

    # 5. Ecommerce storefront (Agente 5).
    ecommerce_run = client.post("/api/ecommerce/runs", json={"product_id": product_id, "market": "us"}).json()
    assert ecommerce_run["launch_status"] == "READY"

    # 6. Marketplace listing (Agente 6).
    marketplace_run = client.post(
        "/api/marketplace/runs", json={"product_id": product_id, "market": "us", "platform": "amazon"}
    ).json()
    assert marketplace_run["listing_status"] == "READY"

    # 7. Marketing campaign (Agente 7).
    marketing_run = client.post(
        "/api/marketing/runs",
        json={"product_id": product_id, "market": "us", "platform": "google", "daily_budget": 20.0},
    ).json()
    assert marketing_run["campaign_status"] == "READY"

    # 8. Operations (Agente 8 — el último agente operativo de Fase 3).
    operations_response = client.post("/api/operations/runs", json={"product_id": product_id, "market": "us"})
    assert operations_response.status_code == 201
    operations_run = operations_response.json()

    # OperationsService resolves the *most recently created* SupplierQuote
    # for the product (same pattern as Agents 4/6/7), which is the last
    # one SourcingService persisted — not necessarily the best-ranked one.
    most_recently_created_quote = sourcing_run["quotes"][-1]

    assert operations_run["operations_status"] == "READY"
    assert operations_run["marketing_campaign_id"] is not None
    assert (
        operations_run["data"]["order"]["tracking"]["lead_time_days_used"]
        == most_recently_created_quote["lead_time_days"]
    )
    assert operations_run["data"]["return_policy"]["refund_estimate"] == 50.0
    assert operations_run["data"]["support_ticket_example"]["ai_resolvable"] is True

    reconstructed = client.get(f"/api/operations/runs/{operations_run['correlation_id']}")
    assert reconstructed.status_code == 200
    assert reconstructed.json() == operations_run

    product_operations = client.get(f"/api/products/{product_id}/operations").json()
    assert any(r["correlation_id"] == operations_run["correlation_id"] for r in product_operations)

    # Full traceability: eight distinct, independently auditable
    # correlation IDs across all eight Fase 3 agents.
    correlation_ids = {
        research_run["correlation_id"],
        sourcing_run["correlation_id"],
        economics_run["correlation_id"],
        legal_run["correlation_id"],
        ecommerce_run["correlation_id"],
        marketplace_run["correlation_id"],
        marketing_run["correlation_id"],
        operations_run["correlation_id"],
    }
    assert len(correlation_ids) == 8

    operations_audit = client.get(
        "/api/audit", params={"correlation_id": operations_run["correlation_id"]}
    ).json()
    assert any(e["action"] == "operations.run" for e in operations_audit)


def test_restricted_legal_status_escalates_the_support_ticket_and_blocks_operations(client: TestClient):
    research_run = client.post("/api/research/runs", json={"category": "accessories", "max_results": 5}).json()
    product_id = research_run["candidates"][0]["product_id"]

    sourcing_run = client.post(
        "/api/sourcing/runs",
        json={
            "product_id": product_id,
            "category": "accessories",
            "destination_region": "mexico",
            "max_results": 5,
        },
    ).json()
    best_quote = sourcing_run["quotes"][0]

    client.post(
        "/api/economics/runs",
        json={"product_id": product_id, "supplier_quote_id": best_quote["id"], "sale_price": 20.0},
    )
    # accessories/eu is restricted (REACH) in the fixture, no certification held.
    legal_run = client.post("/api/legal/runs", json={"product_id": product_id, "market": "eu"}).json()
    assert legal_run["recommendation"] == "NO_GO"

    operations_response = client.post("/api/operations/runs", json={"product_id": product_id, "market": "eu"})
    assert operations_response.status_code == 201
    operations_run = operations_response.json()

    assert operations_run["operations_status"] == "BLOCKED"
    assert operations_run["data"]["support_ticket_example"]["ai_resolvable"] is False
    assert operations_run["data"]["support_ticket_example"]["escalation_reason"]
    assert any("legal" in risk.lower() for risk in operations_run["data"]["risks"])
