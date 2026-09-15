import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.ids import new_id
from app.db.base import Base
from app.db.models.objective import Objective


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


def test_objective_can_be_persisted_within_a_transaction(db_session: Session):
    objective_id = new_id()

    with db_session.begin():
        db_session.add(
            Objective(
                id=objective_id,
                title="Validate wireless earbuds opportunity",
                description="Assess a candidate product for Amazon FBA launch.",
                created_by="owner@amazona.local",
            )
        )

    persisted = db_session.get(Objective, objective_id)

    assert persisted is not None
    assert persisted.title == "Validate wireless earbuds opportunity"
    assert persisted.created_by == "owner@amazona.local"
    assert isinstance(persisted.created_at, datetime.datetime)


def test_objective_insert_is_rolled_back_on_transaction_failure(db_session: Session):
    objective_id = new_id()

    try:
        with db_session.begin():
            db_session.add(Objective(id=objective_id, title="Temp", created_by="owner@amazona.local"))
            raise RuntimeError("simulated failure before commit")
    except RuntimeError:
        pass

    assert db_session.get(Objective, objective_id) is None
