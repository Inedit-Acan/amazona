import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.db.models.pipeline_run import PipelineRun
from app.db.models.product import Product


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


def test_persists_with_a_real_product_id(db_session: Session):
    product = Product(name="Widget", category="home", created_by="owner@amazona.local")
    db_session.add(product)
    db_session.commit()

    run = PipelineRun(
        product_id=product.id,
        category="home",
        market="us",
        status="COMPLETED",
        steps={"research": {"correlation_id": "c1"}},
        correlation_id="corr-1",
    )
    db_session.add(run)
    db_session.commit()

    persisted = db_session.get(PipelineRun, run.id)
    assert persisted is not None
    assert persisted.product_id == product.id
    assert persisted.status == "COMPLETED"


def test_persists_with_a_null_product_id_for_a_partial_run(db_session: Session):
    run = PipelineRun(
        product_id=None,
        category="home",
        market="us",
        status="PARTIAL",
        failed_step="research",
        steps={},
        correlation_id="corr-2",
    )
    db_session.add(run)
    db_session.commit()

    persisted = db_session.get(PipelineRun, run.id)
    assert persisted is not None
    assert persisted.product_id is None
    assert persisted.failed_step == "research"
