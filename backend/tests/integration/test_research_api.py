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


def test_create_research_run_persists_and_returns_ranked_candidates(client: TestClient):
    response = client.post("/api/research/runs", json={"category": "electronics", "max_results": 3})

    assert response.status_code == 201
    body = response.json()
    assert 1 <= len(body["candidates"]) <= 3
    scores = [c["opportunity_score"] for c in body["candidates"]]
    assert scores == sorted(scores, reverse=True)


def test_get_research_run_reconstructs_the_same_result_from_db(client: TestClient):
    created = client.post("/api/research/runs", json={"category": "home", "max_results": 5}).json()

    fetched = client.get(f"/api/research/runs/{created['correlation_id']}")

    assert fetched.status_code == 200
    assert fetched.json()["candidates"] == created["candidates"]


def test_get_research_run_404s_for_an_unknown_correlation_id(client: TestClient):
    response = client.get("/api/research/runs/does-not-exist")

    assert response.status_code == 404


def test_products_endpoint_lists_research_candidates_by_status(client: TestClient):
    client.post("/api/research/runs", json={"category": "accessories", "max_results": 5})

    response = client.get("/api/products", params={"status": "CANDIDATE"})

    assert response.status_code == 200
    products = response.json()
    assert len(products) > 0
    assert all(p["status"] == "CANDIDATE" for p in products)
    assert all(p["source"] == "research" for p in products)


# --- Comparar lo real contra el mock (Milestone 35) -------------------------


def fake_real_provider():
    """Una fuente real de mentira con la forma de la de verdad, para no salir a
    internet desde un test."""
    import datetime

    from app.integrations.ports import CandidateSignals, Signal, SignalKind

    class Measured:
        name = "wikimedia-pageviews"

        def supports(self):
            return frozenset({SignalKind.DEMAND})

        def discover(self, *, category, keywords, market, max_results):
            return [
                CandidateSignals(
                    name="Air fryer",
                    category=category,
                    signals=[
                        Signal(
                            kind=SignalKind.DEMAND,
                            value=0.62,
                            confidence=0.6,
                            provider="wikimedia-pageviews",
                            source="wikimedia.org",
                            query="Air fryer",
                            market=market,
                            observed_at=datetime.datetime.now(datetime.UTC),
                            method="PROXY FOR INTEREST — not purchase demand",
                            raw_reference="https://wikimedia.org/…",
                            simulated=False,
                        )
                    ],
                )
            ]

    return Measured()


@pytest.fixture()
def offline_real_source(monkeypatch):
    """El endpoint resuelve su proveedor del registro; aquí se sustituye por uno
    que no toca la red."""
    from app.research import comparison_service

    monkeypatch.setattr(
        comparison_service.ResearchComparisonService,
        "_configured_candidate",
        lambda self: fake_real_provider(),
    )


def test_creating_a_comparison_returns_the_report(client: TestClient, offline_real_source):
    response = client.post("/api/research/comparisons", json={"category": "home", "max_results": 3})

    assert response.status_code == 201
    body = response.json()
    assert body["baseline_provider"] == "fixtures"
    assert body["candidate_provider"] == "wikimedia-pageviews"
    assert body["summary"]["baseline"]["candidates"] > 0
    assert body["summary"]["candidate"]["candidates"] == 1


def test_the_report_explains_a_zero_overlap_instead_of_looking_empty(
    client: TestClient, offline_real_source
):
    body = client.post("/api/research/comparisons", json={"category": "home"}).json()

    assert body["summary"]["shared"] == []
    assert "Ningún candidato en común" in body["summary"]["verdict"]


def test_a_comparison_can_be_read_back(client: TestClient, offline_real_source):
    created = client.post("/api/research/comparisons", json={"category": "home"}).json()

    fetched = client.get(f"/api/research/comparisons/{created['id']}")

    assert fetched.status_code == 200
    assert fetched.json()["summary"] == created["summary"]


def test_comparisons_are_listed_most_recent_first(client: TestClient, offline_real_source):
    client.post("/api/research/comparisons", json={"category": "home"})
    second = client.post("/api/research/comparisons", json={"category": "electronics"}).json()

    listed = client.get("/api/research/comparisons").json()

    assert listed[0]["id"] == second["id"]


def test_an_unknown_comparison_is_404(client: TestClient):
    assert client.get("/api/research/comparisons/does-not-exist").status_code == 404


def test_comparing_is_refused_where_fixtures_are_not_allowed(client: TestClient, monkeypatch):
    """Comparar exige ejecutar el mock: en staging y producción eso no se hace
    ni para un informe (ADR 0008)."""
    from app.core.config import Environment, Settings
    from app.research import comparison_service

    original = comparison_service.get_settings
    monkeypatch.setattr(
        comparison_service,
        "get_settings",
        lambda: Settings(environment=Environment.PRODUCTION, cors_origins=["https://kova.example"]),
    )
    try:
        response = client.post("/api/research/comparisons", json={"category": "home"})
    finally:
        monkeypatch.setattr(comparison_service, "get_settings", original)

    assert response.status_code == 409
    assert "ADR 0008" in response.json()["detail"]
