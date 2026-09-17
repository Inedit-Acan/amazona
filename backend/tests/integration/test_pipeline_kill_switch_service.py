import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.db.models.audit import AuditLog
from app.pipeline.kill_switch import PipelineKillSwitchService


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


def test_is_enabled_by_default_with_no_prior_row(db_session: Session):
    service = PipelineKillSwitchService(db_session)

    assert service.is_enabled() is True


def test_disable_persists_and_audits(db_session: Session):
    service = PipelineKillSwitchService(db_session)

    switch = service.disable(reason="investigating a data issue", actor="ops@amazona.local", correlation_id="corr-1")

    assert switch.enabled is False
    assert switch.reason == "investigating a data issue"
    assert service.is_enabled() is False
    entries = db_session.query(AuditLog).filter_by(correlation_id="corr-1").all()
    assert any(e.action == "pipeline_kill_switch.disable" for e in entries)


def test_enable_reverts_a_prior_disable(db_session: Session):
    service = PipelineKillSwitchService(db_session)
    service.disable(reason="paused", actor="ops@amazona.local", correlation_id="corr-1")

    switch = service.enable(actor="ops@amazona.local", correlation_id="corr-2")

    assert switch.enabled is True
    assert switch.reason is None
    assert service.is_enabled() is True


def test_get_or_create_reuses_the_same_row(db_session: Session):
    service = PipelineKillSwitchService(db_session)
    service.disable(reason="paused", actor="ops@amazona.local", correlation_id="corr-1")

    same_service = PipelineKillSwitchService(db_session)

    assert same_service.is_enabled() is False
