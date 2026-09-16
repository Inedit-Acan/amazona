"""Milestone 12 (ADR 0005): a SINGLE `POST /api/pipeline/runs` call now
produces the full 9-step Fase 3 chain — research through CFO — verifying
the new internal orchestration, as opposed to
test_operations_to_full_chain_flow.py / test_cfo_aggregation_flow.py,
which prove the chain works only because the test itself makes 8+
sequential HTTP calls threading IDs by hand (the manual flow this
milestone replaces)."""

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


def test_one_call_produces_the_full_nine_step_chain_with_real_ids_threaded(client: TestClient):
    response = client.post(
        "/api/pipeline/runs",
        json={
            "category": "home",
            "sale_price": 50.0,
            "destination_region": "mexico",
            "market": "us",
            "marketplace_platform": "amazon",
            "marketing_platform": "google",
            "daily_budget": 20.0,
        },
    )
    assert response.status_code == 201
    run = response.json()
    assert run["status"] == "COMPLETED"
    product_id = run["product_id"]

    # Every downstream step's real DB row is reconstructable independently,
    # exactly as if a human had clicked through each page — but nobody did.
    economics = client.get(f"/api/products/{product_id}/economics").json()
    assert len(economics) == 1
    assert economics[0]["recommendation"] == "GO"

    legal = client.get(f"/api/products/{product_id}/legal").json()
    assert len(legal) == 1

    campaigns = client.get(f"/api/products/{product_id}/campaigns").json()
    assert len(campaigns) == 1
    assert campaigns[0]["campaign_status"] == "READY"
    assert campaigns[0]["platform"] == "google"

    operations = client.get(f"/api/products/{product_id}/operations").json()
    assert len(operations) == 1
    assert operations[0]["operations_status"] == "READY"
    # Operations linked to the marketing campaign this SAME pipeline run
    # created — proving the IDs were threaded automatically, not guessed.
    assert operations[0]["marketing_campaign_id"] == run["steps"]["marketing"]["entity_id"]

    # Ten distinct correlation_ids: the pipeline's own plus one per step.
    all_correlation_ids = {run["correlation_id"]} | {step["correlation_id"] for step in run["steps"].values()}
    assert len(all_correlation_ids) == 10

    # Every step is independently reconstructable via the audit trail,
    # including the pipeline's own top-level run.
    pipeline_audit = client.get("/api/audit", params={"correlation_id": run["correlation_id"]}).json()
    assert any(e["action"] == "pipeline.run" for e in pipeline_audit)

    economics_audit = client.get(
        "/api/audit", params={"correlation_id": run["steps"]["economics"]["correlation_id"]}
    ).json()
    assert any(e["action"] == "economics.run" for e in economics_audit)


def test_pipeline_completes_even_when_economics_is_no_go(client: TestClient):
    response = client.post(
        "/api/pipeline/runs",
        json={"category": "home", "sale_price": 0.5, "destination_region": "mexico"},
    )
    assert response.status_code == 201
    run = response.json()

    assert run["status"] == "COMPLETED"
    assert run["steps"]["economics"]["recommendation"] == "NO_GO"
    # No auto-halt (ADR 0005) — every downstream step still ran.
    assert "operations" in run["steps"]
    assert "cfo" in run["steps"]


def test_pipeline_is_partial_when_research_has_no_candidates(client: TestClient):
    response = client.post(
        "/api/pipeline/runs",
        json={"category": "does-not-exist", "sale_price": 50.0, "destination_region": "mexico"},
    )
    assert response.status_code == 201
    run = response.json()

    assert run["status"] == "PARTIAL"
    assert run["failed_step"] == "research"
    assert run["product_id"] is None
