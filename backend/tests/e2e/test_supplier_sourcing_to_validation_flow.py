"""End-to-end Fase 3 (Agentes 1 + 2) demo: research a category, source
suppliers for the top-ranked candidate, take the best-landed-cost
supplier, validate the pair through the Milestone 1 CEO flow, and
confirm all three runs are traceable end to end by correlation ID —
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


def test_research_to_sourcing_to_validation_flow_is_traceable_end_to_end(client: TestClient):
    # 1. Research a category (Fase 3, Agente 1 — unchanged from Milestone 2).
    research_response = client.post("/api/research/runs", json={"category": "electronics", "max_results": 5})
    assert research_response.status_code == 201
    research_run = research_response.json()
    assert len(research_run["candidates"]) > 0

    top_candidate = research_run["candidates"][0]
    product_id = top_candidate["product_id"]

    # 2. Source suppliers for that product (Fase 3, Agente 2).
    sourcing_response = client.post(
        "/api/sourcing/runs",
        json={
            "product_id": product_id,
            "category": top_candidate["category"],
            "destination_region": "mexico",
            "max_results": 5,
        },
    )
    assert sourcing_response.status_code == 201
    sourcing_run = sourcing_response.json()
    assert len(sourcing_run["quotes"]) > 0

    # The API already returns quotes ranked by total_landed_cost_per_unit asc.
    best_quote = sourcing_run["quotes"][0]
    costs = [q["total_landed_cost_per_unit"] for q in sourcing_run["quotes"]]
    assert costs == sorted(costs)

    # It's reconstructable purely from the DB via its correlation_id.
    reconstructed = client.get(f"/api/sourcing/runs/{sourcing_run['correlation_id']}")
    assert reconstructed.status_code == 200
    assert reconstructed.json() == sourcing_run

    # It shows up when listing quotes for that product.
    product_suppliers = client.get(f"/api/products/{product_id}/suppliers").json()
    assert any(q["supplier_id"] == best_quote["supplier_id"] for q in product_suppliers)

    # 3. Validate the researched product + sourced supplier through the
    # Milestone 1 CEO flow, using both agents' output to drive context.
    demand_signal = top_candidate["data"]["demand_signal"]
    competition_level = top_candidate["data"]["competition_level"]

    objective_response = client.post(
        "/api/objectives",
        json={
            "title": f"Validate {top_candidate['name']} with {best_quote['data']['name']}",
            "created_by": "owner@amazona.local",
            "context": {
                "product_validation": {
                    "estimated_monthly_searches": round(demand_signal * 15000),
                    "competition_level": competition_level,
                },
                "supplier_sourcing": {
                    "unit_cost": best_quote["unit_price"],
                    "lead_time_days": best_quote["lead_time_days"],
                    "supplier_verified": best_quote["verified"],
                },
                "finance_validation": {
                    "unit_cost": best_quote["unit_price"],
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

    # 4. Full traceability: research, sourcing and validation are three
    # distinct, independently auditable correlation IDs, each reconstructable.
    correlation_ids = {research_run["correlation_id"], sourcing_run["correlation_id"], decision["correlation_id"]}
    assert len(correlation_ids) == 3

    research_audit = client.get("/api/audit", params={"correlation_id": research_run["correlation_id"]}).json()
    assert any(e["action"] == "research.run" for e in research_audit)

    sourcing_audit = client.get("/api/audit", params={"correlation_id": sourcing_run["correlation_id"]}).json()
    assert any(e["action"] == "sourcing.run" for e in sourcing_audit)

    validation_audit = client.get("/api/audit", params={"correlation_id": decision["correlation_id"]}).json()
    assert any(e["action"] == "project.created" for e in validation_audit)
    assert any(e["action"] == "decision.made" for e in validation_audit)

    validation_decision_detail = client.get(f"/api/decisions/{decision['id']}").json()
    supplier_evidence = next(
        e for e in validation_decision_detail["evidence"] if e["source"] == "supplier_sourcing"
    )
    assert str(best_quote["unit_price"]) in supplier_evidence["summary"]
