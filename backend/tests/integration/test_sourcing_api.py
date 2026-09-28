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


def _create_product(client: TestClient) -> str:
    run = client.post("/api/research/runs", json={"category": "electronics", "max_results": 1}).json()
    return run["candidates"][0]["product_id"]


def test_create_sourcing_run_persists_and_returns_ranked_quotes(client: TestClient):
    product_id = _create_product(client)

    response = client.post(
        "/api/sourcing/runs",
        json={
            "product_id": product_id,
            "category": "electronics",
            "destination_region": "mexico",
            "max_results": 3,
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert 1 <= len(body["quotes"]) <= 3
    costs = [q["total_landed_cost_per_unit"] for q in body["quotes"]]
    assert costs == sorted(costs)


def test_get_sourcing_run_reconstructs_the_same_result_from_db(client: TestClient):
    product_id = _create_product(client)
    created = client.post(
        "/api/sourcing/runs",
        json={
            "product_id": product_id,
            "category": "electronics",
            "destination_region": "mexico",
            "max_results": 3,
        },
    ).json()

    fetched = client.get(f"/api/sourcing/runs/{created['correlation_id']}")

    assert fetched.status_code == 200
    assert fetched.json()["quotes"] == created["quotes"]


def test_get_sourcing_run_404s_for_an_unknown_correlation_id(client: TestClient):
    response = client.get("/api/sourcing/runs/does-not-exist")

    assert response.status_code == 404


def test_create_sourcing_run_404s_for_an_unknown_product(client: TestClient):
    response = client.post(
        "/api/sourcing/runs",
        json={
            "product_id": "does-not-exist",
            "category": "electronics",
            "destination_region": "mexico",
            "max_results": 3,
        },
    )

    assert response.status_code == 404


def test_list_product_suppliers_returns_existing_quotes_for_a_product(client: TestClient):
    product_id = _create_product(client)
    client.post(
        "/api/sourcing/runs",
        json={
            "product_id": product_id,
            "category": "electronics",
            "destination_region": "mexico",
            "max_results": 3,
        },
    )

    response = client.get(f"/api/products/{product_id}/suppliers")

    assert response.status_code == 200
    quotes = response.json()
    assert len(quotes) > 0
    assert all(q["product_id"] == product_id for q in quotes)


# --- Milestone 39: entrada manual y hechos con procedencia -------------------


def _create_supplier(client: TestClient, **body) -> dict:
    payload = {"name": "Fábrica Real S.L.", "country": "ES", "city": "Valencia", **body}
    response = client.post("/api/suppliers", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_a_supplier_can_be_entered_by_hand_and_read_back(client: TestClient):
    created = _create_supplier(client, website="https://fabrica.example")

    listed = client.get("/api/suppliers")
    fetched = client.get(f"/api/suppliers/{created['id']}")

    assert listed.status_code == 200
    assert [s["id"] for s in listed.json()] == [created["id"]]
    assert fetched.json()["verification"] == "supplier_claim"
    assert fetched.json()["identity_key"]


def test_an_unknown_supplier_is_a_404(client: TestClient):
    assert client.get("/api/suppliers/nope").status_code == 404


def test_declaring_third_party_verification_without_an_issuer_is_a_422(client: TestClient):
    response = client.post(
        "/api/suppliers", json={"name": "Audited Co", "verification": "third_party_verified"}
    )

    assert response.status_code == 422
    assert "verifier" in response.json()["detail"]


def test_a_real_quote_can_be_recorded_against_a_product(client: TestClient):
    product_id = _create_product(client)
    supplier = _create_supplier(client)

    response = client.post(
        f"/api/suppliers/{supplier['id']}/quotes",
        json={
            "product_id": product_id,
            "unit_price": 6.4,
            "currency": "EUR",
            "moq": 25,
            "incoterm": "DDP",
            "payment_terms": "50 % anticipo, 50 % a 30 días",
            "destination_market": "eu",
            "logistics_cost_per_unit": 0.42,
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["currency"] == "EUR"
    assert body["incoterm"] == "DDP"
    assert body["total_landed_cost_per_unit"] == 6.82
    assert body["provenance"] == "supplier_claim"


def test_a_price_without_a_currency_is_a_422(client: TestClient):
    product_id = _create_product(client)
    supplier = _create_supplier(client)

    response = client.post(
        f"/api/suppliers/{supplier['id']}/quotes",
        json={"product_id": product_id, "unit_price": 6.4},
    )

    assert response.status_code == 422


def test_an_incoterm_that_does_not_exist_is_a_422(client: TestClient):
    product_id = _create_product(client)
    supplier = _create_supplier(client)

    response = client.post(
        f"/api/suppliers/{supplier['id']}/quotes",
        json={"product_id": product_id, "incoterm": "DPP"},
    )

    assert response.status_code == 422


def test_capabilities_can_be_declared_and_come_back_with_their_provenance(client: TestClient):
    product_id = _create_product(client)
    supplier = _create_supplier(client)
    client.post(
        f"/api/suppliers/{supplier['id']}/quotes",
        json={"product_id": product_id, "unit_price": 6.4, "currency": "EUR"},
    )

    declared = client.post(
        f"/api/suppliers/{supplier['id']}/capabilities",
        json={"capability": "dropshipping", "supported": True, "note": "desde 20 unidades"},
    )
    assert declared.status_code == 201, declared.text

    quotes = client.get(f"/api/products/{product_id}/suppliers").json()
    by_name = {c["capability"]: c for c in quotes[0]["capabilities"]}

    assert len(by_name) == 8
    assert by_name["dropshipping"] == {
        "capability": "dropshipping",
        "supported": True,
        "provenance": "supplier_claim",
        "source": None,
        "note": "desde 20 unidades",
        "observed_at": by_name["dropshipping"]["observed_at"],
        "product_specific": False,
    }
    # Lo que nadie ha declarado responde «no se sabe», nunca «no».
    assert by_name["sla"]["supported"] is None
    assert by_name["sla"]["provenance"] == "unknown"


def test_the_gaps_that_block_the_no_stock_model_are_listed(client: TestClient):
    product_id = _create_product(client)
    supplier = _create_supplier(client)
    client.post(
        f"/api/suppliers/{supplier['id']}/quotes",
        json={"product_id": product_id, "unit_price": 6.4, "currency": "EUR"},
    )

    quotes = client.get(f"/api/products/{product_id}/suppliers").json()

    assert "eu_return_address" in quotes[0]["unanswered_capabilities"]


def test_a_quote_carries_the_eight_risk_dimensions_and_no_total(client: TestClient):
    product_id = _create_product(client)
    supplier = _create_supplier(client)
    client.post(
        f"/api/suppliers/{supplier['id']}/quotes",
        json={"product_id": product_id, "unit_price": 6.4, "currency": "EUR"},
    )

    detail = client.get(f"/api/products/{product_id}/suppliers").json()[0]

    assert len(detail["risk"]) == 8
    assert all(r["rationale"] for r in detail["risk"])
    assert "risk_score" not in detail
    assert "overall_risk" not in detail


def test_quotes_without_a_landed_cost_are_listed_last_not_first(client: TestClient):
    product_id = _create_product(client)
    priced = _create_supplier(client, name="Con precio")
    silent = _create_supplier(client, name="Sin precio")
    client.post(
        f"/api/suppliers/{priced['id']}/quotes",
        json={
            "product_id": product_id,
            "unit_price": 6.4,
            "currency": "EUR",
            "logistics_cost_per_unit": 0.4,
        },
    )
    client.post(f"/api/suppliers/{silent['id']}/quotes", json={"product_id": product_id})

    quotes = client.get(f"/api/products/{product_id}/suppliers").json()

    assert [q["supplier"]["name"] for q in quotes] == ["Con precio", "Sin precio"]
    assert quotes[1]["total_landed_cost_per_unit"] is None
