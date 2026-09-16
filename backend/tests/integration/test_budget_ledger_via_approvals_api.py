"""Verifies IVA-59: approving/rejecting an approval through the public API
reconciles the durable budget_allocations/financial_events ledger, not just
the orchestrator's in-memory BudgetState."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models.budget import BudgetAllocation, FinancialEvent
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
def app_fixture():
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
        yield TestClient(app), session_factory
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def _run_objective_and_get_approval_id(client: TestClient) -> str:
    objective_id = client.post(
        "/api/objectives",
        json={
            "title": "Validate wireless earbuds opportunity",
            "created_by": "owner@amazona.local",
            "context": ATTRACTIVE_PRODUCT_CONTEXT,
        },
    ).json()["id"]
    client.post(f"/api/objectives/{objective_id}/run")
    approvals = client.get("/api/approvals").json()
    return approvals[0]["id"]


def test_running_an_objective_persists_the_reservation(app_fixture):
    client, session_factory = app_fixture

    _run_objective_and_get_approval_id(client)

    session = session_factory()
    allocation = session.query(BudgetAllocation).one()
    assert allocation.reserved == 150.0
    assert allocation.committed == 0.0
    assert allocation.spent == 0.0
    reserve_events = session.query(FinancialEvent).filter_by(type="RESERVE").all()
    assert len(reserve_events) == 1
    assert reserve_events[0].amount == 150.0
    session.close()


def test_approving_commits_the_reservation_into_committed_and_spent(app_fixture):
    client, session_factory = app_fixture
    approval_id = _run_objective_and_get_approval_id(client)

    response = client.post(f"/api/approvals/{approval_id}/approve", json={"actor": "owner@amazona.local"})
    assert response.status_code == 200

    session = session_factory()
    allocation = session.query(BudgetAllocation).one()
    assert allocation.reserved == 0.0
    assert allocation.committed == 150.0
    assert allocation.spent == 150.0
    assert session.query(FinancialEvent).filter_by(type="COMMIT").count() == 1
    session.close()


def test_rejecting_releases_the_reservation_without_committing_or_spending(app_fixture):
    client, session_factory = app_fixture
    approval_id = _run_objective_and_get_approval_id(client)

    response = client.post(f"/api/approvals/{approval_id}/reject", json={"actor": "owner@amazona.local"})
    assert response.status_code == 200

    session = session_factory()
    allocation = session.query(BudgetAllocation).one()
    assert allocation.reserved == 0.0
    assert allocation.committed == 0.0
    assert allocation.spent == 0.0
    assert session.query(FinancialEvent).filter_by(type="RELEASE").count() == 1
    session.close()


def test_cfo_report_reflects_real_budget_utilization_after_approval(app_fixture):
    client, session_factory = app_fixture
    approval_id = _run_objective_and_get_approval_id(client)
    client.post(f"/api/approvals/{approval_id}/approve", json={"actor": "owner@amazona.local"})

    cfo_report = client.post("/api/cfo/runs").json()

    assert cfo_report["data"]["total_budget_hard_limit"] == 100_000.0
    assert cfo_report["data"]["total_committed"] == 150.0
    assert cfo_report["data"]["total_spent"] == 150.0
    # CFOAgent sums reserved + committed + spent; record_commit mirrors
    # BudgetEngine.commit(), which moves the amount into both simultaneously.
    assert cfo_report["data"]["budget_utilization"] == pytest.approx((150.0 + 150.0) / 100_000.0)
