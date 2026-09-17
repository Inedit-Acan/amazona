"""Milestone 14 (IVA-33, ADR 0006) end to end: a risky pipeline run
requires human review before anyone can act on it with confidence, and
an operator can disable/re-enable the pipeline entirely — the two
critical human controls this milestone adds over the automated
PipelineOrchestrator (Milestone 12/13)."""

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


def test_a_risky_run_is_flagged_reviewed_and_audited(client: TestClient):
    run_response = client.post(
        "/api/pipeline/runs",
        json={"category": "home", "sale_price": 0.5, "destination_region": "mexico"},
    )
    assert run_response.status_code == 201
    run = run_response.json()
    assert run["needs_review"] is True
    assert run["steps"]["economics"]["recommendation"] == "NO_GO"

    reviews = client.get("/api/pipeline/reviews").json()
    assert len(reviews) == 1
    review = reviews[0]
    assert review["status"] == "PENDING"
    assert any("economics" in reason for reason in review["reasons"])

    approve_response = client.post(
        f"/api/pipeline/reviews/{review['id']}/approve", json={"actor": "owner@amazona.local"}
    )
    assert approve_response.status_code == 200
    assert approve_response.json()["status"] == "APPROVED"
    assert approve_response.json()["resolved_by"] == "owner@amazona.local"

    audit_entries = client.get("/api/audit", params={"correlation_id": review["correlation_id"]}).json()
    assert any(e["action"] == "pipeline_review.approve" for e in audit_entries)

    assert client.get("/api/pipeline/reviews").json() == []


def test_kill_switch_blocks_and_then_unblocks_new_runs(client: TestClient):
    # Healthy to start.
    ok_response = client.post(
        "/api/pipeline/runs",
        json={"category": "home", "sale_price": 50.0, "destination_region": "mexico"},
    )
    assert ok_response.status_code == 201

    disable_response = client.post(
        "/api/pipeline/kill-switch",
        json={"enabled": False, "reason": "investigating an incident", "actor": "ops@amazona.local"},
    )
    assert disable_response.status_code == 200

    blocked_response = client.post(
        "/api/pipeline/runs",
        json={"category": "home", "sale_price": 50.0, "destination_region": "mexico"},
    )
    assert blocked_response.status_code == 423

    reenable_response = client.post(
        "/api/pipeline/kill-switch", json={"enabled": True, "actor": "ops@amazona.local"}
    )
    assert reenable_response.status_code == 200
    assert reenable_response.json()["reason"] is None

    resumed_response = client.post(
        "/api/pipeline/runs",
        json={"category": "home", "sale_price": 50.0, "destination_region": "mexico"},
    )
    assert resumed_response.status_code == 201
