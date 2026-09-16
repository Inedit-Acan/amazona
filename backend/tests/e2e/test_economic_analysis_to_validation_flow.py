"""End-to-end Fase 3 (Agentes 1 + 2 + 3) demo: research a category,
source suppliers for the top-ranked candidate, run an economic/risk
analysis on the best-landed-cost supplier, validate the trio through
the Milestone 1 CEO flow, and confirm all four runs are traceable end
to end by correlation ID — driven entirely through the public HTTP API,
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


def test_research_to_sourcing_to_economics_to_validation_flow_is_traceable_end_to_end(client: TestClient):
    # 1. Research a category (Fase 3, Agente 1 — unchanged since Milestone 2).
    research_response = client.post("/api/research/runs", json={"category": "electronics", "max_results": 5})
    assert research_response.status_code == 201
    research_run = research_response.json()
    top_candidate = research_run["candidates"][0]
    product_id = top_candidate["product_id"]

    # 2. Source suppliers for that product (Fase 3, Agente 2 — unchanged since Milestone 3).
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
    best_quote = sourcing_run["quotes"][0]

    # 3. Run an economic/risk analysis on the researched product + sourced
    # supplier (Fase 3, Agente 3).
    economics_response = client.post(
        "/api/economics/runs",
        json={"product_id": product_id, "supplier_quote_id": best_quote["id"], "sale_price": 20.0},
    )
    assert economics_response.status_code == 201
    economics_run = economics_response.json()
    assert economics_run["recommendation"] in {"GO", "REVIEW", "NO_GO"}
    base_scenario = economics_run["data"]["scenarios"]["base"]

    # It's reconstructable purely from the DB via its correlation_id.
    reconstructed = client.get(f"/api/economics/runs/{economics_run['correlation_id']}")
    assert reconstructed.status_code == 200
    assert reconstructed.json() == economics_run

    # It shows up when listing economics history for that product.
    product_economics = client.get(f"/api/products/{product_id}/economics").json()
    assert any(a["correlation_id"] == economics_run["correlation_id"] for a in product_economics)

    # 4. Validate the researched product + sourced supplier + economic
    # analysis through the Milestone 1 CEO flow, using all three agents'
    # output to drive context.
    demand_signal = top_candidate["data"]["demand_signal"]
    competition_level = top_candidate["data"]["competition_level"]
    unit_landed_cost = economics_run["sale_price"] * (1 - economics_run["margin_percent"])

    objective_response = client.post(
        "/api/objectives",
        json={
            "title": f"Validate {top_candidate['name']} with {best_quote['data']['name']} economics",
            "created_by": "owner@amazona.local",
            "context": {
                "product_validation": {
                    "estimated_monthly_searches": round(demand_signal * 15000),
                    "competition_level": competition_level,
                },
                "supplier_sourcing": {
                    "unit_cost": unit_landed_cost,
                    "lead_time_days": best_quote["lead_time_days"],
                    "supplier_verified": best_quote["verified"],
                },
                "finance_validation": {
                    "unit_cost": unit_landed_cost,
                    "sale_price": economics_run["sale_price"],
                    "monthly_unit_sales": round(base_scenario["monthly_unit_sales"]),
                    "monthly_fixed_costs": economics_run["monthly_fixed_costs"],
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

    # 5. Full traceability: research, sourcing, economics, and validation
    # are four distinct, independently auditable correlation IDs.
    correlation_ids = {
        research_run["correlation_id"],
        sourcing_run["correlation_id"],
        economics_run["correlation_id"],
        decision["correlation_id"],
    }
    assert len(correlation_ids) == 4

    economics_audit = client.get("/api/audit", params={"correlation_id": economics_run["correlation_id"]}).json()
    assert any(e["action"] == "economics.run" for e in economics_audit)

    validation_audit = client.get("/api/audit", params={"correlation_id": decision["correlation_id"]}).json()
    assert any(e["action"] == "project.created" for e in validation_audit)
    assert any(e["action"] == "decision.made" for e in validation_audit)

    # The decision's finance evidence reflects the economic analysis's real
    # margin, not a hardcoded example value: unit_landed_cost was derived
    # from economics_run's own margin_percent/sale_price, so FinanceAgent
    # recomputing margin from those same numbers must land back on it.
    validation_decision_detail = client.get(f"/api/decisions/{decision['id']}").json()
    finance_evidence = next(
        e for e in validation_decision_detail["evidence"] if e["source"] == "finance_validation"
    )
    assert f"{economics_run['margin_percent']:.2%}" in finance_evidence["summary"]
