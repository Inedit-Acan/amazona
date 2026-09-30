import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.budgets.service import BudgetLedgerService
from app.core.errors import ValidationError
from app.db.base import Base
from app.db.models.audit import AuditLog
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


def authorised(db: Session, hard_limit: float = 1000.0, soft_limit: float | None = None) -> BudgetLedgerService:
    """Un libro con presupuesto, que solo existe porque alguien lo autorizó."""
    ledger = BudgetLedgerService(db)
    ledger.authorise_budget(hard_limit=hard_limit, soft_limit=soft_limit, actor="owner@amazona.local")
    return ledger


# --- El presupuesto no se crea solo -------------------------------------------------


def test_reading_the_ledger_never_creates_a_budget(db_session: Session):
    ledger = BudgetLedgerService(db_session)

    assert ledger.find_budget() is None
    assert ledger.snapshot() is None
    ledger.assess(100.0, simulated=False)
    db_session.commit()

    assert db_session.query(Budget).count() == 0
    assert db_session.query(BudgetAllocation).count() == 0


def test_without_a_budget_nothing_is_reserved_and_nothing_is_moved(db_session: Session):
    ledger = BudgetLedgerService(db_session)

    assert ledger.reserve(amount=100.0, reference="approval:1") is False
    assert ledger.record_commit(amount=100.0, reference="approval:1") is False
    assert ledger.record_release(amount=100.0, reference="approval:1") is False

    assert db_session.query(Budget).count() == 0
    assert db_session.query(FinancialEvent).count() == 0


def test_authorising_a_budget_creates_it_with_its_allocation_and_audits_it(db_session: Session):
    ledger = BudgetLedgerService(db_session)

    budget = ledger.authorise_budget(hard_limit=1000.0, soft_limit=800.0, actor="cli:owner")

    assert (budget.hard_limit, budget.soft_limit) == (1000.0, 800.0)
    allocation = db_session.query(BudgetAllocation).one()
    assert (allocation.reserved, allocation.committed, allocation.spent) == (0, 0, 0)
    entry = db_session.query(AuditLog).filter_by(action="budget.authorise").one()
    assert entry.actor == "cli:owner"
    assert entry.before is None
    assert entry.after == {"hard_limit": 1000.0, "soft_limit": 800.0}


def test_changing_the_budget_keeps_one_row_and_audits_before_and_after(db_session: Session):
    ledger = authorised(db_session, 1000.0)

    ledger.authorise_budget(hard_limit=2500.0, actor="cli:owner")

    assert db_session.query(Budget).count() == 1
    assert db_session.query(BudgetAllocation).count() == 1
    entry = db_session.query(AuditLog).filter_by(action="budget.authorise").order_by(AuditLog.created_at).all()[-1]
    assert entry.before == {"hard_limit": 1000.0, "soft_limit": None}
    assert entry.after == {"hard_limit": 2500.0, "soft_limit": None}


@pytest.mark.parametrize("hard, soft", [(0.0, None), (-5.0, None), (100.0, 0.0), (100.0, 150.0)])
def test_an_invalid_budget_is_refused_and_nothing_is_written(db_session: Session, hard, soft):
    with pytest.raises(ValidationError):
        BudgetLedgerService(db_session).authorise_budget(hard_limit=hard, soft_limit=soft, actor="cli:owner")

    assert db_session.query(Budget).count() == 0
    assert db_session.query(AuditLog).count() == 0


# --- Reservar, comprometer y liberar ------------------------------------------------


def test_reserve_moves_the_amount_into_reserved_and_leaves_a_trail(db_session: Session):
    ledger = authorised(db_session)

    assert ledger.reserve(amount=150.0, reference="approval:1") is True
    db_session.commit()

    allocation = db_session.query(BudgetAllocation).one()
    assert allocation.reserved == 150.0
    assert allocation.committed == 0.0
    assert allocation.spent == 0.0
    event = db_session.query(FinancialEvent).one()
    assert (event.type, event.amount, event.reference) == ("RESERVE", 150.0, "approval:1")


