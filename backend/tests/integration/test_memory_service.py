import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.db.models.audit import AuditLog
from app.memory.service import MemoryService


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


@pytest.fixture()
def memory(db_session: Session) -> MemoryService:
    return MemoryService(db_session)


def test_recall_of_an_unknown_key_returns_none(memory: MemoryService):
    result = memory.recall(scope="product", scope_id="prod-1", key="supplier_check")

    assert result is None


def test_remember_then_recall_returns_the_same_value(memory: MemoryService):
    memory.remember(
        scope="product", scope_id="prod-1", key="supplier_check",
        value={"verified": True}, correlation_id="corr-1",
    )

    record = memory.recall(scope="product", scope_id="prod-1", key="supplier_check")

    assert record is not None
    assert record.value == {"verified": True}


def test_remember_with_same_key_updates_instead_of_duplicating(memory: MemoryService, db_session: Session):
    memory.remember(
        scope="product", scope_id="prod-1", key="supplier_check",
        value={"verified": False}, correlation_id="corr-1",
    )
    memory.remember(
        scope="product", scope_id="prod-1", key="supplier_check",
        value={"verified": True}, correlation_id="corr-2",
    )

    all_records = memory.recall_all(scope="product", scope_id="prod-1")
    assert len(all_records) == 1
    assert all_records[0].value == {"verified": True}


def test_remember_scopes_are_isolated_from_each_other(memory: MemoryService):
    memory.remember(scope="product", scope_id="prod-1", key="k", value={"a": 1}, correlation_id="corr-1")
    memory.remember(scope="product", scope_id="prod-2", key="k", value={"a": 2}, correlation_id="corr-1")

    assert memory.recall(scope="product", scope_id="prod-1", key="k").value == {"a": 1}
    assert memory.recall(scope="product", scope_id="prod-2", key="k").value == {"a": 2}


def test_every_remember_call_is_audited(memory: MemoryService, db_session: Session):
    memory.remember(
        scope="product", scope_id="prod-1", key="supplier_check",
        value={"verified": True}, correlation_id="corr-1",
    )

    entries = db_session.query(AuditLog).filter_by(correlation_id="corr-1").all()
    assert len(entries) == 1
    assert entries[0].action == "memory.remember"
    assert entries[0].after == {"verified": True}
