"""End-to-end Milestone 1 demo: drive the whole product-validation flow
through the public HTTP API, exactly as an owner or the Control Center
would, against a clean database.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app

ATTRACTIVE_PRODUCT_CONTEXT = {
    "product_validation": {"estimated_monthly_searches": 12000, "competition_level": "low"},
    "supplier_sourcing": {"unit_cost": 5.0, "lead_time_days": 20, "supplier_verified": True},
    "finance_validation": {
        "unit_cost": 5.0,
        "sale_price": 20.0,
        "monthly_unit_sales": 300,
        "monthly_fixed_costs": 500.0,
    },
    "legal_validation": {"restricted_category": False},
    "requests_simulated_spend": True,
    "spend_action": "launch_marketing_campaign",
    "spend_amount": 150.0,
}


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


def run_objective(client: TestClient, context: dict) -> dict:
    objective = client.post(
        "/api/objectives",
        json={
            "title": "Validate wireless earbuds opportunity",
            "created_by": "owner@amazona.local",
            "context": context,
        },
    ).json()
    return client.post(f"/api/objectives/{objective['id']}/run").json()


def test_scenario_a_attractive_product_requires_human_approval(client: TestClient):
    """Product attractive, supplier viable, finance profitable, legal
    clear, and a simulated marketing spend requested -> HUMAN_APPROVAL,
    with exactly one pending approval created."""
    decision = run_objective(client, ATTRACTIVE_PRODUCT_CONTEXT)

    assert decision["status"] == "HUMAN_APPROVAL"

    tasks = client.get("/api/tasks", params={"project_id": decision["project_id"]}).json()
    assert len(tasks) == 5
    assert all(t["status"] == "COMPLETED" for t in tasks)

    approvals = client.get("/api/approvals").json()
    matching = [a for a in approvals if a["decision_id"] == decision["id"]]
    assert len(matching) == 1
    assert matching[0]["status"] == "PENDING"
    assert matching[0]["action"] == "launch_marketing_campaign"
    assert matching[0]["amount"] == 150.0

    audit = client.get("/api/audit", params={"correlation_id": decision["correlation_id"]}).json()
    audit_actions = {e["action"] for e in audit}
    assert {"project.created", "tasks.created", "decision.made", "approval.requested"} <= audit_actions


def test_scenario_b_legal_veto_is_no_go_with_no_approval(client: TestClient):
    """Same attractive product, but Legal is BLOCKED -> NO_GO, and no
    approval is created even though a spend was requested."""
    context = {
        **ATTRACTIVE_PRODUCT_CONTEXT,
        "legal_validation": {
            "restricted_category": True,
            "requires_certification": True,
            "certification_available": False,
        },
    }

    decision = run_objective(client, context)

    assert decision["status"] == "NO_GO"

    approvals = client.get("/api/approvals").json()
    matching = [a for a in approvals if a["decision_id"] == decision["id"]]
    assert matching == []

    project = client.get(f"/api/projects/{decision['project_id']}").json()
    assert project["status"] == "REJECTED"


def test_scenario_c_insufficient_data_yields_review(client: TestClient):
    """Weak/missing product data drags the agent's confidence down ->
    overall decision REVIEW, regardless of the requested spend."""
    context = {
        **ATTRACTIVE_PRODUCT_CONTEXT,
        "product_validation": {"product_name": "Unknown gadget"},
    }

    decision = run_objective(client, context)

    assert decision["status"] == "REVIEW"
    assert decision["confidence"] is not None
    assert decision["confidence"] < 0.5

    approvals = client.get("/api/approvals").json()
    matching = [a for a in approvals if a["decision_id"] == decision["id"]]
    assert matching == []