def test_reserving_twice_reuses_the_same_budget_and_allocation(db_session: Session):
    ledger = authorised(db_session)

    ledger.reserve(amount=100.0, reference="approval:1")
    ledger.reserve(amount=50.0, reference="approval:2")
    db_session.commit()

    assert db_session.query(Budget).count() == 1
    assert db_session.query(BudgetAllocation).one().reserved == 150.0
    assert db_session.query(FinancialEvent).count() == 2


def test_a_reservation_that_does_not_fit_is_refused_and_reserves_nothing(db_session: Session):
    ledger = authorised(db_session, 100.0)
    ledger.reserve(amount=60.0, reference="approval:1")

    assert ledger.reserve(amount=60.0, reference="approval:2") is False

    assert db_session.query(BudgetAllocation).one().reserved == 60.0
    assert db_session.query(FinancialEvent).count() == 1


def test_a_reservation_of_exactly_what_is_left_fits(db_session: Session):
    ledger = authorised(db_session, 100.0)
    ledger.reserve(amount=60.0, reference="approval:1")

    assert ledger.reserve(amount=40.0, reference="approval:2") is True
    assert ledger.reserve(amount=0.01, reference="approval:3") is False


def test_what_is_committed_also_counts_against_the_limit(db_session: Session):
    ledger = authorised(db_session, 100.0)
    ledger.reserve(amount=70.0, reference="approval:1")
    ledger.record_commit(amount=70.0, reference="approval:1")

    assert ledger.reserve(amount=40.0, reference="approval:2") is False
    assert ledger.reserve(amount=30.0, reference="approval:2") is True


def test_an_idempotent_reservation_is_not_repeated(db_session: Session):
    ledger = authorised(db_session, 100.0)

    assert ledger.reserve(amount=60.0, reference="step:1", idempotent=True) is True
    assert ledger.reserve(amount=60.0, reference="step:1", idempotent=True) is True  # ya estaba viva

    assert db_session.query(BudgetAllocation).one().reserved == 60.0
    assert db_session.query(FinancialEvent).count() == 1
    assert ledger.outstanding("step:1") == 60


def test_once_committed_an_idempotent_reference_can_reserve_again(db_session: Session):
    ledger = authorised(db_session, 100.0)
    ledger.reserve(amount=30.0, reference="step:1", idempotent=True)
    ledger.record_commit(amount=30.0, reference="step:1")

    assert ledger.outstanding("step:1") == 0
    assert ledger.reserve(amount=30.0, reference="step:1", idempotent=True) is True
    assert db_session.query(BudgetAllocation).one().reserved == 30.0


def test_record_commit_moves_reserved_into_committed_and_spent(db_session: Session):
    ledger = authorised(db_session)
    ledger.reserve(amount=150.0, reference="approval:1")

    assert ledger.record_commit(amount=150.0, reference="approval:1") is True
    db_session.commit()

    allocation = db_session.query(BudgetAllocation).one()
    assert allocation.reserved == 0.0
    assert allocation.committed == 150.0
    assert allocation.spent == 150.0
    events = {e.type for e in db_session.query(FinancialEvent).all()}
    assert events == {"RESERVE", "COMMIT"}


def test_record_release_reduces_reserved_without_touching_committed_or_spent(db_session: Session):
    ledger = authorised(db_session)
    ledger.reserve(amount=150.0, reference="approval:1")

    ledger.record_release(amount=150.0, reference="approval:1")
    db_session.commit()

    allocation = db_session.query(BudgetAllocation).one()
    assert allocation.reserved == 0.0
    assert allocation.committed == 0.0
    assert allocation.spent == 0.0


def test_release_never_drives_reserved_negative(db_session: Session):
    ledger = authorised(db_session)
    ledger.reserve(amount=50.0, reference="approval:1")

    ledger.record_release(amount=999.0, reference="approval:1")
    db_session.commit()

    allocation = db_session.query(BudgetAllocation).one()
    assert allocation.reserved == 0.0
