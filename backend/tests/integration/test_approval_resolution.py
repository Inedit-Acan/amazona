"""Resolver una aprobación es atómico y el libro no pierde importes (hardening pre-M44, D10).

Antes, `approve`/`reject` leían el estado, comprobaban en Python que seguía `PENDING` y
escribían después, y `record_commit` leía el saldo, sumaba en Python y escribía el
resultado. Con peticiones simultáneas, todas veían `PENDING` y todas registraban su
`COMMIT`; y un `approve` con un `reject` dejaban `COMMIT` y `RELEASE` de la misma
aprobación. Medido sobre PostgreSQL: 8 `approve` simultáneos producían 8 `COMMIT`.

Aquí, lo secuencial, en SQLite: quién gana, qué recibe quien pierde, y que la
aritmética del libro es relativa. La carrera de verdad está en
`test_approval_resolution_concurrency.py`, que necesita PostgreSQL.
"""

import datetime

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.api import approvals as api
from app.approvals.service import ApprovalNotPendingError
from app.auth.actor import Actor, ActorSource, RoleName
from app.budgets.service import BudgetLedgerService
from app.core.config import Settings
from app.db.base import Base
from app.db.models.approval import Approval
from app.db.models.audit import AuditLog
from app.db.models.budget import BudgetAllocation, FinancialEvent
from app.db.models.decision import Decision
from app.db.models.objective import Objective
from app.db.models.project import Project

IDENTITY = Actor(subject="owner@amazona.local", role=RoleName.OWNER, source=ActorSource.DECLARED)
SETTINGS = Settings(_env_file=None)


@pytest.fixture()
def engine():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture()
def db(engine):
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def pending_approval(db: Session, *, amount: float = 100.0, expired: bool = False) -> Approval:
    """Una aprobación pendiente con su reserva en el libro, como la deja el orquestador."""
    objective = Objective(title="t", created_by="t@t", context={})
    db.add(objective)
    db.flush()
    project = Project(objective_id=objective.id, name="p")
    db.add(project)
    db.flush()
    decision = Decision(project_id=project.id, status="HUMAN_APPROVAL", correlation_id="c-1")
    db.add(decision)
    db.flush()
    delta = datetime.timedelta(hours=-1 if expired else 24)
    approval = Approval(
        decision_id=decision.id,
        action="launch_marketing_campaign",
        amount=amount,
        status="PENDING",
        expires_at=datetime.datetime.now(datetime.UTC) + delta,
        correlation_id="c-1",
    )
    db.add(approval)
    db.flush()
    ledger = BudgetLedgerService(db)
    if ledger.find_budget() is None:
        ledger.authorise_budget(hard_limit=1_000_000.0, actor="owner@amazona.local")
    assert ledger.reserve(amount=amount, reference=f"approval:{approval.id}")
    db.commit()
    return approval


def events(db: Session, approval: Approval) -> list[str]:
    rows = db.query(FinancialEvent).filter_by(reference=f"approval:{approval.id}").order_by(FinancialEvent.type).all()
    return [row.type for row in rows]


def allocation(db: Session) -> BudgetAllocation:
    db.expire_all()
    return db.query(BudgetAllocation).one()


# --- Un solo ganador ----------------------------------------------------------------


def test_the_claim_changes_the_row_for_one_caller_only(db: Session):
    approval = pending_approval(db)
    now = datetime.datetime.now(datetime.UTC)

    first = api._claim(db, approval.id, to_status="APPROVED", now=now, resolved_by="a")
    second = api._claim(db, approval.id, to_status="REJECTED", now=now, resolved_by="b")
    db.commit()
    db.refresh(approval)

    assert (first, second) == (True, False)
    assert (approval.status, approval.resolved_by) == ("APPROVED", "a")


def test_approving_twice_commits_once_and_the_second_gets_already_resolved(db: Session):
    approval = pending_approval(db)
    api._resolve(approval.id, "APPROVED", db, IDENTITY, None, SETTINGS)

    with pytest.raises(ApprovalNotPendingError, match="status=APPROVED"):
        api._resolve(approval.id, "APPROVED", db, IDENTITY, None, SETTINGS)

    assert events(db, approval) == ["COMMIT", "RESERVE"]
    assert (allocation(db).reserved, allocation(db).committed) == (0, 100)
    assert db.query(AuditLog).filter_by(action="approval.approve").count() == 1


def test_rejecting_after_approving_is_refused_and_does_not_release(db: Session):
    approval = pending_approval(db)
    api._resolve(approval.id, "APPROVED", db, IDENTITY, None, SETTINGS)

    with pytest.raises(ApprovalNotPendingError):
        api._resolve(approval.id, "REJECTED", db, IDENTITY, None, SETTINGS)

    assert events(db, approval) == ["COMMIT", "RESERVE"]
    assert db.query(AuditLog).filter_by(action="approval.reject").count() == 0


def test_approving_after_rejecting_is_refused_and_does_not_commit(db: Session):
    approval = pending_approval(db)
    api._resolve(approval.id, "REJECTED", db, IDENTITY, None, SETTINGS)

    with pytest.raises(ApprovalNotPendingError):
        api._resolve(approval.id, "APPROVED", db, IDENTITY, None, SETTINGS)

    assert events(db, approval) == ["RELEASE", "RESERVE"]
    assert (allocation(db).reserved, allocation(db).committed) == (0, 0)


# --- La rama de caducidad ------------------------------------------------------------


def test_an_expired_approval_is_released_exactly_once(db: Session):
    approval = pending_approval(db, expired=True)

    for _ in range(3):
        with pytest.raises(ApprovalNotPendingError, match="status=EXPIRED"):
            api._resolve(approval.id, "APPROVED", db, IDENTITY, None, SETTINGS)

    assert events(db, approval) == ["RELEASE", "RESERVE"]
    assert allocation(db).reserved == 0
    assert db.query(AuditLog).filter_by(action="approval.expire").count() == 1


def test_an_unknown_approval_is_still_not_found(db: Session):
    from app.core.errors import NotFoundError

    with pytest.raises(NotFoundError):
        api._resolve("missing", "APPROVED", db, IDENTITY, None, SETTINGS)


# --- El libro mueve saldos con aritmética de la base --------------------------------


def test_the_ledger_writes_relative_arithmetic_never_a_total_computed_in_python(engine, db: Session):
    approval = pending_approval(db)
    statements: list[str] = []

    @event.listens_for(engine, "before_cursor_execute")
    def capture(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("UPDATE BUDGET_ALLOCATIONS"):
            statements.append(" ".join(statement.split()))

    BudgetLedgerService(db).record_commit(amount=30.0, reference=f"approval:{approval.id}")
    db.commit()

    assert len(statements) == 1
    assert "committed=(budget_allocations.committed +" in statements[0].replace(" = ", "=")
    assert "spent=(budget_allocations.spent +" in statements[0].replace(" = ", "=")


def test_the_ledger_arithmetic_is_unchanged(db: Session):
    ledger = BudgetLedgerService(db)
    ledger.authorise_budget(hard_limit=1000.0, actor="owner@amazona.local")
    ledger.reserve(amount=150.0, reference="a:1")
    ledger.reserve(amount=50.0, reference="a:2")
    ledger.record_commit(amount=150.0, reference="a:1")
    ledger.record_release(amount=500.0, reference="a:2")  # más de lo reservado: nunca negativo
    db.commit()

    row = allocation(db)
    assert (row.reserved, row.committed, row.spent) == (0, 150, 150)
    assert db.query(FinancialEvent).count() == 4
