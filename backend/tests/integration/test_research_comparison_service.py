"""El servicio de comparación y sus rutas (Milestone 35, ADR 0013).

Tres cosas: que el informe se guarde y se audite, que la evidencia mensual se
persista con su señal, y —la que más importa— que comparar **no se pueda hacer
donde los datos simulados están prohibidos**. Comparar exige ejecutar el mock, y
una excepción «solo para un informe» vaciaría la regla de la ADR 0008.
"""

import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.agents.product_research import ProductResearchAgent
from app.core.config import Environment, Settings
from app.db.base import Base
from app.db.models.audit import AuditLog
from app.db.models.product_signal import ProductSignal
from app.db.models.product_signal_observation import ProductSignalObservation
from app.db.models.research_comparison import ResearchComparison
from app.integrations.ports import CandidateSignals, Observation, ProductSignalProvider, Signal, SignalKind
from app.integrations.product_intelligence.mock import MockProductSignalProvider
from app.research.comparison_service import ComparisonNotAllowedError, ResearchComparisonService
from app.research.service import ResearchService


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


class MeasuredWithEvidence(ProductSignalProvider):
    """Una fuente real de mentira con la forma de la de verdad: mide demanda y
    trae la serie que la respalda."""

    name = "wikimedia-pageviews"

    def supports(self) -> frozenset[SignalKind]:
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
                        source="wikimedia.org/api/rest_v1/metrics/pageviews",
                        query="Air fryer",
                        market=market,
                        observed_at=datetime.datetime(2026, 9, 1, tzinfo=datetime.UTC),
                        method="monthly pageviews… PROXY FOR INTEREST — not purchase demand",
                        raw_reference="https://wikimedia.org/…/Air_fryer/monthly/…",
                        simulated=False,
                        observations=[
                            Observation(period="2026-06", value=41000.0),
                            Observation(period="2026-07", value=38000.0),
                            Observation(period="2026-08", value=45000.0),
                        ],
                    )
                ],
            )
        ]


def settings_for(environment: Environment) -> Settings:
    return Settings(environment=environment, cors_origins=["https://kova.example"])


# --- La evidencia se persiste ----------------------------------------------


def test_the_monthly_evidence_is_stored_with_its_signal(db_session: Session):
    ResearchService(db_session, agent=ProductResearchAgent(MeasuredWithEvidence())).run_research(
        category="home", keywords=[], max_results=1, correlation_id="cid-1", market="us"
    )

    signal = db_session.query(ProductSignal).one()
    observations = (
        db_session.query(ProductSignalObservation)
        .filter_by(signal_id=signal.id)
        .order_by(ProductSignalObservation.period)
        .all()
    )
    assert [o.period for o in observations] == ["2026-06", "2026-07", "2026-08"]
    # El valor crudo de la fuente, sin normalizar: la normalización vive en la
    # señal y aquí está lo que de verdad contestó la API.
    assert [o.value for o in observations] == [41000.0, 38000.0, 45000.0]


def test_a_fixture_signal_has_no_evidence_and_that_is_not_zero_evidence(db_session: Session):
    """El mock no mide una serie; no se le inventa una de ceros."""
    ResearchService(db_session, agent=ProductResearchAgent(MockProductSignalProvider())).run_research(
        category="home", keywords=[], max_results=2, correlation_id="cid-2", market="us"
    )

    assert db_session.query(ProductSignal).count() > 0
    assert db_session.query(ProductSignalObservation).count() == 0


# --- El informe -------------------------------------------------------------


def test_the_comparison_is_stored_with_its_summary(db_session: Session):
    service = ResearchComparisonService(
        db_session,
        settings=settings_for(Environment.DEVELOPMENT),
        baseline=MockProductSignalProvider(),
        candidate=MeasuredWithEvidence(),
    )

    row = service.run(category="home", market="us", max_results=3)

    stored = db_session.query(ResearchComparison).one()
    assert stored.id == row.id
    assert stored.baseline_provider == "fixtures"
    assert stored.candidate_provider == "wikimedia-pageviews"
    assert stored.summary["baseline"]["candidates"] > 0
    assert stored.summary["candidate"]["candidates"] == 1
    assert "Ningún candidato en común" in stored.summary["verdict"]


def test_the_comparison_is_audited(db_session: Session):
    ResearchComparisonService(
        db_session,
        settings=settings_for(Environment.DEVELOPMENT),
        baseline=MockProductSignalProvider(),
        candidate=MeasuredWithEvidence(),
    ).run(category="home", actor="owner@amazona.local")

    entry = db_session.query(AuditLog).filter_by(action="research.compare").one()
    assert entry.actor == "owner@amazona.local"
    assert entry.after["baseline"] == "fixtures"
    assert entry.after["shared"] == 0


def test_the_comparison_measures_what_each_one_knows(db_session: Session):
    row = ResearchComparisonService(
        db_session,
        settings=settings_for(Environment.DEVELOPMENT),
        baseline=MockProductSignalProvider(),
        candidate=MeasuredWithEvidence(),
    ).run(category="home", max_results=3)

    summary = row.summary
    assert summary["baseline"]["coverage"]["competition"] > 0
    assert "competition" not in summary["candidate"]["coverage"]
    assert summary["baseline"]["scorable"] > 0
    assert summary["candidate"]["scorable"] == 0
    assert summary["candidate"]["measured_signals"] == 1
    assert summary["baseline"]["measured_signals"] == 0


def test_comparing_writes_nothing_into_the_catalogue(db_session: Session):
    """Un informe no descubre productos: no crea `Product` ni señales."""
    ResearchComparisonService(
        db_session,
        settings=settings_for(Environment.DEVELOPMENT),
        baseline=MockProductSignalProvider(),
        candidate=MeasuredWithEvidence(),
    ).run(category="home")

    assert db_session.query(ProductSignal).count() == 0


# --- Dónde no se puede comparar ---------------------------------------------


@pytest.mark.parametrize("environment", [Environment.STAGING, Environment.PRODUCTION])
def test_comparing_is_refused_where_simulated_data_is_not_allowed(
    db_session: Session, environment: Environment
):
    """Comparar exige ejecutar el mock. Una excepción «solo para un informe»
    sería exactamente lo que vacía una regla (ADR 0008)."""
    service = ResearchComparisonService(
        db_session,
        settings=settings_for(environment),
        baseline=MockProductSignalProvider(),
        candidate=MeasuredWithEvidence(),
    )

    with pytest.raises(ComparisonNotAllowedError, match="ADR 0008"):
        service.run(category="home")

    assert db_session.query(ResearchComparison).count() == 0


@pytest.mark.parametrize("environment", [Environment.DEVELOPMENT, Environment.DEMO, Environment.TEST])
def test_comparing_is_allowed_where_fixtures_are(db_session: Session, environment: Environment):
    service = ResearchComparisonService(
        db_session,
        settings=settings_for(environment),
        baseline=MockProductSignalProvider(),
        candidate=MeasuredWithEvidence(),
    )

    assert service.run(category="home") is not None
