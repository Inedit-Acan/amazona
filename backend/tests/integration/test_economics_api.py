import datetime
from decimal import Decimal

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


def _create_product_and_quote(client: TestClient) -> tuple[str, str]:
    research = client.post("/api/research/runs", json={"category": "electronics", "max_results": 1}).json()
    product_id = research["candidates"][0]["product_id"]

    sourcing = client.post(
        "/api/sourcing/runs",
        json={
            "product_id": product_id,
            "category": "electronics",
            "destination_region": "mexico",
            "max_results": 1,
        },
    ).json()
    supplier_quote_id = sourcing["quotes"][0]["id"]
    return product_id, supplier_quote_id


def test_create_economic_analysis_run_persists_and_returns_the_report(client: TestClient):
    product_id, _ = _create_product_and_quote(client)
    quotes = client.get(f"/api/products/{product_id}/suppliers").json()
    supplier_quote_id = quotes[0]["id"]

    response = client.post(
        "/api/economics/runs",
        json={"product_id": product_id, "supplier_quote_id": supplier_quote_id, "sale_price": 20.0},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["recommendation"] in {"GO", "REVIEW", "NO_GO"}
    assert set(body["data"]["scenarios"]) == {"conservative", "base", "optimistic"}


def test_get_economic_analysis_run_reconstructs_the_same_result_from_db(client: TestClient):
    product_id, _ = _create_product_and_quote(client)
    quotes = client.get(f"/api/products/{product_id}/suppliers").json()
    supplier_quote_id = quotes[0]["id"]

    created = client.post(
        "/api/economics/runs",
        json={"product_id": product_id, "supplier_quote_id": supplier_quote_id, "sale_price": 20.0},
    ).json()

    fetched = client.get(f"/api/economics/runs/{created['correlation_id']}")

    assert fetched.status_code == 200
    assert fetched.json() == created


def test_get_economic_analysis_run_404s_for_an_unknown_correlation_id(client: TestClient):
    response = client.get("/api/economics/runs/does-not-exist")

    assert response.status_code == 404


def test_create_economic_analysis_run_404s_for_an_unknown_product(client: TestClient):
    response = client.post(
        "/api/economics/runs",
        json={"product_id": "does-not-exist", "supplier_quote_id": "does-not-exist", "sale_price": 20.0},
    )

    assert response.status_code == 404


def test_list_product_economics_returns_existing_analyses_for_a_product(client: TestClient):
    product_id, _ = _create_product_and_quote(client)
    quotes = client.get(f"/api/products/{product_id}/suppliers").json()
    supplier_quote_id = quotes[0]["id"]

    client.post(
        "/api/economics/runs",
        json={"product_id": product_id, "supplier_quote_id": supplier_quote_id, "sale_price": 20.0},
    )

    response = client.get(f"/api/products/{product_id}/economics")

    assert response.status_code == 200
    analyses = response.json()
    assert len(analyses) > 0
    assert all(a["product_id"] == product_id for a in analyses)


def test_timeseries_returns_empty_list_when_no_analyses_exist(client: TestClient):
    response = client.get("/api/economics/analyses/timeseries")

    assert response.status_code == 200
    assert response.json() == []


def test_timeseries_aggregates_todays_analyses_into_one_bucket(client: TestClient):
    product_id, _ = _create_product_and_quote(client)
    quotes = client.get(f"/api/products/{product_id}/suppliers").json()
    supplier_quote_id = quotes[0]["id"]

    client.post(
        "/api/economics/runs",
        json={"product_id": product_id, "supplier_quote_id": supplier_quote_id, "sale_price": 20.0},
    )
    client.post(
        "/api/economics/runs",
        json={"product_id": product_id, "supplier_quote_id": supplier_quote_id, "sale_price": 30.0},
    )

    response = client.get("/api/economics/analyses/timeseries", params={"days": 30})

    assert response.status_code == 200
    points = response.json()
    assert len(points) == 1
    assert points[0]["analyses_count"] == 2
    assert points[0]["avg_sale_price"] == 25.0


def test_timeseries_days_parameter_is_bounded(client: TestClient):
    too_many = client.get("/api/economics/analyses/timeseries", params={"days": 366})
    too_few = client.get("/api/economics/analyses/timeseries", params={"days": 0})

    assert too_many.status_code == 422
    assert too_few.status_code == 422


# --- Milestone 40: canal, moneda y techo de CAC ------------------------------


def _utc_today() -> datetime.date:
    """El día UTC, que es contra el que la API valida las fechas de las tasas.

    `datetime.date.today()` es el día **local** de la máquina: entre las 22:00 y las
    24:00 UTC en una zona adelantada (CEST) es ya «mañana» para la API y la tasa
    se rechazaba por estar en el futuro. Corrección de un test anterior al
    Milestone 42, descubierta durante él; la regla de producción no cambia."""
    return datetime.datetime.now(datetime.UTC).date()


def _declare_rate(client: TestClient, rate: str = "0.92") -> None:
    response = client.post(
        "/api/exchange-rates",
        json={
            "base_currency": "USD",
            "quote_currency": "EUR",
            "rate": rate,
            "effective_date": _utc_today().isoformat(),
        },
    )
    assert response.status_code == 201, response.text


def test_an_exchange_rate_can_be_declared_and_read_back(client: TestClient):
    _declare_rate(client)

    rates = client.get("/api/exchange-rates").json()

    assert len(rates) == 1
    assert rates[0]["base_currency"] == "USD"
    assert rates[0]["quote_currency"] == "EUR"
    assert rates[0]["provenance"] == "declared"
    assert rates[0]["source"].startswith("manual:")


def test_a_rate_dated_in_the_future_is_a_422(client: TestClient):
    response = client.post(
        "/api/exchange-rates",
        json={
            "base_currency": "USD",
            "quote_currency": "EUR",
            "rate": "0.92",
            "effective_date": (_utc_today() + datetime.timedelta(days=1)).isoformat(),
        },
    )

    assert response.status_code == 422
    assert "future" in response.json()["detail"]


def test_a_rate_between_a_currency_and_itself_is_a_422(client: TestClient):
    response = client.post(
        "/api/exchange-rates",
        json={
            "base_currency": "EUR",
            "quote_currency": "EUR",
            "rate": "1",
            "effective_date": _utc_today().isoformat(),
        },
    )

    assert response.status_code == 422


def test_an_analysis_declares_its_channel_currency_and_evaluability(client: TestClient):
    product_id, supplier_quote_id = _create_product_and_quote(client)

    body = client.post(
        "/api/economics/runs",
        json={
            "product_id": product_id,
            "supplier_quote_id": supplier_quote_id,
            "sale_price": 20.0,
            "channel": "own_web",
            "units_per_order": 1,
        },
    ).json()

    assert body["channel"] == "own_web"
    assert body["currency"] == "EUR"
    assert body["margin_evaluability"] == "evaluable"
    # Importes como cadena: en JavaScript un número es un float64.
    assert isinstance(body["contribution_margin_per_unit"], str)
    assert isinstance(body["max_breakeven_cac"], str)


def test_without_units_per_order_the_cac_ceiling_is_not_evaluable(client: TestClient):
    """Un 1 que nadie ha declarado no vale."""
    product_id, supplier_quote_id = _create_product_and_quote(client)

    body = client.post(
        "/api/economics/runs",
        json={
            "product_id": product_id,
            "supplier_quote_id": supplier_quote_id,
            "sale_price": 20.0,
        },
    ).json()

    assert body["margin_evaluability"] == "evaluable"
    assert body["cac_evaluability"] == "not_evaluable"
    assert body["max_breakeven_cac"] is None
    assert "units_per_order" in body["missing_inputs"]


def test_more_units_per_order_raise_the_ceiling_without_touching_the_unit_margin(
    client: TestClient,
):
    product_id, supplier_quote_id = _create_product_and_quote(client)

    def run(units: int) -> dict:
        return client.post(
            "/api/economics/runs",
            json={
                "product_id": product_id,
                "supplier_quote_id": supplier_quote_id,
                "sale_price": 20.0,
                "units_per_order": units,
                "monthly_unit_sales_base": 300.0,
            },
        ).json()

    one, three = run(1), run(3)

    assert one["contribution_margin_per_unit"] == three["contribution_margin_per_unit"]
    assert Decimal(three["max_breakeven_cac"]) > Decimal(one["max_breakeven_cac"])


def test_the_breakdown_explains_where_every_figure_comes_from(client: TestClient):
    product_id, supplier_quote_id = _create_product_and_quote(client)

    body = client.post(
        "/api/economics/runs",
        json={
            "product_id": product_id,
            "supplier_quote_id": supplier_quote_id,
            "sale_price": 20.0,
            "units_per_order": 1,
        },
    ).json()

    components = {c["concept"]: c for c in body["data"]["unit_economics"]["components"]}
    assert set(components) == {
        "product",
        "logistics",
        "import",
        "channel",
        "payment",
        "other_variable",
    }
    assert all(c["provenance"] for c in components.values())
    # El precio viene del mock, así que el margen entero es simulado y lo dice.
    assert body["data"]["unit_economics"]["weakest_provenance"] == "simulated"
