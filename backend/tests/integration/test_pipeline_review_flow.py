import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.db.models.pipeline_review import PipelineReview
from app.pipeline.service import PipelineOrchestrator, PipelineRequest


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


def test_a_healthy_run_does_not_create_a_review(db_session: Session):
    orchestrator = PipelineOrchestrator(db_session)
    request = PipelineRequest(category="home", sale_price=50.0, destination_region="mexico")

    run = orchestrator.run_pipeline(request)

    assert run.needs_review is False
    assert db_session.query(PipelineReview).count() == 0


def test_a_no_go_economics_run_creates_a_pending_review(db_session: Session):
    orchestrator = PipelineOrchestrator(db_session)
    request = PipelineRequest(category="home", sale_price=0.5, destination_region="mexico")

    run = orchestrator.run_pipeline(request)

    assert run.needs_review is True
    review = db_session.query(PipelineReview).filter_by(pipeline_run_id=run.id).one()
    assert review.status == "PENDING"
    assert any("economics" in reason for reason in review.reasons)
    assert review.correlation_id == run.correlation_id


def test_a_partial_run_creates_a_pending_review(db_session: Session):
    orchestrator = PipelineOrchestrator(db_session)
    request = PipelineRequest(category="does-not-exist", sale_price=50.0, destination_region="mexico")

    run = orchestrator.run_pipeline(request)

    assert run.status == "PARTIAL"
    assert run.needs_review is True
    review = db_session.query(PipelineReview).filter_by(pipeline_run_id=run.id).one()
    assert any("PARTIAL" in reason for reason in review.reasons)
