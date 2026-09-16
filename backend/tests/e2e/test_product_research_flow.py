"""End-to-end Fase 3 (Agente 1) demo: research a category, take the
top-ranked candidate, validate it through the Milestone 1 CEO flow, and
confirm both runs are traceable end to end by correlation ID — driven
entirely through the public HTTP API, against a clean database.
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


def test_research_to_validation_flow_is_traceable_end_to_end(client: TestClient):
    # 1. Research a category.
    research_response = client.post("/api/research/runs", json={"category": "electronics", "max_results": 5})
    assert research_response.status_code == 201
    research_run = research_response.json()
    assert len(research_run["candidates"]) > 0

    # The API already returns candidates ranked by opportunity_score desc.
    top_candidate = research_run["candidates"][0]
    assert top_candidate["opportunity_score"] is not None

    # It's reconstructable purely from the DB via its correlation_id.
    reconstructed = client.get(f"/api/research/runs/{research_run['correlation_id']}")
    assert reconstructed.status_code == 200
    assert reconstructed.json() == research_run

    # It shows up in the candidate product list.
    candidates_list = client.get("/api/products", params={"status": "CANDIDATE"}).json()
    assert any(p["id"] == top_candidate["product_id"] for p in candidates_list)

    # 2. Validate the top candidate through the Milestone 1 CEO flow, using
    # the researched demand/competition signals to drive product_validation.
    demand_signal = top_candidate["data"]["demand_signal"]
    competition_level = top_candidate["data"]["competition_level"]

    objective_response = client.post(
        "/api/objectives",
        json={
            "title": f"Validate {top_candidate['name']} opportunity",
            "created_by": "owner@amazona.local",
            "context": {
                "product_validation": {
                    "estimated_monthly_searches": round(demand_signal * 15000),
                    "competition_level": competition_level,
                },
                "supplier_sourcing": {"unit_cost": 5.0, "lead_time_days": 20, "supplier_verified": True},
                "finance_validation": {
                    "unit_cost": 5.0,
                    "sale_price": 20.0,
                    "monthly_unit_sales": 300,
                    "monthly_fixed_costs": 500.0,
                },
                "legal_validation": {"restricted_category": False},
            },
        },
    )
    assert objective_response.status_code == 201
    objective_id = objective_response.json()["id"]

    decision_response = client.post(f"/api/objectives/{objective_id}/run")
    assert decision_response.status_code == 200
    decision = decision_response.json()
    assert decision["status"] in {"GO", "REVIEW", "NO_GO", "HUMAN_APPROVAL"}

    # 3. Full traceability: research and validation are two distinct,
    # independently auditable correlation IDs, each reconstructable.
    assert decision["correlation_id"] != research_run["correlation_id"]

    research_audit = client.get("/api/audit", params={"correlation_id": research_run["correlation_id"]}).json()
    assert any(e["action"] == "research.run" for e in research_audit)

    validation_audit = client.get("/api/audit", params={"correlation_id": decision["correlation_id"]}).json()
    assert any(e["action"] == "project.created" for e in validation_audit)
    assert any(e["action"] == "decision.made" for e in validation_audit)

    validation_decision_detail = client.get(f"/api/decisions/{decision['id']}").json()
    product_evidence = next(
        e for e in validation_decision_detail["evidence"] if e["source"] == "product_validation"
    )
    assert str(round(demand_signal * 15000)) in product_evidence["summary"]
