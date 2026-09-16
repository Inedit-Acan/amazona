"""End-to-end Fase 3 (Agentes 1 + 2 + 3 + 4) demo: research a category,
source suppliers for the top-ranked candidate, run an economic/risk
analysis, run a legal/compliance analysis, validate all four through the
Milestone 1 CEO flow, and confirm all five runs are traceable end to end
by correlation ID — driven entirely through the public HTTP API, against
a clean database.
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


def test_full_five_step_flow_is_traceable_end_to_end_and_blocks_a_restricted_category(client: TestClient):
    # 1. Research a category (Fase 3, Agente 1).
    research_response = client.post("/api/research/runs", json={"category": "accessories", "max_results": 5})
    assert research_response.status_code == 201
    research_run = research_response.json()
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
    best_quote = sourcing_run["quotes"][0]

    # 3. Run an economic/risk analysis (Fase 3, Agente 3).
    economics_response = client.post(
        "/api/economics/runs",
        json={"product_id": product_id, "supplier_quote_id": best_quote["id"], "sale_price": 20.0},
    )
    assert economics_response.status_code == 201
    economics_run = economics_response.json()

    # 4. Run a legal/compliance analysis in the EU market (Fase 3, Agente 4)
    # — the "accessories" fixture is restricted in "eu" with REACH required,
    # so with no certification held this should come back NO_GO/restricted.
    legal_response = client.post(
        "/api/legal/runs", json={"product_id": product_id, "market": "eu"}
    )
    assert legal_response.status_code == 201
    legal_run = legal_response.json()
    assert legal_run["restricted"] is True
    assert legal_run["recommendation"] == "NO_GO"
    assert "REACH" in legal_run["data"]["required_certifications"]

    # It's reconstructable purely from the DB via its correlation_id.
    reconstructed = client.get(f"/api/legal/runs/{legal_run['correlation_id']}")
    assert reconstructed.status_code == 200
    assert reconstructed.json() == legal_run

    # It shows up in the product's compliance history/checklist.
    product_legal = client.get(f"/api/products/{product_id}/legal").json()
    assert any(a["correlation_id"] == legal_run["correlation_id"] for a in product_legal)

    # 5. Validate the researched product + sourced supplier + economic
    # analysis + legal analysis through the Milestone 1 CEO flow, using all
    # four agents' output to drive context — the real legal_validation
    # values replace the {"restricted_category": False} placeholder that
    # existed since Milestone 1.
    demand_signal = top_candidate["data"]["demand_signal"]
    competition_level = top_candidate["data"]["competition_level"]
    base_scenario = economics_run["data"]["scenarios"]["base"]
    unit_landed_cost = economics_run["sale_price"] * (1 - economics_run["margin_percent"])
    requires_certification = bool(legal_run["data"]["required_certifications"])

    objective_response = client.post(
        "/api/objectives",
        json={
            "title": f"Validate {top_candidate['name']} full compliance chain",
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
                "legal_validation": {
                    "restricted_category": legal_run["restricted"],
                    "requires_certification": requires_certification,
                    "certification_available": False,
                },
            },
        },
    )
    assert objective_response.status_code == 201
    objective_id = objective_response.json()["id"]

    decision_response = client.post(f"/api/objectives/{objective_id}/run")
    assert decision_response.status_code == 200
    decision = decision_response.json()

    # The real legal analysis (restricted + certification missing) must
    # block the objective, exactly like a real restricted category would —
    # proving the placeholder replacement changes real outcomes, not just
    # UI text.
    assert decision["status"] == "NO_GO"

    # 6. Full traceability: five distinct, independently auditable
    # correlation IDs across research, sourcing, economics, legal, and
    # validation.
    correlation_ids = {
        research_run["correlation_id"],
        sourcing_run["correlation_id"],
        economics_run["correlation_id"],
        legal_run["correlation_id"],
        decision["correlation_id"],
    }
    assert len(correlation_ids) == 5

    legal_audit = client.get("/api/audit", params={"correlation_id": legal_run["correlation_id"]}).json()
    assert any(e["action"] == "legal.run" for e in legal_audit)

    validation_audit = client.get("/api/audit", params={"correlation_id": decision["correlation_id"]}).json()
    assert any(e["action"] == "project.created" for e in validation_audit)
    assert any(e["action"] == "decision.made" for e in validation_audit)

    # The decision's legal evidence reflects the real analysis, not a
    # hardcoded example value.
    validation_decision_detail = client.get(f"/api/decisions/{decision['id']}").json()
    legal_evidence = next(
        e for e in validation_decision_detail["evidence"] if e["source"] == "legal_validation"
    )
    assert "certification" in legal_evidence["summary"]
