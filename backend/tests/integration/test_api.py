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


def test_full_objective_lifecycle_through_the_api(client: TestClient):
    create_response = client.post(
        "/api/objectives",
        json={
            "title": "Validate wireless earbuds opportunity",
            "created_by": "owner@amazona.local",
            "context": ATTRACTIVE_PRODUCT_CONTEXT,
        },
    )
    assert create_response.status_code == 201
    objective = create_response.json()
    assert objective["title"] == "Validate wireless earbuds opportunity"

    run_response = client.post(f"/api/objectives/{objective['id']}/run")
    assert run_response.status_code == 200
    decision = run_response.json()
    assert decision["status"] == "HUMAN_APPROVAL"
    project_id = decision["project_id"]
    correlation_id = decision["correlation_id"]

    project_response = client.get(f"/api/projects/{project_id}")
    assert project_response.status_code == 200
    assert project_response.json()["id"] == project_id

    tasks_response = client.get("/api/tasks", params={"project_id": project_id})
    assert tasks_response.status_code == 200
    tasks = tasks_response.json()
    assert len(tasks) == 5
    assert all(t["status"] == "COMPLETED" for t in tasks)
    tasks_by_name = {t["name"]: t for t in tasks}
    assert tasks_by_name["decision_synthesis"]["depends_on"]
    assert tasks_by_name["product_validation"]["depends_on"] == []

    agents_response = client.get("/api/agents")
    assert agents_response.status_code == 200
    agents = agents_response.json()
    assert len(agents) == 9
    assert {a["role"] for a in agents} == {
        "product",
        "supplier",
        "finance",
        "legal",
        "research",
        "sourcing",
        "economics",
        "legal_compliance",
        "ecommerce",
    }

    decision_response = client.get(f"/api/decisions/{decision['id']}")
    assert decision_response.status_code == 200
    decision_detail = decision_response.json()
    assert decision_detail["status"] == "HUMAN_APPROVAL"
    assert len(decision_detail["evidence"]) == 4

    approvals_response = client.get("/api/approvals")
    assert approvals_response.status_code == 200
    approvals = approvals_response.json()
    assert len(approvals) == 1
    approval_id = approvals[0]["id"]
    assert approvals[0]["status"] == "PENDING"

    approve_response = client.post(
        f"/api/approvals/{approval_id}/approve", json={"actor": "owner@amazona.local"}
    )
    assert approve_response.status_code == 200
    assert approve_response.json()["status"] == "APPROVED"

    replay_response = client.post(
        f"/api/approvals/{approval_id}/approve", json={"actor": "owner@amazona.local"}
    )
    assert replay_response.status_code == 409

    audit_response = client.get("/api/audit", params={"correlation_id": correlation_id})
    assert audit_response.status_code == 200
    audit_entries = audit_response.json()
    assert len(audit_entries) > 0
    assert any(e["action"] == "approval.approve" for e in audit_entries)

    executions_response = client.get("/api/agent-executions", params={"correlation_id": correlation_id})
    assert executions_response.status_code == 200
    executions = executions_response.json()
    assert len(executions) == 4
    assert all(e["success"] for e in executions)

    health_response = client.get("/health/detailed")
    assert health_response.status_code == 200
    assert health_response.json()["database"] == "ok"


def test_reject_approval_marks_it_rejected(client: TestClient):
    create_response = client.post(
        "/api/objectives",
        json={
            "title": "Validate wireless earbuds opportunity",
            "created_by": "owner@amazona.local",
            "context": ATTRACTIVE_PRODUCT_CONTEXT,
        },
    )
    objective_id = create_response.json()["id"]
    client.post(f"/api/objectives/{objective_id}/run")

    approvals = client.get("/api/approvals").json()
    approval_id = approvals[0]["id"]

    reject_response = client.post(
        f"/api/approvals/{approval_id}/reject", json={"actor": "owner@amazona.local"}
    )
    assert reject_response.status_code == 200
    assert reject_response.json()["status"] == "REJECTED"


def test_get_project_returns_404_for_unknown_id(client: TestClient):
    response = client.get("/api/projects/does-not-exist")
    assert response.status_code == 404


def test_list_projects_returns_all_created_projects(client: TestClient):
    objective_id = client.post(
        "/api/objectives",
        json={
            "title": "Validate wireless earbuds opportunity",
            "created_by": "owner@amazona.local",
            "context": ATTRACTIVE_PRODUCT_CONTEXT,
        },
    ).json()["id"]
    client.post(f"/api/objectives/{objective_id}/run")

    response = client.get("/api/projects")

    assert response.status_code == 200
    projects = response.json()
    assert len(projects) == 1
    assert projects[0]["objective_id"] == objective_id


def test_list_decisions_filters_by_project_id(client: TestClient):
    objective_id = client.post(
        "/api/objectives",
        json={
            "title": "Validate wireless earbuds opportunity",
            "created_by": "owner@amazona.local",
            "context": ATTRACTIVE_PRODUCT_CONTEXT,
        },
    ).json()["id"]
    run_result = client.post(f"/api/objectives/{objective_id}/run").json()

    response = client.get("/api/decisions", params={"project_id": run_result["project_id"]})

    assert response.status_code == 200
    decisions = response.json()
    assert len(decisions) == 1
    assert decisions[0]["id"] == run_result["id"]
    assert len(decisions[0]["evidence"]) == 4
