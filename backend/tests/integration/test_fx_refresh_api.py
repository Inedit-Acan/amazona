"""Los endpoints, el trabajo `fx.refresh` y el análisis económico con tasas del BCE
(Milestone 42, ADR 0020).

La autorización por rol la cubren los inventarios de `test_api_authorization.py` y
`test_permission_matrix.py`; aquí se prueba lo que la ruta hace una vez autorizada.
La fuente se sustituye por una falsa: ninguna prueba toca la red.
"""

import datetime
from decimal import Decimal

import pytest
from ecb_test_support import ADMITTED, OMITTED, FakeFeed, rate_set, real_settings
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.costs.service import ApiBudgetExceededError
from app.db.base import Base
from app.db.models.exchange_rate import ExchangeRate as Row
from app.db.models.product import Product
from app.db.models.product_analysis import ProductAnalysis
from app.db.models.supplier import Supplier
from app.db.models.supplier_quote import SupplierQuote
from app.db.session import get_db
from app.economics.service import EconomicAnalysisService
from app.integrations.fx.ecb import FeedUnavailableError
from app.jobs import handlers
from app.jobs.handlers import FX_REFRESH, run_fx_refresh
from app.jobs.registry import known_types
from app.jobs.schemas import JobBlockedError, JobContext
from app.main import app
from app.money.fx_refresh import FxRefreshService

TODAY = datetime.datetime.now(datetime.UTC).date()
YESTERDAY = TODAY - datetime.timedelta(days=1)


@pytest.fixture()
def session_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, expire_on_commit=False)
    engine.dispose()


@pytest.fixture()
def client(session_factory):
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


def use_feed(monkeypatch, feed: FakeFeed, settings: Settings | None = None) -> None:
    """Sustituye la construcción del servicio por una con fuente falsa y la fuente
    real activada, en el endpoint y en el trabajo."""
    def build(db):
        return FxRefreshService(db, settings or real_settings(), feed=feed)

    monkeypatch.setattr("app.api.economics.FxRefreshService", build)
    monkeypatch.setattr(handlers, "FxRefreshService", build)


# --- POST /api/exchange-rates/refresh -----------------------------------------


def test_refresh_reports_what_it_did_including_what_it_left_out(client, monkeypatch):
    use_feed(monkeypatch, FakeFeed(daily=rate_set(YESTERDAY)))

    response = client.post("/api/exchange-rates/refresh")

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "daily"
    assert body["latest_effective_date"] == YESTERDAY.isoformat()
    assert body["stored"] == len(ADMITTED)
    assert body["unchanged"] == 0
    assert body["republished"] == []
    assert body["omitted_currencies"] == OMITTED
    assert body["ingested_at"]


def test_refresh_twice_is_idempotent(client, monkeypatch):
    use_feed(monkeypatch, FakeFeed(daily=rate_set(YESTERDAY)))
    client.post("/api/exchange-rates/refresh")

    body = client.post("/api/exchange-rates/refresh").json()

    assert body["stored"] == 0
    assert body["unchanged"] == len(ADMITTED)
    assert len(client.get("/api/exchange-rates").json()) == len(ADMITTED)


def test_a_republication_shows_up_in_the_response(client, monkeypatch):
    use_feed(monkeypatch, FakeFeed(daily=rate_set(YESTERDAY)))
    client.post("/api/exchange-rates/refresh")
    use_feed(monkeypatch, FakeFeed(daily=rate_set(YESTERDAY, {"USD": Decimal("1.1400"), "GBP": Decimal("0.85718")})))

    body = client.post("/api/exchange-rates/refresh").json()

    assert body["republished"] == [
        {"pair": "EUR/USD", "effective_date": YESTERDAY.isoformat(), "previous_rate": "1.1355", "new_rate": "1.1400"}
    ]


def test_the_listing_exposes_source_dates_provenance_attribution_and_the_warning(client, monkeypatch):
    use_feed(monkeypatch, FakeFeed(daily=rate_set(YESTERDAY)))
    client.post("/api/exchange-rates/refresh")

    usd = next(r for r in client.get("/api/exchange-rates").json() if r["quote_currency"] == "USD")

    assert usd["source"] == "ecb:eurofxref"
    assert usd["effective_date"] == YESTERDAY.isoformat()
    assert usd["ingested_at"]
    assert usd["provenance"] == "third_party_verified"
    assert usd["declared_by"] == "European Central Bank"
    assert "Banco Central Europeo" in usd["attribution"]
    assert "no es la tasa transaccional" in usd["notice"]


