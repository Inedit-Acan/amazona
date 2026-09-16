import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.budgets.service import BudgetLedgerService
from app.db.base import Base
from app.db.models.budget import Budget, BudgetAllocation, FinancialEvent


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


def test_record_reserve_creates_budget_and_allocation(db_session: Session):
    ledger = BudgetLedgerService(db_session, hard_limit=1000.0)

    ledger.record_reserve(amount=150.0, reference="approval:1")
    db_session.commit()

    budget = db_session.query(Budget).one()
    assert budget.hard_limit == 1000.0
    allocation = db_session.query(BudgetAllocation).filter_by(budget_id=budget.id).one()
    assert allocation.reserved == 150.0
    assert allocation.committed == 0.0
    assert allocation.spent == 0.0
    event = db_session.query(FinancialEvent).one()
    assert event.type == "RESERVE"
    assert event.amount == 150.0
    assert event.reference == "approval:1"


def test_get_or_create_reuses_the_same_budget_and_allocation(db_session: Session):
    ledger = BudgetLedgerService(db_session, hard_limit=1000.0)

    ledger.record_reserve(amount=100.0, reference="approval:1")
    ledger.record_reserve(amount=50.0, reference="approval:2")
    db_session.commit()

    assert db_session.query(Budget).count() == 1
    allocation = db_session.query(BudgetAllocation).one()
    assert allocation.reserved == 150.0
    assert db_session.query(FinancialEvent).count() == 2


def test_record_commit_moves_reserved_into_committed_and_spent(db_session: Session):
    ledger = BudgetLedgerService(db_session, hard_limit=1000.0)
    ledger.record_reserve(amount=150.0, reference="approval:1")

    ledger.record_commit(amount=150.0, reference="approval:1")
    db_session.commit()

    allocation = db_session.query(BudgetAllocation).one()
    assert allocation.reserved == 0.0
    assert allocation.committed == 150.0
    assert allocation.spent == 150.0
    events = {e.type for e in db_session.query(FinancialEvent).all()}
    assert events == {"RESERVE", "COMMIT"}


def test_record_release_reduces_reserved_without_touching_committed_or_spent(db_session: Session):
    ledger = BudgetLedgerService(db_session, hard_limit=1000.0)
    ledger.record_reserve(amount=150.0, reference="approval:1")

    ledger.record_release(amount=150.0, reference="approval:1")
    db_session.commit()

    allocation = db_session.query(BudgetAllocation).one()
    assert allocation.reserved == 0.0
    assert allocation.committed == 0.0
    assert allocation.spent == 0.0


def test_release_never_drives_reserved_negative(db_session: Session):
    ledger = BudgetLedgerService(db_session, hard_limit=1000.0)
    ledger.record_reserve(amount=50.0, reference="approval:1")

    ledger.record_release(amount=999.0, reference="approval:1")
    db_session.commit()

    allocation = db_session.query(BudgetAllocation).one()
    assert allocation.reserved == 0.0
