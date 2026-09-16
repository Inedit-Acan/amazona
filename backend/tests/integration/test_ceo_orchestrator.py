import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.ceo.orchestrator import CEOOrchestrator
from app.ceo.schemas import DecisionStatus
from app.core.ids import new_id
from app.db.base import Base
from app.db.models.agent_execution_log import AgentExecutionLog
from app.db.models.approval import Approval
from app.db.models.budget import BudgetAllocation, FinancialEvent
from app.db.models.decision import DecisionEvidence
from app.db.models.objective import Objective
from app.db.models.project import Project
from app.db.models.task import Task, TaskDependency

ATTRACTIVE_PRODUCT_CONTEXT = {
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
    "spend_action": "launch_marketing_campaign",
    "spend_amount": 150.0,
}


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


def create_objective(db_session: Session, context: dict) -> Objective:
    objective = Objective(
        id=new_id(),
        title="Validate wireless earbuds opportunity",
        description="Assess a candidate product for Amazon FBA launch.",
        created_by="owner@amazona.local",
        context=context,
    )
    db_session.add(objective)
    db_session.commit()
    return objective


def test_run_objective_produces_a_full_audited_workflow_requiring_human_approval(db_session: Session):
    objective = create_objective(db_session, ATTRACTIVE_PRODUCT_CONTEXT)
    orchestrator = CEOOrchestrator(db_session)

    decision = orchestrator.run_objective(objective.id)

    assert decision.status == DecisionStatus.HUMAN_APPROVAL.value

    project = db_session.query(Project).filter_by(objective_id=objective.id).one()
    assert project is not None

    tasks = db_session.query(Task).filter_by(project_id=project.id).all()
    assert len(tasks) == 5
    assert {t.name for t in tasks} == {
        "product_validation",
        "supplier_sourcing",
        "finance_validation",
        "legal_validation",
        "decision_synthesis",
    }
    assert all(t.status == "COMPLETED" for t in tasks)

    tasks_by_name = {t.name: t for t in tasks}
    dependencies = db_session.query(TaskDependency).all()
    dependency_pairs = {(d.parent_task_id, d.child_task_id) for d in dependencies}
    assert (
        tasks_by_name["product_validation"].id,
        tasks_by_name["supplier_sourcing"].id,
    ) in dependency_pairs
    assert (
        tasks_by_name["finance_validation"].id,
        tasks_by_name["decision_synthesis"].id,
    ) in dependency_pairs

    evidence = db_session.query(DecisionEvidence).filter_by(decision_id=decision.id).all()
    assert len(evidence) == 4
    assert all("risks" in e.data for e in evidence)
    assert all("recommendation" in e.data for e in evidence)
    finance_evidence = next(e for e in evidence if e.source == "finance_validation")
    assert finance_evidence.data["risks"] == []

    execution_logs = db_session.query(AgentExecutionLog).filter_by(correlation_id=decision.correlation_id).all()
    assert len(execution_logs) == 4
    assert all(log.success for log in execution_logs)
    assert all(log.duration_ms >= 0 for log in execution_logs)

    approval = db_session.query(Approval).filter_by(decision_id=decision.id).one()
    assert approval.status == "PENDING"
    assert approval.action == "launch_marketing_campaign"
    assert approval.amount == 150.0

    correlation_id = decision.correlation_id
    audit_actions = {e.action for e in orchestrator.audit_service.list_for_correlation(correlation_id)}
    assert "project.created" in audit_actions
    assert "decision.made" in audit_actions
    assert "approval.requested" in audit_actions

    allocation = db_session.query(BudgetAllocation).one()
    assert allocation.reserved == 150.0
    assert allocation.committed == 0.0
    reserve_event = db_session.query(FinancialEvent).filter_by(type="RESERVE").one()
    assert reserve_event.amount == 150.0
    assert reserve_event.reference == f"approval:{approval.id}"


def test_run_objective_with_legal_veto_results_in_no_go_and_no_approval(db_session: Session):
    context = {
        **ATTRACTIVE_PRODUCT_CONTEXT,
        "legal_validation": {
            "restricted_category": True,
            "requires_certification": True,
            "certification_available": False,
        },
    }
    objective = create_objective(db_session, context)
    orchestrator = CEOOrchestrator(db_session)

    decision = orchestrator.run_objective(objective.id)

    assert decision.status == DecisionStatus.NO_GO.value

    approvals = db_session.query(Approval).filter_by(decision_id=decision.id).all()
    assert approvals == []

    project = db_session.query(Project).filter_by(objective_id=objective.id).one()
    assert project.status == "REJECTED"


def test_run_objective_raises_for_an_unknown_objective(db_session: Session):
    from app.core.errors import NotFoundError

    orchestrator = CEOOrchestrator(db_session)

    with pytest.raises(NotFoundError):
        orchestrator.run_objective("does-not-exist")
