"""La procedencia, persistida (Milestone 34, plan maestro §8).

«Nunca almacenar solo un número final sin procedencia.» Esto comprueba que cada
señal que el agente produce llega a `product_signals` con los nueve campos, y
que de la base de datos se puede volver a responder la pregunta que antes no se
podía: **¿esto es real o inventado?**
"""

import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.agents.product_research import ProductResearchAgent
from app.db.base import Base
from app.db.models.audit import AuditLog
from app.db.models.product_analysis import ProductAnalysis
from app.db.models.product_signal import ProductSignal
from app.integrations.ports import CandidateSignals, ProductSignalProvider, Signal, SignalKind
from app.integrations.product_intelligence.composite import CompositeProductSignalProvider
from app.integrations.product_intelligence.mock import MockProductSignalProvider
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


class MeasuredDemandOnly(ProductSignalProvider):
    """Una fuente real de mentira, con la forma de la de verdad: sabe de
    demanda y de nada más."""

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
                        confidence=0.55,
                        provider="wikimedia-pageviews",
                        source="wikimedia.org/api/rest_v1/metrics/pageviews",
                        query="Air fryer",
                        market=market,
                        observed_at=datetime.datetime(2026, 9, 1, tzinfo=datetime.UTC),
                        method="monthly pageviews… PROXY FOR INTEREST — not purchase demand",
                        raw_reference="https://wikimedia.org/api/rest_v1/…/Air_fryer/monthly/…",
                        simulated=False,
                    )
                ],
            )
        ]


def run(db: Session, provider: ProductSignalProvider, correlation_id: str = "cid-1") -> None:
    ResearchService(db, agent=ProductResearchAgent(provider)).run_research(
        category="home", keywords=[], max_results=3, correlation_id=correlation_id, market="us"
    )


def test_every_signal_is_persisted_with_its_nine_fields(db_session: Session):
    run(db_session, MeasuredDemandOnly())

    signal = db_session.query(ProductSignal).one()
    assert signal.kind == "demand"
    assert signal.value == 0.62
    assert signal.confidence == 0.55
    assert signal.provider == "wikimedia-pageviews"
    assert signal.source.startswith("wikimedia.org")
    assert signal.query == "Air fryer"
    assert signal.market == "us"
    assert signal.observed_at is not None
    assert "PROXY FOR INTEREST" in signal.method
    assert signal.raw_reference.startswith("https://")
    assert signal.simulated is False
    assert signal.correlation_id == "cid-1"


def test_the_database_can_answer_what_is_real_and_what_is_invented(db_session: Session):
    """La pregunta que antes no se podía hacer."""
    run(db_session, MeasuredDemandOnly(), correlation_id="cid-real")
    run(db_session, MockProductSignalProvider(), correlation_id="cid-mock")

    real = db_session.query(ProductSignal).filter_by(simulated=False).all()
    invented = db_session.query(ProductSignal).filter_by(simulated=True).all()

    assert {s.provider for s in real} == {"wikimedia-pageviews"}
    assert {s.provider for s in invented} == {"fixtures"}
    assert len(invented) > len(real)


def test_the_fixture_run_persists_five_signals_per_candidate(db_session: Session):
    run(db_session, MockProductSignalProvider())

    analyses = db_session.query(ProductAnalysis).all()
    signals = db_session.query(ProductSignal).all()

    assert len(signals) == 5 * len(analyses)
    assert {s.kind for s in signals} == {
        "demand",
        "competition",
        "future_outlook",
        "regulatory_risk",
        "scalability",
    }


def test_the_filler_cannot_complete_a_product_it_knows_nothing_about(db_session: Session):
    """Consecuencia real de la composición, y es la correcta.

    La fuente real descubre por término («Air fryer») y el relleno solo sabe de
    los suyos («Silicone kitchen organizer»…). Como no coinciden, el relleno no
    tiene nada que decir sobre el candidato real: su demanda queda medida, su
    competencia queda **ausente**, y el score sin calcular. La alternativa sería
    inventarle un nivel de competencia a un producto real, que es exactamente lo
    que este milestone existe para impedir.
    """
    composite = CompositeProductSignalProvider([MeasuredDemandOnly(), MockProductSignalProvider()])

    run(db_session, composite)

    analysis = db_session.query(ProductAnalysis).one()
    assert analysis.data["provenance"] == "real"
    assert analysis.opportunity_score is None
    signals = {s.kind: s for s in db_session.query(ProductSignal).all()}
    assert signals["demand"].simulated is False
    assert "competition" not in signals


def test_the_analysis_still_holds_the_score_and_the_signals_explain_it(db_session: Session):
    """Aditivo: `product_analyses` no cambia de forma, `product_signals` dice
    de qué está hecho lo que guarda."""
    run(db_session, MockProductSignalProvider())

    analysis = db_session.query(ProductAnalysis).first()
    assert analysis.opportunity_score is not None
    assert analysis.data["provenance"] == "simulated"

    signals = db_session.query(ProductSignal).filter_by(product_id=analysis.product_id).all()
    demand = next(s for s in signals if s.kind == "demand")
    assert demand.value == analysis.data["demand_signal"]


def test_the_audit_entry_says_what_the_run_was_made_of(db_session: Session):
    run(db_session, MeasuredDemandOnly())

    entry = db_session.query(AuditLog).filter_by(action="research.run").one()
    assert entry.after["provenance"] == ["real"]


def test_a_source_that_finds_nothing_persists_nothing_invented(db_session: Session):
    """Sin datos no hay señales — y tampoco ceros que parecerían datos."""

    class FindsNothing(ProductSignalProvider):
        name = "empty"

        def supports(self):
            return frozenset({SignalKind.DEMAND})

        def discover(self, *, category, keywords, market, max_results):
            return []

    run(db_session, FindsNothing())

    assert db_session.query(ProductSignal).count() == 0
    assert db_session.query(ProductAnalysis).count() == 0


def test_the_filler_does_complete_a_product_it_does_know(db_session: Session):
    """Cuando los nombres sí coinciden, el relleno completa lo que falta y el
    candidato queda marcado como mixto: medido a medias."""

    class MeasuredKnownProduct(MeasuredDemandOnly):
        def discover(self, *, category, keywords, market, max_results):
            candidates = super().discover(
                category=category, keywords=keywords, market=market, max_results=max_results
            )
            measured = candidates[0]
            return [
                CandidateSignals(
                    name="Silicone kitchen organizer",
                    category=category,
                    signals=measured.signals,
                )
            ]

    composite = CompositeProductSignalProvider([MeasuredKnownProduct(), MockProductSignalProvider()])

    run(db_session, composite)

    analysis = db_session.query(ProductAnalysis).one()
    assert analysis.data["provenance"] == "mixed"
    assert analysis.opportunity_score is not None
    signals = {s.kind: s for s in db_session.query(ProductSignal).all()}
    assert signals["demand"].simulated is False
    assert signals["competition"].simulated is True
