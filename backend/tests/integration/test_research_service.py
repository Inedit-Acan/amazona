import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.agents.product_research import ProductResearchAgent
from app.db.base import Base
from app.db.models.audit import AuditLog
from app.db.models.product import Product
from app.db.models.product_analysis import ProductAnalysis
from app.db.models.product_identity_alias import ProductIdentityAlias
from app.integrations.ports import CandidateSignals, ProductSignalProvider, Signal, SignalBasis, SignalKind
from app.integrations.product_intelligence.identity import ALIAS, NORMALISED, resolve
from app.research.service import ResearchService


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


class _OneNamed(ProductSignalProvider):
    """Una fuente que solo sabe de un producto, para poder elegir con qué nombre
    llega un candidato (Milestone 36)."""

    name = "wikimedia-pageviews"

    def __init__(self, candidate_name: str) -> None:
        self._name = candidate_name

    def supports(self) -> frozenset[SignalKind]:
        return frozenset({SignalKind.DEMAND})

    def discover(self, *, category, keywords, market, max_results, channels=None):
        return [
            CandidateSignals(
                name=self._name,
                category=category,
                signals=[
                    Signal(
                        kind=SignalKind.DEMAND,
                        value=0.62,
                        confidence=0.55,
                        provider="wikimedia-pageviews",
                        source="wikimedia.org/api/rest_v1/metrics/pageviews",
                        query=self._name,
                        market=market,
                        observed_at=datetime.datetime(2026, 9, 1, tzinfo=datetime.UTC),
                        method="monthly pageviews… PROXY FOR INTEREST — not purchase demand",
                        basis=SignalBasis.MEASURED,
                    )
                ],
            )
        ]


def _agent_for(candidate_name: str) -> ProductResearchAgent:
    return ProductResearchAgent(trends_provider=_OneNamed(candidate_name))


def test_run_research_persists_a_product_and_analysis_per_candidate(db_session: Session):
    service = ResearchService(db_session)

    products = service.run_research(
        category="electronics", keywords=None, max_results=3, correlation_id="corr-1"
    )

    assert 1 <= len(products) <= 3
    persisted_products = db_session.query(Product).all()
    assert len(persisted_products) == len(products)
    assert all(p.status == "CANDIDATE" for p in persisted_products)
    assert all(p.source == "research" for p in persisted_products)

    analyses = db_session.query(ProductAnalysis).filter_by(correlation_id="corr-1").all()
    assert len(analyses) == len(products)
    assert all(a.analysis_type == "research" for a in analyses)
    assert all(a.opportunity_score is not None for a in analyses)


def test_run_research_audits_the_run(db_session: Session):
    service = ResearchService(db_session)

    service.run_research(category="home", keywords=None, max_results=5, correlation_id="corr-2")

    entries = db_session.query(AuditLog).filter_by(correlation_id="corr-2").all()
    assert any(e.action == "research.run" for e in entries)


def test_run_research_with_unknown_category_persists_nothing(db_session: Session):
    service = ResearchService(db_session)

    products = service.run_research(
        category="does-not-exist", keywords=None, max_results=5, correlation_id="corr-3"
    )

    assert products == []
    assert db_session.query(Product).count() == 0


# --- Identidad de los candidatos (Milestone 36, ADR 0014) ------------------


def test_two_runs_do_not_duplicate_the_same_product(db_session: Session):
    """Antes, dos investigaciones sobre `home` dejaban dos «Silicone kitchen
    organizer» sin relación entre sí, y la serie mensual que el Milestone 35
    empezó a guardar quedaba repartida entre ellas."""
    service = ResearchService(db_session)

    first = service.run_research(
        category="home", keywords=None, max_results=5, correlation_id="corr-a"
    )
    second = service.run_research(
        category="home", keywords=None, max_results=5, correlation_id="corr-b"
    )

    assert [p.id for p in first] == [p.id for p in second]
    assert db_session.query(Product).count() == len(first)


def test_each_run_still_leaves_its_own_analysis(db_session: Session):
    """Reutilizar el producto no borra la historia por ejecución."""
    service = ResearchService(db_session)

    service.run_research(category="home", keywords=None, max_results=5, correlation_id="corr-a")
    service.run_research(category="home", keywords=None, max_results=5, correlation_id="corr-b")

    first = db_session.query(ProductAnalysis).filter_by(correlation_id="corr-a").count()
    second = db_session.query(ProductAnalysis).filter_by(correlation_id="corr-b").count()
    assert first == second > 0