def test_a_declared_rate_carries_no_ecb_attribution(client):
    client.post(
        "/api/exchange-rates",
        json={
            "base_currency": "USD",
            "quote_currency": "EUR",
            "rate": "0.92",
            "effective_date": (datetime.datetime.now(datetime.UTC).date()).isoformat(),
        },
    )

    (row,) = client.get("/api/exchange-rates").json()
    assert row["attribution"] is None and row["notice"] is None
    assert row["ingested_at"]


def test_the_ecb_source_prefix_is_reserved_to_the_refresh(client):
    response = client.post(
        "/api/exchange-rates",
        json={
            "base_currency": "USD",
            "quote_currency": "EUR",
            "rate": "0.92",
            "effective_date": YESTERDAY.isoformat(),
            "source": "ecb:eurofxref",
            "provenance": "third_party_verified",
            "declared_by": "someone",
        },
    )

    assert response.status_code == 422
    assert client.get("/api/exchange-rates").json() == []


@pytest.mark.parametrize(
    ("failure", "status"),
    [
        (FeedUnavailableError("the ECB did not answer"), 502),
        (ApiBudgetExceededError("no room"), 429),
    ],
)
def test_source_failures_map_to_502_and_429_and_store_nothing(client, monkeypatch, failure, status):
    use_feed(monkeypatch, FakeFeed(daily=failure))

    response = client.post("/api/exchange-rates/refresh")

    assert response.status_code == status
    assert client.get("/api/exchange-rates").json() == []


def test_without_a_real_source_configured_refresh_is_a_409(client):
    """Por defecto `EXCHANGE_RATE_PROVIDER` es `mock`: no se llama a nadie."""
    response = client.post("/api/exchange-rates/refresh")

    assert response.status_code == 409
    assert "EXCHANGE_RATE_PROVIDER" in response.json()["detail"]


# --- POST /api/exchange-rates/backfill ----------------------------------------


def test_backfill_is_its_own_explicit_request(client, monkeypatch):
    feed = FakeFeed(history=[rate_set(TODAY - datetime.timedelta(days=n)) for n in (1, 4)])
    use_feed(monkeypatch, feed)

    body = client.post("/api/exchange-rates/backfill").json()

    assert body["mode"] == "backfill"
    assert body["days_examined"] == 2
    assert body["stored"] == 2 * len(ADMITTED)
    assert feed.daily_calls == 0


def test_a_failed_refresh_does_not_trigger_a_backfill(client, monkeypatch):
    feed = FakeFeed(daily=FeedUnavailableError("down"), history=[rate_set(YESTERDAY)])
    use_feed(monkeypatch, feed)

    assert client.post("/api/exchange-rates/refresh").status_code == 502

    assert feed.history_calls == 0


# --- El trabajo fx.refresh ----------------------------------------------------


def context() -> JobContext:
    return JobContext(
        job_id="job-1",
        correlation_id="corr-1",
        attempt=1,
        heartbeat=lambda: None,
        started_at=datetime.datetime.now(datetime.UTC),
    )


def test_the_job_type_is_registered():
    assert FX_REFRESH == "fx.refresh"
    assert FX_REFRESH in known_types()


def test_the_job_refreshes_the_daily_file_and_reports_the_summary(session_factory, monkeypatch):
    feed = FakeFeed(daily=rate_set(YESTERDAY), history=[rate_set(YESTERDAY)])
    use_feed(monkeypatch, feed)
    db = session_factory()

    result = run_fx_refresh({}, context(), db)

    assert result.reference == "corr-1"
    assert result.detail["stored"] == len(ADMITTED)
    assert result.detail["omitted_currencies"] == OMITTED
    assert feed.history_calls == 0


def test_the_job_refuses_to_backfill(session_factory, monkeypatch):
    use_feed(monkeypatch, FakeFeed(daily=rate_set(YESTERDAY)))

    with pytest.raises(ValueError, match="explicit"):
        run_fx_refresh({"mode": "backfill"}, context(), session_factory())


def test_the_job_blocks_instead_of_retrying_when_nothing_can_be_called(session_factory, monkeypatch):
    use_feed(monkeypatch, FakeFeed(daily=rate_set(YESTERDAY)), settings=Settings(_env_file=None))

    with pytest.raises(JobBlockedError):
        run_fx_refresh({}, context(), session_factory())


def test_the_job_blocks_when_the_budget_denies_the_call(session_factory, monkeypatch):
    use_feed(monkeypatch, FakeFeed(daily=ApiBudgetExceededError("no room")))

    with pytest.raises(JobBlockedError):
        run_fx_refresh({}, context(), session_factory())


