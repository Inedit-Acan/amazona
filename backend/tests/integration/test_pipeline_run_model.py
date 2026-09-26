import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.db.models.pipeline_run import PipelineRun
from app.db.models.pipeline_step import PipelineStep, PipelineStepAttempt
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
        correlation_id="corr-1",
        request={"category": "home", "sale_price": 50.0, "destination_region": "mexico"},
    )
    db_session.add(run)
    db_session.commit()

    persisted = db_session.get(PipelineRun, run.id)
    assert persisted is not None
    assert persisted.product_id == product.id
    assert persisted.status == "COMPLETED"
    # Los parámetros de negocio se guardan: sin ellos no se puede reanudar
    # (Milestone 32).
    assert persisted.request["sale_price"] == 50.0


def test_persists_with_a_null_product_id_for_a_partial_run(db_session: Session):
    run = PipelineRun(
        product_id=None,
        category="home",
        market="us",
        status="PARTIAL",
        failed_step="research",
        correlation_id="corr-2",
    )
    db_session.add(run)
    db_session.commit()

    persisted = db_session.get(PipelineRun, run.id)
    assert persisted is not None
    assert persisted.product_id is None
    assert persisted.failed_step == "research"


def test_the_steps_of_a_run_are_rows_not_a_json_blob(db_session: Session):
    """Milestone 32 (ADR 0010): `pipeline_runs.steps` ya no existe. Cada paso es
    una fila, que es lo que permite escribirlo cuando ocurre en vez de al final."""
    assert "steps" not in PipelineRun.__table__.columns

    run = PipelineRun(category="home", market="us", status="QUEUED", correlation_id="corr-3")
    db_session.add(run)
    db_session.flush()
    db_session.add(
        PipelineStep(
            pipeline_run_id=run.id,
            name="research",
            ordinal=0,
            status="COMPLETED",
            correlation_id="c1",
            entity_id="prod-1",
            detail={"candidate_count": 3},
            attempt=1,
        )
    )
    db_session.commit()

    step = db_session.query(PipelineStep).filter_by(pipeline_run_id=run.id).one()
    assert step.detail == {"candidate_count": 3}
    assert step.entity_id == "prod-1"


def test_a_step_cannot_be_duplicated_within_a_run(db_session: Session):
    run = PipelineRun(category="home", market="us", status="QUEUED", correlation_id="corr-4")
    db_session.add(run)
    db_session.flush()
    for _ in range(2):
        db_session.add(
            PipelineStep(pipeline_run_id=run.id, name="research", ordinal=0, status="PENDING", attempt=0)
        )

    with pytest.raises(IntegrityError):
        db_session.commit()


def test_a_step_keeps_every_attempt_it_took(db_session: Session):
    run = PipelineRun(category="home", market="us", status="QUEUED", correlation_id="corr-5")
    db_session.add(run)
    db_session.flush()
    step = PipelineStep(pipeline_run_id=run.id, name="economics", ordinal=2, status="COMPLETED", attempt=2)
    db_session.add(step)
    db_session.flush()
    db_session.add_all(
        [
            PipelineStepAttempt(
                pipeline_step_id=step.id, number=1, status="FAILED", error="provider is down"
            ),
            PipelineStepAttempt(pipeline_step_id=step.id, number=2, status="COMPLETED"),
        ]
    )
    db_session.commit()

    attempts = (
        db_session.query(PipelineStepAttempt)
        .filter_by(pipeline_step_id=step.id)
        .order_by(PipelineStepAttempt.number)
        .all()
    )
    assert [attempt.status for attempt in attempts] == ["FAILED", "COMPLETED"]
    assert attempts[0].error == "provider is down"