def test_every_product_carries_its_identity(db_session: Session):
    service = ResearchService(db_session)

    service.run_research(category="home", keywords=None, max_results=5, correlation_id="corr-a")

    for product in db_session.query(Product).all():
        assert product.identity_key == resolve(product.name).key


def test_a_product_that_arrives_with_another_name_records_why(db_session: Session):
    """«¿Por qué estos dos son uno?» tiene que poder contestarse desde la base de
    datos meses después."""
    db_session.add(
        Product(
            name="air fryer",
            identity_key=resolve("air fryer").key,
            category="home",
            status="CANDIDATE",
            created_by="owner@amazona.local",
            source="manual",
        )
    )
    db_session.commit()

    ResearchService(db_session, agent=_agent_for("Air fryer")).run_research(
        category="home", keywords=None, max_results=1, correlation_id="corr-c"
    )

    assert db_session.query(Product).count() == 1
    alias = db_session.query(ProductIdentityAlias).one()
    assert alias.alias == "Air fryer"
    assert alias.identity_key == "air fryer"
    assert alias.method == NORMALISED
    assert alias.correlation_id == "corr-c"


def test_a_declared_alias_says_it_came_from_the_catalogue(db_session: Session):
    db_session.add(
        Product(
            name="Air fryer",
            identity_key=resolve("Air fryer").key,
            category="home",
            status="CANDIDATE",
            created_by="owner@amazona.local",
            source="manual",
        )
    )
    db_session.commit()

    ResearchService(db_session, agent=_agent_for("airfryer")).run_research(
        category="home", keywords=None, max_results=1, correlation_id="corr-d"
    )

    assert db_session.query(Product).count() == 1
    alias = db_session.query(ProductIdentityAlias).one()
    assert alias.alias == "airfryer"
    assert alias.method == ALIAS


def test_the_same_term_under_another_category_is_another_product(db_session: Session):
    """Límite conocido y escrito: la categoría viene de la petición, no de la
    fuente, y unir dos categorías reescribiría en silencio la primera."""
    ResearchService(db_session, agent=_agent_for("Air fryer")).run_research(
        category="home", keywords=None, max_results=1, correlation_id="corr-e"
    )
    ResearchService(db_session, agent=_agent_for("Air fryer")).run_research(
        category="kitchen", keywords=None, max_results=1, correlation_id="corr-f"
    )

    assert db_session.query(Product).count() == 2


def test_the_audit_says_how_much_was_already_known(db_session: Session):
    service = ResearchService(db_session)

    service.run_research(category="home", keywords=None, max_results=5, correlation_id="corr-a")
    service.run_research(category="home", keywords=None, max_results=5, correlation_id="corr-b")

    first = db_session.query(AuditLog).filter_by(correlation_id="corr-a").one()
    second = db_session.query(AuditLog).filter_by(correlation_id="corr-b").one()
    assert first.after["reused_products"] == 0
    assert second.after["reused_products"] == second.after["candidate_count"] > 0


def test_the_word_the_caller_used_is_not_lost(db_session: Session):
    """El catálogo canonicaliza antes de preguntar, así que `AIRFRYER` nunca
    llega a la fuente. Quien escribió esa palabra tiene que poder encontrarla."""
    service = ResearchService(db_session, agent=_agent_for("Air fryer"))

    service.run_research(
        category="home", keywords=["AIRFRYER"], max_results=1, correlation_id="corr-g"
    )

    alias = db_session.query(ProductIdentityAlias).one()
    assert alias.alias == "AIRFRYER"
    assert alias.identity_key == "air fryer"
    assert alias.method == ALIAS


def test_the_same_question_is_not_recorded_twice(db_session: Session):
    service = ResearchService(db_session, agent=_agent_for("Air fryer"))

    service.run_research(
        category="home", keywords=["AIRFRYER"], max_results=1, correlation_id="corr-h"
    )
    service.run_research(
        category="home", keywords=["AIRFRYER"], max_results=1, correlation_id="corr-i"
    )

    assert db_session.query(ProductIdentityAlias).count() == 1


def test_a_keyword_that_found_nothing_records_nothing(db_session: Session):
    """No se anota una fusión que no ocurrió."""
    service = ResearchService(db_session, agent=_agent_for("Air fryer"))

    service.run_research(
        category="home", keywords=["Sous vide cooker"], max_results=1, correlation_id="corr-j"
    )

    assert db_session.query(ProductIdentityAlias).count() == 0
