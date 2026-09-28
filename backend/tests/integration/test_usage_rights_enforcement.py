"""Los derechos de uso, aplicados y no solo escritos (Milestone 37, ADR 0015).

Una matriz de licencias que nadie consulta es documentación. Lo que estas pruebas
protegen es que el sistema **pregunte** antes de guardar y antes de puntuar, y que
un `UNKNOWN` se comporte como un «no».

El caso concreto que esto evita: conectar eBay antes de resolver si Browse es una
«Restricted API» y descubrir tres meses después que sus cifras llevaban un
trimestre alimentando un score.
"""

import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.agents.product_research import ProductResearchAgent
from app.db.base import Base
from app.db.models.audit import AuditLog
from app.db.models.product_signal import ProductSignal
from app.integrations.ports import (
    CandidateSignals,
    ProductSignalProvider,
    Signal,
    SignalBasis,
    SignalKind,
)
from app.research.service import ResearchService

#: Un proveedor real de mentira cuya licencia nadie ha leído: todo `UNKNOWN`, y
#: por tanto nada permitido.
UNREAD = "un-proveedor-sin-licencia-leida"


class TwoSignalProvider(ProductSignalProvider):
    """Da demanda y competencia, atribuidas a quien se le diga."""

    name = "de-mentira"

    def __init__(self, demand_provider: str, competition_provider: str) -> None:
        self._demand_provider = demand_provider
        self._competition_provider = competition_provider

    def supports(self) -> frozenset[SignalKind]:
        return frozenset({SignalKind.DEMAND, SignalKind.COMPETITION})

    def _signal(self, kind: SignalKind, value: float, provider: str) -> Signal:
        return Signal(
            kind=kind,
            value=value,
            confidence=0.6,
            provider=provider,
            source="somewhere",
            query="Air fryer",
            market="us",
            observed_at=datetime.datetime(2026, 9, 28, tzinfo=datetime.UTC),
            method="…",
            basis=SignalBasis.MEASURED,
        )

    def discover(self, *, category, keywords, market, max_results, channels=None):
        return [
            CandidateSignals(
                name="Air fryer",
                category=category,
                signals=[
                    self._signal(SignalKind.DEMAND, 0.8, self._demand_provider),
                    self._signal(SignalKind.COMPETITION, 0.2, self._competition_provider),
                ],
            )
        ]


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


def agent_for(demand_provider: str, competition_provider: str) -> ProductResearchAgent:
    return ProductResearchAgent(
        trends_provider=TwoSignalProvider(demand_provider, competition_provider)
    )


def run(db: Session, agent: ProductResearchAgent, correlation_id: str = "cid-1"):
    return ResearchService(db, agent=agent).run_research(
        category="home", keywords=None, max_results=1, correlation_id=correlation_id
    )


# --- Puntuar ----------------------------------------------------------------


def test_a_signal_whose_licence_allows_scoring_produces_a_score():
    result = agent_for("wikimedia-pageviews", "wikimedia-pageviews").run(
        {"category": "home", "max_results": 1}
    )

    [candidate] = result.data["candidates"]
    assert candidate["opportunity_score"] is not None
    assert candidate["scoring_withheld_from"] == []


def test_a_signal_with_an_unread_licence_does_not_reach_the_score():
    """Está medida, está guardada si su licencia lo permite, y **no puntúa**."""
    result = agent_for("wikimedia-pageviews", UNREAD).run({"category": "home", "max_results": 1})

    [candidate] = result.data["candidates"]
    assert candidate["opportunity_score"] is None
    assert candidate["scoring_withheld_from"] == [UNREAD]


def test_the_value_is_still_shown_even_when_it_cannot_be_scored():
    """Enseñarlo en el panel del propietario es uso interno, no redistribución.
    Lo que no se puede es meterlo en un número que decide."""
    result = agent_for("wikimedia-pageviews", UNREAD).run({"category": "home", "max_results": 1})

    [candidate] = result.data["candidates"]
    assert candidate["competition_level"] is not None


def test_a_withheld_score_says_who_withheld_it():
    """Un score ausente sin explicación es indistinguible de una avería."""
    result = agent_for(UNREAD, UNREAD).run({"category": "home", "max_results": 1})

    [candidate] = result.data["candidates"]
    assert candidate["scoring_withheld_from"] == [UNREAD]
    assert candidate["provenance"] == "unknown"


# --- Guardar ----------------------------------------------------------------


def test_a_signal_whose_licence_allows_storage_is_persisted(db_session: Session):
    run(db_session, agent_for("wikimedia-pageviews", "wikimedia-pageviews"))

    kinds = {row.kind for row in db_session.query(ProductSignal).all()}
    assert kinds == {"demand", "competition"}


def test_a_signal_with_an_unread_licence_is_not_persisted(db_session: Session):
    run(db_session, agent_for("wikimedia-pageviews", UNREAD))

    kinds = {row.kind for row in db_session.query(ProductSignal).all()}
    assert kinds == {"demand"}


def test_what_was_withheld_is_written_in_the_audit_trail(db_session: Session):
    """Un dato que desaparece sin dejar rastro es peor que un dato que falta."""
    run(db_session, agent_for("wikimedia-pageviews", UNREAD), correlation_id="cid-w")

    entry = db_session.query(AuditLog).filter_by(correlation_id="cid-w").one()
    assert entry.after["signals_withheld_by_provider"] == {UNREAD: 1}


def test_nothing_withheld_is_the_normal_case(db_session: Session):
    run(db_session, agent_for("wikimedia-pageviews", "wikimedia-pageviews"), correlation_id="cid-n")

    entry = db_session.query(AuditLog).filter_by(correlation_id="cid-n").one()
    assert entry.after["signals_withheld_by_provider"] == {}


def test_the_product_still_exists_even_if_every_signal_was_withheld(db_session: Session):
    """El candidato se encontró: eso es verdad aunque no se pueda guardar lo que
    se midió de él."""
    products = run(db_session, agent_for(UNREAD, UNREAD))

    assert len(products) == 1
    assert db_session.query(ProductSignal).count() == 0
