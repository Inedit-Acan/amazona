"""Verifies two concurrent run_objective() calls on distinct objectives
don't interfere with each other.

Each call gets its own TaskService instance (an orchestrator-local, in
memory DAG — see app/tasks/service.py) and, here, its own SQLAlchemy
Session bound to a shared StaticPool SQLite engine so both threads see
the same database. That isolation (own TaskService + own Session per
call) is what this test exists to prove is actually race-free, not just
architecturally plausible.
"""

import threading

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

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
    engine = create_engine(
        "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        engine.dispose()


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
