import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.db.models.audit import AuditLog
from app.db.models.product import Product
from app.db.models.product_analysis import ProductAnalysis
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
