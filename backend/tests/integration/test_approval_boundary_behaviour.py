"""Cada bandeja autoriza lo suyo y nada más (hardening pre-M44, ADR 0027).

La frontera estática (quién importa a quién) la guarda `tests/unit/test_approval_boundary.py`. Aquí se prueba lo
que ocurre de verdad al resolver una y otra: una aprobación del CEO no desbloquea un paso del pipeline, resolver una
revisión del pipeline no toca ni las aprobaciones ni el libro, y una revisión a posteriori no es una autorización.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.budgets.service import BudgetLedgerService
from app.ceo.orchestrator import CEOOrchestrator
from app.ceo.schemas import ApprovalStatus
from app.core.ids import new_id
from app.db.base import Base
from app.db.models.approval import Approval
from app.db.models.audit import AuditLog
from app.db.models.budget import BudgetAllocation, FinancialEvent
from app.db.models.objective import Objective
from app.db.models.pipeline_review import PipelineReview
from app.db.models.pipeline_run import PipelineRun
from app.db.models.storefront import Storefront
from app.db.session import get_db
from app.jobs.worker import Worker
from app.main import app
from app.pipeline.schemas import REVIEW_KIND_ACTION_GATE, PipelineRunStatus
from app.pipeline.service import PipelineOrchestrator, PipelineRequest

OWNER = "owner@amazona.local"
#: Economía NO_GO de verdad: el precio no cubre ni el coste, así que el paso de ecommerce pregunta.
GATED = PipelineRequest(category="home", sale_price=0.5, destination_region="mexico", market="us")
SPEND_CONTEXT = {
    "product_validation": {"estimated_monthly_searches": 12000, "competition_level": "low"},
    "supplier_sourcing": {"unit_cost": 5.0, "lead_time_days": 20, "supplier_verified": True},
    "finance_validation": {
        "unit_cost": 5.0,
        "sale_price": 20.0,
        "monthly_unit_sales": 300,
        "monthly_fixed_costs": 500.0,
    },
    "legal_validation": {"restricted_category": False},
    "requests_simulated_spend": True,
    "spend_action": "publish_product",
    "spend_amount": 100.0,
}


@pytest.fixture()
def session_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, expire_on_commit=False)
    engine.dispose()


@pytest.fixture()
def client(session_factory):
    def override_get_db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.fixture()
def db(session_factory):
    with session_factory() as session:
        BudgetLedgerService(session).authorise_budget(hard_limit=1_000.0, actor=OWNER)
        yield session


def drain(db: Session, rounds: int = 12) -> None:
    worker = Worker(name="test-worker")
    for _ in range(rounds):
        if worker.run_once(db) is None:
            break


def gated_run(db: Session) -> PipelineRun:
    """Una ejecución parada delante de la puerta del paso de ecommerce."""
    run = PipelineOrchestrator(db).enqueue_run(GATED)
    drain(db)
    db.refresh(run)
    assert run.status == PipelineRunStatus.WAITING_APPROVAL
    return run


def pending_gate(db: Session, run: PipelineRun) -> PipelineReview:
    db.expire_all()
    return db.query(PipelineReview).filter_by(pipeline_run_id=run.id, kind=REVIEW_KIND_ACTION_GATE).one()


def ceo_approval(db: Session) -> Approval:
    """Una aprobación pendiente de una decisión del CEO, con su importe ya reservado."""
    objective = Objective(id=new_id(), title="spend", created_by=OWNER, context=SPEND_CONTEXT)
    db.add(objective)
    db.commit()
    CEOOrchestrator(db).run_objective(objective.id)
    db.commit()
    return db.query(Approval).one()


def counts(db: Session) -> dict[str, int]:
    db.expire_all()
    return {
        "approvals": db.query(Approval).count(),
        "reviews": db.query(PipelineReview).count(),
        "ledger_events": db.query(FinancialEvent).count(),
        "storefronts": db.query(Storefront).count(),
    }


def ledger(db: Session) -> tuple[float, float]:
    db.expire_all()
    row = db.query(BudgetAllocation).one()
    return float(row.reserved), float(row.committed)


def test_an_approved_ceo_decision_does_not_unblock_a_pipeline_step(client: TestClient, db: Session):
    run = gated_run(db)
    approval = ceo_approval(db)

    resolved = client.post(f"/api/approvals/{approval.id}/approve", json={"actor": OWNER})
    assert resolved.status_code == 200
    PipelineOrchestrator(db).resume_run(db.get(PipelineRun, run.id), actor=OWNER)
    drain(db)

    db.refresh(run)
    assert run.status == PipelineRunStatus.WAITING_APPROVAL  # la pregunta del paso sigue sin contestar
    assert pending_gate(db, run).status == "PENDING"
    assert db.query(Storefront).count() == 0


def test_resolving_a_pipeline_review_touches_neither_the_ceo_approvals_nor_the_ledger(client: TestClient, db: Session):
    run = gated_run(db)
    approval = ceo_approval(db)
    before = counts(db)
    ledger_before = ledger(db)

    response = client.post(f"/api/pipeline/reviews/{pending_gate(db, run).id}/approve", json={"actor": OWNER})

    assert response.status_code == 200
    after = counts(db)
    assert after["approvals"] == before["approvals"]
    assert after["ledger_events"] == before["ledger_events"]
    assert ledger(db) == ledger_before  # el importe reservado por el CEO sigue siendo del CEO
    db.refresh(approval)
    assert approval.status == "PENDING"


def test_resolving_a_ceo_approval_touches_no_pipeline_review(client: TestClient, db: Session):
    run = gated_run(db)
    approval = ceo_approval(db)
    review_before = pending_gate(db, run).status

    client.post(f"/api/approvals/{approval.id}/approve", json={"actor": OWNER})

    assert pending_gate(db, run).status == review_before == "PENDING"
    assert ledger(db) == (0.0, 100.0)  # y lo suyo, el importe, sí se compromete: es la decisión que aprobó
    actions = {entry.action for entry in db.query(AuditLog).filter(AuditLog.action.like("pipeline_review.%"))}
    assert actions == set()


def test_a_post_hoc_review_is_not_an_authorisation_to_act(db: Session):
    run = gated_run(db)
    db.add(
        PipelineReview(
            pipeline_run_id=run.id,
            kind="POST_HOC",
            reasons=["looked at after the fact"],
            status="APPROVED",
            correlation_id=run.correlation_id,
        )
    )
    db.commit()

    PipelineOrchestrator(db).resume_run(db.get(PipelineRun, run.id), actor=OWNER)
    drain(db)

    db.refresh(run)
    assert run.status == PipelineRunStatus.WAITING_APPROVAL
    assert db.query(Storefront).count() == 0


def test_the_two_inboxes_have_different_states_and_only_one_expires():
    """Una autorización de un paso se **consume**; una decisión del CEO **caduca**. Estados distintos a propósito."""
    approval_states = {state.value for state in ApprovalStatus}

    assert hasattr(Approval, "expires_at") and not hasattr(PipelineReview, "expires_at")
    assert "EXPIRED" in approval_states and "CONSUMED" not in approval_states
