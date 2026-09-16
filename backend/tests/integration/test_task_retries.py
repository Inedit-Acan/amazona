import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.agents.base import Agent, AgentDescriptor, AgentResult
from app.agents.finance import FinanceAgent
from app.agents.legal import LegalAgent
from app.agents.manager import AgentManager
from app.agents.registry import AgentRegistry
from app.agents.supplier import SupplierAgent
from app.ceo.orchestrator import CEOOrchestrator
from app.ceo.schemas import DecisionStatus
from app.core.ids import new_id
from app.db.base import Base
from app.db.models.audit import AuditLog
from app.db.models.objective import Objective
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


class FlakyProductAgent(Agent):
    """Fails the first `fail_times` calls, then succeeds deterministically."""

    capability = "market_validation"

    def __init__(self, fail_times: int) -> None:
        self.fail_times = fail_times
        self.calls = 0

    def run(self, task_input: dict) -> AgentResult:
        self.calls += 1
        if self.calls <= self.fail_times:
            raise RuntimeError(f"simulated transient failure #{self.calls}")
        return AgentResult(
            status="COMPLETED",
            recommendation="GO",
            confidence=0.9,
            evidence=["recovered after retry"],
            risks=[],
            assumptions=[],
            data={"opportunity_score": 0.8},
        )


def build_manager(product_agent: Agent) -> AgentManager:
    registry = AgentRegistry()
    manager = AgentManager(registry)
    specialists = [
        ("agent-product-1", product_agent),
        ("agent-supplier-1", SupplierAgent()),
        ("agent-finance-1", FinanceAgent()),
        ("agent-legal-1", LegalAgent()),
    ]
    for agent_id, executor in specialists:
        registry.register(
            AgentDescriptor(
                id=agent_id,
                name=agent_id,
                role="specialist",
                version="1.0.0",
                capabilities=[executor.capability],
                reliability_score=1.0,
            )
        )
        manager.register_executor(agent_id, executor)
    return manager


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


def create_objective(db_session: Session) -> Objective:
    objective = Objective(
        id=new_id(), title="Retry test", created_by="owner@amazona.local", context=ATTRACTIVE_CONTEXT
    )
    db_session.add(objective)
    db_session.commit()
    return objective


def test_task_recovers_after_transient_failures_within_the_retry_bound(db_session: Session):
    objective = create_objective(db_session)
    flaky = FlakyProductAgent(fail_times=2)
    orchestrator = CEOOrchestrator(db_session, agent_manager=build_manager(flaky), max_task_retries=2)

    decision = orchestrator.run_objective(objective.id)

    assert flaky.calls == 3
    task = db_session.query(Task).filter_by(name="product_validation").one()
    assert task.status == "COMPLETED"
    assert task.output["data"]["opportunity_score"] == 0.8
    assert decision.status in {
        DecisionStatus.GO.value,
        DecisionStatus.REVIEW.value,
        DecisionStatus.HUMAN_APPROVAL.value,
    }


def test_task_fails_permanently_after_exhausting_retries_without_crashing(db_session: Session):
    objective = create_objective(db_session)
    always_fails = FlakyProductAgent(fail_times=999)
    orchestrator = CEOOrchestrator(db_session, agent_manager=build_manager(always_fails), max_task_retries=2)

    decision = orchestrator.run_objective(objective.id)

    assert always_fails.calls == 3  # 1 initial attempt + 2 retries, never unbounded
    task = db_session.query(Task).filter_by(name="product_validation").one()
    assert task.status == "FAILED"
    assert decision.status == DecisionStatus.REVIEW.value

    audit_actions = [e.action for e in db_session.query(AuditLog).filter_by(correlation_id=decision.correlation_id)]
    assert audit_actions.count("task.retried") == 2
    assert audit_actions.count("task.failed") == 1
