"""End-to-end Fase 3 (Agentes 1-7) demo: research a category, source
suppliers, run economic/legal analyses, generate a storefront and a
marketplace listing, plan a marketing campaign, and validate the whole
chain through the Milestone 1 CEO flow — verifying that the campaign's
real recommended daily_budget replaces the spend_amount=150.0 example
placeholder that has existed since Milestone 1, and that a weak
projected ROAS blocks the campaign instead of reaching validation.
Driven entirely through the public HTTP API, against a clean database.
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


def test_full_seven_agent_chain_reaches_human_approval_with_the_real_recommended_budget(
    client: TestClient,
):
    # 1. Research a category (Fase 3, Agente 1).
    research_run = client.post("/api/research/runs", json={"category": "home", "max_results": 5}).json()
    top_candidate = research_run["candidates"][0]
    product_id = top_candidate["product_id"]

    # 2. Source suppliers (Fase 3, Agente 2).
    sourcing_run = client.post(
        "/api/sourcing/runs",
        json={"product_id": product_id, "category": "home", "destination_region": "mexico", "max_results": 5},
    ).json()
    best_quote = sourcing_run["quotes"][0]

    # 3. Economic analysis at a healthy price point (Fase 3, Agente 3).
    economics_run = client.post(
        "/api/economics/runs",
        json={"product_id": product_id, "supplier_quote_id": best_quote["id"], "sale_price": 50.0},
    ).json()
    assert economics_run["recommendation"] == "GO"

    # 4. Legal analysis, cleared (Fase 3, Agente 4).
    legal_run = client.post(
        "/api/legal/runs",
        json={"product_id": product_id, "market": "us", "certification_available": True},
    ).json()
    assert legal_run["recommendation"] == "GO"

    # 5. Storefront generation (Fase 3, Agente 5).
    ecommerce_run = client.post("/api/ecommerce/runs", json={"product_id": product_id, "market": "us"}).json()
    assert ecommerce_run["launch_status"] == "READY"

    # 6. Marketplace listing (Fase 3, Agente 6).
    marketplace_run = client.post(
        "/api/marketplace/runs", json={"product_id": product_id, "market": "us", "platform": "amazon"}
    ).json()
    assert marketplace_run["listing_status"] == "READY"

    # 7. Marketing campaign proposal (Fase 3, Agente 7) — home/google at
    # $50 sale price yields a strong projected ROAS.
    marketing_run = client.post(
        "/api/marketing/runs",
        json={"product_id": product_id, "market": "us", "platform": "google", "daily_budget": 20.0},
    ).json()
    assert marketing_run["campaign_status"] == "READY"
    assert marketing_run["data"]["performance_estimate"]["projected_roas"] >= 2.0
    assert marketing_run["data"]["performance_estimate"]["data_origin"] == "simulated_ad_performance_estimate"

    reconstructed = client.get(f"/api/marketing/runs/{marketing_run['correlation_id']}")
    assert reconstructed.status_code == 200
    assert reconstructed.json() == marketing_run

    product_campaigns = client.get(f"/api/products/{product_id}/campaigns").json()
    assert any(c["correlation_id"] == marketing_run["correlation_id"] for c in product_campaigns)

    # 8. Validate the full chain through the Milestone 1 CEO flow. The real
    # recommended daily_budget drives spend_amount — replacing the 150.0
    # example placeholder that's existed since Milestone 1.
    objective_response = client.post(
        "/api/objectives",
        json={
            "title": f"Validate {top_candidate['name']} full chain",
            "created_by": "owner@amazona.local",
            "context": {
                "product_validation": {
                    "estimated_monthly_searches": round(top_candidate["data"]["demand_signal"] * 15000),
                    "competition_level": top_candidate["data"]["competition_level"],
                },
                "supplier_sourcing": {
                    "unit_cost": best_quote["unit_price"],
                    "lead_time_days": best_quote["lead_time_days"],
                    "supplier_verified": best_quote["verified"],
                },
                "finance_validation": {
                    "unit_cost": best_quote["unit_price"],
                    "sale_price": 50.0,
                    "monthly_unit_sales": 300,
                    "monthly_fixed_costs": 500.0,
                },
                "legal_validation": {
                    "restricted_category": legal_run["restricted"],
                    "requires_certification": bool(legal_run["data"]["required_certifications"]),
                    "certification_available": True,
                },
                "requests_simulated_spend": True,
                "spend_action": "launch_marketing_campaign",
                "spend_amount": marketing_run["daily_budget"],
            },
        },
    )
    assert objective_response.status_code == 201
    objective_id = objective_response.json()["id"]

    decision_response = client.post(f"/api/objectives/{objective_id}/run")
    assert decision_response.status_code == 200
    decision = decision_response.json()
    assert decision["status"] == "HUMAN_APPROVAL"

    # The pending Approval carries the real recommended budget, not the
    # Milestone 1 example value of 150.0.
    approvals = client.get("/api/approvals").json()
    matching_approval = next(a for a in approvals if a["decision_id"] == decision["id"])
    assert matching_approval["action"] == "launch_marketing_campaign"
    assert matching_approval["amount"] == marketing_run["daily_budget"]
    assert matching_approval["amount"] != 150.0

    # 9. Full traceability: seven distinct, independently auditable
    # correlation IDs across all agent runs plus validation.
    correlation_ids = {
        research_run["correlation_id"],
        sourcing_run["correlation_id"],
        economics_run["correlation_id"],
        legal_run["correlation_id"],
        ecommerce_run["correlation_id"],
        marketplace_run["correlation_id"],
        marketing_run["correlation_id"],
        decision["correlation_id"],
    }
    assert len(correlation_ids) == 8

    marketing_audit = client.get("/api/audit", params={"correlation_id": marketing_run["correlation_id"]}).json()
    assert any(e["action"] == "marketing.run" for e in marketing_audit)


def test_weak_projected_roas_blocks_the_campaign_before_reaching_validation(client: TestClient):
    # accessories/meta has a low avg_cpc (0.40) relative to conversion_rate
    # (0.02); at a low sale price the projected ROAS falls under 1.0.
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
        json={"product_id": product_id, "supplier_quote_id": best_quote["id"], "sale_price": 5.0},
    )
    client.post(
        "/api/legal/runs",
        json={"product_id": product_id, "market": "us", "certification_available": True},
    )
    client.post("/api/ecommerce/runs", json={"product_id": product_id, "market": "us"})
    client.post("/api/marketplace/runs", json={"product_id": product_id, "market": "us", "platform": "amazon"})

    marketing_response = client.post(
        "/api/marketing/runs", json={"product_id": product_id, "market": "us", "platform": "meta"}
    )
    assert marketing_response.status_code == 201
    marketing_run = marketing_response.json()

    assert marketing_run["campaign_status"] == "BLOCKED"
    assert marketing_run["recommendation"] == "NO_GO"
    assert any("roas" in risk.lower() for risk in marketing_run["data"]["risks"])