def test_the_job_lets_a_source_failure_propagate_so_the_runtime_retries_it(session_factory, monkeypatch):
    use_feed(monkeypatch, FakeFeed(daily=FeedUnavailableError("down")))

    with pytest.raises(FeedUnavailableError):
        run_fx_refresh({}, context(), session_factory())


# --- El análisis económico lee de la base, nunca de la red --------------------


@pytest.fixture()
def economics(session_factory, monkeypatch):
    db = session_factory()
    product = Product(name="Wireless earbuds", category="electronics", created_by="owner")
    db.add(product)
    db.commit()
    db.add(
        ProductAnalysis(
            product_id=product.id,
            analysis_type="research",
            opportunity_score=0.6,
            confidence=0.85,
            data={"demand_signal": 0.6, "competition_level": "low"},
            correlation_id="corr-research",
        )
    )
    supplier = Supplier(name="Fábrica Real S.L.", verification="supplier_claim", region="cn")
    db.add(supplier)
    db.commit()
    quote = SupplierQuote(
        product_id=product.id,
        supplier_id=supplier.id,
        correlation_id="corr-sourcing",
        unit_price=4.0,
        currency="USD",
        provenance="supplier_claim",
        source="manual:owner",
        logistics_cost_per_unit=1.0,
        logistics_provenance="supplier_claim",
        incoterm="DDP",
        destination_market="eu",
        moq=10,
        lead_time_days=7,
    )
    db.add(quote)
    db.commit()

    class Config:
        allows_simulated_providers = False
        exchange_rate_provider = real_settings().exchange_rate_provider
        ecb_rate_max_age_days = 7

    monkeypatch.setattr("app.money.resolver.get_settings", lambda: Config())
    return db, product, quote


def analyse(db, product, quote):
    return EconomicAnalysisService(db).run_analysis(
        product_id=product.id,
        supplier_quote_id=quote.id,
        sale_price=20.0,
        monthly_fixed_costs=500.0,
        monthly_unit_sales_base=300.0,
        units_per_order=1,
        payment_cost_per_unit=0.83,
        correlation_id="corr-econ",
        on=TODAY,
    )


def test_an_analysis_converts_with_the_stored_ecb_reference_and_says_so(economics):
    db, product, quote = economics
    FxRefreshService(db, real_settings(), feed=FakeFeed(daily=rate_set(YESTERDAY))).refresh_daily(
        actor="owner"
    )

    analysis = analyse(db, product, quote)

    assert analysis.margin_evaluability == "evaluable"
    assert len(analysis.fx_conversions) == 2
    for conversion in analysis.fx_conversions:
        assert conversion["pair"] == "EUR/USD"
        assert conversion["direction"] == "inverted"
        assert conversion["source"] == "ecb:eurofxref"
        assert conversion["provenance"] == "third_party_verified"
        assert conversion["effective_date"] == YESTERDAY.isoformat()
        assert conversion["ingested_at"]


def test_the_analysis_makes_no_http_request(economics, monkeypatch):
    """Sin nada guardado, el análisis es no evaluable: no va a buscar la tasa."""
    db, product, quote = economics

    def no_network(*args, **kwargs):
        raise AssertionError("the economic analysis must never touch the network")

    monkeypatch.setattr("httpx.Client.get", no_network)

    analysis = analyse(db, product, quote)

    assert analysis.margin_evaluability == "not_evaluable"
    assert "exchange_rate" in analysis.missing_inputs


def test_an_eight_day_old_reference_leaves_the_margin_not_evaluable_and_never_no_go(economics):
    db, product, quote = economics
    old = TODAY - datetime.timedelta(days=8)
    FxRefreshService(db, real_settings(), feed=FakeFeed(daily=rate_set(old))).refresh_daily(actor="owner")

    analysis = analyse(db, product, quote)

    assert analysis.margin_evaluability == "not_evaluable"
    assert analysis.margin_percent is None
    assert analysis.recommendation != "NO_GO"


def test_a_stale_manual_rate_falls_back_to_the_fresh_reference_in_the_analysis(economics):
    db, product, quote = economics
    db.add(
        Row(
            base_currency="USD",
            quote_currency="EUR",
            rate=Decimal("0.50"),
            effective_date=TODAY - datetime.timedelta(days=40),
            source="manual:owner",
            provenance="declared",
        )
    )
    db.commit()
    FxRefreshService(db, real_settings(), feed=FakeFeed(daily=rate_set(YESTERDAY))).refresh_daily(
        actor="owner"
    )

    analysis = analyse(db, product, quote)

    assert analysis.margin_evaluability == "evaluable"
    assert {c["source"] for c in analysis.fx_conversions} == {"ecb:eurofxref"}
