"""Verifies two concurrent run_objective() calls on distinct objectives
don't interfere with each other.

Each call gets its own TaskService instance (an orchestrator-local, in
memory DAG — see app/tasks/service.py) and, here, its own SQLAlchemy
Session bound to its own real connection to a shared file-based SQLite
DB, so both threads see the same database. That isolation (own
TaskService + own connection per call) is what this test exists to prove
is actually race-free, not just architecturally plausible.

Deliberately *not* an in-memory DB behind StaticPool: StaticPool hands
every Session the exact same underlying sqlite3 connection object, and
concurrently executing statements through one shared connection object
from two threads is itself unsafe (observed as sqlite3.InterfaceError /
StaleDataError under real thread scheduling, e.g. in CI) — that would be
testing StaticPool's single-connection hazard, not the orchestrator's
own isolation. A real file gives each thread its own connection, same as
two real Postgres clients would have.
"""

import tempfile
import threading
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.ceo.orchestrator import CEOOrchestrator
from app.ceo.schemas import DecisionStatus
from app.core.ids import new_id
from app.db.base import Base
from app.db.models.objective import Objective
from app.db.models.project import Project
from app.db.models.task import Task

ATTRACTIVE_CONTEXT = {
    "product_validation": {"estimated_monthly_searches": 12000, "competition_level": "low"},
    "supplier_sourcing": {"unit_cost": 5.0, "lead_time_days": 20, "supplier_verified": True},
    "finance_validation": {
        "unit_cost": 5.0,
        "sale_price": 20.0,
        "monthly_unit_sales": 300,
        "monthly_fixed_costs": 500.0,
    },
    "legal_validation": {"restricted_category": False},
}

LEGAL_VETO_CONTEXT = {
    **ATTRACTIVE_CONTEXT,
    "legal_validation": {
        "restricted_category": True,
        "requires_certification": True,
        "certification_available": False,
    },
}


@pytest.fixture()
def session_factory():
    db_path = Path(tempfile.mkstemp(suffix=".sqlite3")[1])
    engine = create_engine(f"sqlite+pysqlite:///{db_path}", connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _set_busy_timeout(dbapi_connection, connection_record):
        # SQLite allows only one writer at a time; without this, a second
        # thread's concurrent COMMIT can raise "database is locked"
        # immediately instead of waiting briefly for the first to finish -
        # a SQLite-only artifact of two real connections to one file, not
        # a real race in the orchestrator (real Postgres has proper MVCC
        # and doesn't need this).
        dbapi_connection.execute("PRAGMA busy_timeout=5000")

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        engine.dispose()
        try:
            db_path.unlink(missing_ok=True)
        except PermissionError:
            pass  # Windows can hold the file handle briefly after dispose(); harmless leftover temp file


def test_two_concurrent_objective_runs_do_not_interfere(session_factory):
    setup_session = session_factory()
    objective_a = Objective(
        id=new_id(), title="Objective A", created_by="owner@amazona.local", context=ATTRACTIVE_CONTEXT
    )
    objective_b = Objective(
        id=new_id(), title="Objective B", created_by="owner@amazona.local", context=LEGAL_VETO_CONTEXT
    )
    setup_session.add_all([objective_a, objective_b])
    setup_session.commit()
    objective_a_id = objective_a.id
    objective_b_id = objective_b.id
    setup_session.close()

    results: dict[str, object] = {}
    errors: list[Exception] = []

    def run(objective_id: str, key: str) -> None:
        thread_session = session_factory()
        try:
            orchestrator = CEOOrchestrator(thread_session)
            results[key] = orchestrator.run_objective(objective_id)
        except Exception as exc:  # noqa: BLE001 - surfaced via `errors` for the assertion below
            errors.append(exc)
        finally:
            thread_session.close()

    thread_a = threading.Thread(target=run, args=(objective_a_id, "a"))
    thread_b = threading.Thread(target=run, args=(objective_b_id, "b"))
    thread_a.start()
    thread_b.start()
    thread_a.join(timeout=30)
    thread_b.join(timeout=30)

    assert errors == []
    assert results["a"].status == DecisionStatus.GO.value
    assert results["b"].status == DecisionStatus.NO_GO.value

    verify_session = session_factory()
    try:
        project_a = verify_session.query(Project).filter_by(objective_id=objective_a_id).one()
        project_b = verify_session.query(Project).filter_by(objective_id=objective_b_id).one()
        assert project_a.id != project_b.id

        tasks_a = verify_session.query(Task).filter_by(project_id=project_a.id).all()
        tasks_b = verify_session.query(Task).filter_by(project_id=project_b.id).all()
        assert len(tasks_a) == 5
        assert len(tasks_b) == 5
        assert all(t.status == "COMPLETED" for t in tasks_a)
        assert all(t.status == "COMPLETED" for t in tasks_b)
        assert {t.id for t in tasks_a}.isdisjoint({t.id for t in tasks_b})
    finally:
        verify_session.close()
