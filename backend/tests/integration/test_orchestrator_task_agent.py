"""El orquestador asigna cada tarea a un agente al crearla y ejecuta al asignado (M48, Commit 7).

Lo que se fija: la asignación sale del REGISTRO de agentes (no de un mapa duplicado) y queda en la tarea y en la
auditoría; cada ejecución del log lleva su `task_id`, la foto de la asignación, el intento y las horas; un reintento
añade una fila y no pisa la anterior; si el agente asignado deja de poder ejecutar, se REASIGNA de forma explícita y
auditada; y `decision_synthesis` es del orquestador, no de ningún agente."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.agents.base import Agent, AgentDescriptor, AgentResult, AgentStatus
from app.agents.finance import FinanceAgent
from app.agents.legal import LegalAgent
from app.agents.manager import AgentManager
from app.agents.product import ProductAgent
from app.agents.registry import AgentRegistry, build_default_agent_manager
from app.agents.supplier import SupplierAgent
from app.ceo.orchestrator import CEOOrchestrator
from app.core.ids import new_id
from app.db.base import Base
from app.db.models.agent_execution_log import AgentExecutionLog
from app.db.models.audit import AuditLog
from app.db.models.objective import Objective
from app.db.models.task import Task
from app.tasks.assignment import AssignmentStatus, TaskAssignmentService, load_relations

CONTEXT = {
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


@pytest.fixture()
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def objective(db: Session) -> Objective:
    row = Objective(id=new_id(), title="Task agent", created_by="owner@amazona.local", context=CONTEXT)
    db.add(row)
    db.commit()
    return row


def tasks_by_name(db: Session) -> dict[str, Task]:
    return {task.name: task for task in db.query(Task).all()}


def audit(db: Session, action: str) -> list[AuditLog]:
    return db.query(AuditLog).filter_by(action=action).order_by(AuditLog.created_at).all()


def run_default(db: Session):
    registry, manager = build_default_agent_manager()
    decision = CEOOrchestrator(db, agent_manager=manager).run_objective(objective(db).id)
    return decision, registry, manager


# --- crear: la asignación sale del registro ---------------------------------------------------------------------------


def test_each_agent_task_is_assigned_to_the_registry_agent_for_its_capability_when_it_is_created(db):
    decision, registry, _ = run_default(db)

    tasks = tasks_by_name(db)
    assert {name: task.assigned_agent_id for name, task in tasks.items() if name != "decision_synthesis"} == {
        "product_validation": "agent-product-1",
        "supplier_sourcing": "agent-supplier-1",
        "legal_validation": "agent-legal-1",
        "finance_validation": "agent-finance-1",
    }
    # Y son agentes del registro: no hay un mapa duplicado, y un id que no esté en él no puede salir de aquí.
    known = {agent.id for agent in registry.list_all()}
    assert all(task.assigned_agent_id in known for name, task in tasks.items() if name != "decision_synthesis")
    assert decision.correlation_id


def test_the_assignments_are_audited_one_event_per_task_with_the_mission_correlation(db):
    decision, _, _ = run_default(db)

    events = audit(db, "task.assigned")

    assert len(events) == 4
    assert {event.correlation_id for event in events} == {decision.correlation_id}
    assert {event.actor for event in events} == {"ceo"}
    tasks = tasks_by_name(db)
    by_resource = {event.resource: event for event in events}
    assert set(by_resource) == {f"task:{tasks[name].id}" for name in tasks if name != "decision_synthesis"}
    for event in events:
        assert event.before is None
        assert event.after["agent_id"].startswith("agent-")


def test_decision_synthesis_belongs_to_the_orchestrator_it_gets_no_agent_and_no_assignment_event(db):
    run_default(db)

    synthesis = tasks_by_name(db)["decision_synthesis"]

    assert synthesis.assigned_agent_id is None
    assert not [event for event in audit(db, "task.assigned") if event.resource == f"task:{synthesis.id}"]
    assert not db.query(AgentExecutionLog).filter_by(task_id=synthesis.id).count()
    relation = load_relations(db, [synthesis], {"agent-product-1"})[synthesis.id]
    assert relation.status is AssignmentStatus.ORCHESTRATOR


def test_the_assignment_does_not_come_from_the_task_name_it_comes_from_the_capability_in_the_registry(db):
    """Cambia el agente del registro para la capacidad y la asignación lo sigue: no hay ningún `agent-product-1` escrito
    en el orquestador."""
    registry = AgentRegistry()
    manager = AgentManager(registry)
    renamed = {
        "agent-alpha": ProductAgent(),
        "agent-beta": SupplierAgent(),
        "agent-gamma": FinanceAgent(),
        "agent-delta": LegalAgent(),
    }
    for agent_id, executor in renamed.items():
        registry.register(
            AgentDescriptor(id=agent_id, name=agent_id, role="x", version="1", capabilities=[executor.capability])
        )
        manager.register_executor(agent_id, executor)

    CEOOrchestrator(db, agent_manager=manager).run_objective(objective(db).id)

    tasks = tasks_by_name(db)
    assert tasks["product_validation"].assigned_agent_id == "agent-alpha"
    assert tasks["finance_validation"].assigned_agent_id == "agent-gamma"


# --- ejecutar: el log lleva la tarea, la foto y las horas -------------------------------------------------------------


def test_every_agent_execution_is_linked_to_its_task_with_the_assignment_snapshot_the_attempt_and_the_times(db):
    decision, _, _ = run_default(db)
    tasks = tasks_by_name(db)

    rows = db.query(AgentExecutionLog).filter_by(correlation_id=decision.correlation_id).all()

    assert len(rows) == 4
    by_task = {row.task_id: row for row in rows}
    for name in ("product_validation", "supplier_sourcing", "legal_validation", "finance_validation"):
        row = by_task[tasks[name].id]
        assert row.agent_id == row.assigned_agent_id == tasks[name].assigned_agent_id
        assert row.attempt == 1
        assert row.success is True
        assert row.started_at is not None and row.completed_at is not None
        assert row.completed_at >= row.started_at
        assert row.capability == tasks[name].capability


def test_a_normal_mission_reads_as_four_matches_and_one_orchestrator_task_and_no_deviation_is_audited(db):
    _, registry, _ = run_default(db)
    known = {agent.id for agent in registry.list_all()}

    relations = load_relations(db, list(tasks_by_name(db).values()), known)

    statuses = sorted(item.status.value for item in relations.values())
    assert statuses == ["MATCH", "MATCH", "MATCH", "MATCH", "ORCHESTRATOR"]
    assert not audit(db, "task.executed_by_other_agent")
    assert not audit(db, "task.reassigned")


# --- reintentos -------------------------------------------------------------------------------------------------------


class Flaky(Agent):
    capability = "market_validation"

    def __init__(self, fail_times: int, *, on_first_failure=None) -> None:
        self.fail_times = fail_times
        self.calls = 0
        self.on_first_failure = on_first_failure

    def run(self, task_input: dict) -> AgentResult:
        self.calls += 1
        if self.calls <= self.fail_times:
            if self.calls == 1 and self.on_first_failure is not None:
                self.on_first_failure()
            raise RuntimeError(f"simulated failure #{self.calls}")
        return AgentResult(
            status="COMPLETED",
            recommendation="GO",
            confidence=0.9,
            evidence=["ok"],
            risks=[],
            assumptions=[],
            data={"opportunity_score": 0.8},
        )


def build_manager(product_agents: dict[str, Agent]) -> tuple[AgentRegistry, AgentManager]:
    registry = AgentRegistry()
    manager = AgentManager(registry)
    specialists = {
        **product_agents,
        "agent-supplier-1": SupplierAgent(),
        "agent-finance-1": FinanceAgent(),
        "agent-legal-1": LegalAgent(),
    }
    for index, (agent_id, executor) in enumerate(specialists.items()):
        registry.register(
            AgentDescriptor(
                id=agent_id,
                name=agent_id,
                role="x",
                version="1",
                capabilities=[executor.capability],
                reliability_score=1.0 - index * 0.01 if agent_id.startswith("agent-product") else 1.0,
            )
        )
        manager.register_executor(agent_id, executor)
    return registry, manager


def test_F_a_retry_by_the_same_agent_adds_a_row_per_attempt_and_keeps_the_assignment(db):
    flaky = Flaky(fail_times=2)
    registry, manager = build_manager({"agent-product-1": flaky})

    CEOOrchestrator(db, agent_manager=manager, max_task_retries=2).run_objective(objective(db).id)

    task = tasks_by_name(db)["product_validation"]
    rows = db.query(AgentExecutionLog).filter_by(task_id=task.id).order_by(AgentExecutionLog.attempt).all()
    assert [(row.attempt, row.success, row.agent_id) for row in rows] == [
        (1, False, "agent-product-1"),
        (2, False, "agent-product-1"),
        (3, True, "agent-product-1"),
    ]
    assert task.assigned_agent_id == "agent-product-1"
    assert not audit(db, "task.reassigned")
    relation = load_relations(db, [task], {a.id for a in registry.list_all()})[task.id]
    assert relation.status is AssignmentStatus.MATCH
    assert len(relation.executions) == 3


def test_G_when_the_assigned_agent_stops_being_routable_the_retry_goes_to_another_agent_with_an_explicit_reassignment(
    db,
):
    registry_holder: dict[str, AgentRegistry] = {}

    def disable_first_agent() -> None:
        registry_holder["registry"].set_status("agent-product-1", AgentStatus.DISABLED)

    first = Flaky(fail_times=1, on_first_failure=disable_first_agent)
    second = Flaky(fail_times=0)
    registry, manager = build_manager({"agent-product-1": first, "agent-product-2": second})
    registry_holder["registry"] = registry

    CEOOrchestrator(db, agent_manager=manager, max_task_retries=2).run_objective(objective(db).id)

    task = tasks_by_name(db)["product_validation"]
    assert task.assigned_agent_id == "agent-product-2"
    rows = db.query(AgentExecutionLog).filter_by(task_id=task.id).order_by(AgentExecutionLog.attempt).all()
    assert [(row.attempt, row.agent_id, row.assigned_agent_id, row.success) for row in rows] == [
        (1, "agent-product-1", "agent-product-1", False),
        (2, "agent-product-2", "agent-product-2", True),
    ]
    history = TaskAssignmentService(db, {"agent-product-1", "agent-product-2"}).history(task.id)
    assert [(item.kind, item.before_agent_id, item.agent_id) for item in history] == [
        ("assigned", None, "agent-product-1"),
        ("reassigned", "agent-product-1", "agent-product-2"),
    ]
    reassigned = audit(db, "task.reassigned")
    assert len(reassigned) == 1
    assert "not routable" in reassigned[0].after["reason"]
    relation = load_relations(db, [task], {"agent-product-1", "agent-product-2"})[task.id]
    assert relation.status is AssignmentStatus.MATCH
    assert relation.reassigned is True
    assert len(relation.executions) == 2


def test_a_task_with_no_available_agent_at_creation_stays_unassigned_it_is_not_filled_by_capability(db):
    registry = AgentRegistry()
    manager = AgentManager(registry)
    for agent_id, executor in {
        "agent-supplier-1": SupplierAgent(),
        "agent-finance-1": FinanceAgent(),
        "agent-legal-1": LegalAgent(),
    }.items():
        registry.register(
            AgentDescriptor(id=agent_id, name=agent_id, role="x", version="1", capabilities=[executor.capability])
        )
        manager.register_executor(agent_id, executor)
    # no hay agente de producto: la ejecución falla como siempre, y la tarea no queda atribuida a nadie

    from app.core.errors import NoAgentAvailableError

    with pytest.raises(NoAgentAvailableError):
        CEOOrchestrator(db, agent_manager=manager).run_objective(objective(db).id)
    db.rollback()


def test_the_default_registry_is_the_one_source_of_the_agents_the_api_lists_and_the_assignments_use():
    from app.agents.registry import default_agent_registry

    first = default_agent_registry()
    assert first is default_agent_registry()
    assert {agent.id for agent in first.list_all()} >= {
        "agent-product-1",
        "agent-supplier-1",
        "agent-legal-1",
        "agent-finance-1",
    }


def test_an_agent_that_declares_decision_synthesis_still_does_not_get_the_orchestrators_task(db):
    """La capacidad del orquestador no se reparte aunque el registro tenga un agente que la declare."""
    registry, manager = build_manager({"agent-product-1": Flaky(fail_times=0)})
    registry.register(
        AgentDescriptor(id="agent-synth", name="synth", role="x", version="1", capabilities=["decision_synthesis"])
    )

    CEOOrchestrator(db, agent_manager=manager).run_objective(objective(db).id)

    synthesis = tasks_by_name(db)["decision_synthesis"]
    assert synthesis.assigned_agent_id is None
    assert not audit(db, "task.reassigned")
    assert not [event for event in audit(db, "task.assigned") if event.resource == f"task:{synthesis.id}"]


def test_a_call_that_executed_nothing_records_no_execution_it_does_not_reuse_the_previous_one(db):
    """El agente de proveedores está en el registro pero no tiene ejecutor: la llamada no llega a ejecutar nada. Su
    tarea no hereda la fila del log de la tarea anterior."""
    registry, manager = build_manager({"agent-product-1": Flaky(fail_times=0)})
    manager._executors.pop("agent-supplier-1")

    try:
        CEOOrchestrator(db, agent_manager=manager, max_task_retries=0).run_objective(objective(db).id)
    except Exception:  # noqa: BLE001, S110 - lo que se comprueba es lo que quedó escrito
        db.rollback()

    supplier = tasks_by_name(db)["supplier_sourcing"]
    assert db.query(AgentExecutionLog).filter_by(task_id=supplier.id).count() == 0
    assert not [row for row in db.query(AgentExecutionLog).all() if row.task_id is None]
