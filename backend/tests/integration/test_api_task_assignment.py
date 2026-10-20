"""`GET /api/tasks` y `GET /api/agent-executions` dicen la relación tarea ↔ agente (M48, Commit 7).

Se EXTIENDEN las respuestas existentes (campos nuevos, ninguno quitado): `assigned_agent_id`, `agent_relation` por
tarea, y `task_id`, `assigned_agent_id`, `attempt`, `started_at`, `completed_at` por ejecución. Una misión de antes de
este commit (sin asignación) se lee desde su evento de auditoría y NO se le inventa una asignación; un agente que el
registro no conoce sale como desconocido."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.agents.registry import build_default_agent_manager
from app.ceo.orchestrator import CEOOrchestrator
from app.core.ids import new_id
from app.db.base import Base
from app.db.models.agent_execution_log import AgentExecutionLog
from app.db.models.audit import AuditLog
from app.db.models.objective import Objective
from app.db.models.project import Project
from app.db.models.task import Task
from app.db.session import get_db
from app.main import app

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
def factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override
    try:
        yield session_factory
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


@pytest.fixture()
def client(factory) -> TestClient:
    return TestClient(app)


def run_mission(factory) -> str:
    with factory() as db:
        row = Objective(id=new_id(), title="Mission", created_by="owner@amazona.local", context=CONTEXT)
        db.add(row)
        db.commit()
        _, manager = build_default_agent_manager()
        CEOOrchestrator(db, agent_manager=manager).run_objective(row.id)
        return db.query(Project).one().id


def relations(client, project_id: str) -> dict[str, dict]:
    body = client.get("/api/tasks", params={"project_id": project_id}).json()
    return {task["name"]: task for task in body}


def test_a_new_mission_reports_its_assignments_and_matches_through_the_existing_endpoint(client, factory):
    project_id = run_mission(factory)

    tasks = relations(client, project_id)

    product = tasks["product_validation"]
    assert product["assigned_agent_id"] == "agent-product-1"
    relation = product["agent_relation"]
    assert relation["status"] == "MATCH"
    assert relation["assigned_agent_id"] == "agent-product-1"
    assert relation["assigned_agent_known"] is True
    assert relation["executed_by_agent_id"] == "agent-product-1"
    assert relation["reassigned"] is False
    execution = relation["executions"][0]
    assert execution["source"] == "execution_log"
    assert (execution["agent_id"], execution["agent_known"], execution["attempt"], execution["success"]) == (
        "agent-product-1",
        True,
        1,
        True,
    )
    assert execution["assigned_agent_id"] == "agent-product-1"
    assert execution["started_at"] and execution["completed_at"] and execution["execution_id"]


def test_the_orchestrator_task_is_reported_as_the_orchestrators_not_as_unassigned(client, factory):
    synthesis = relations(client, run_mission(factory))["decision_synthesis"]

    assert synthesis["assigned_agent_id"] is None
    assert synthesis["agent_relation"]["status"] == "ORCHESTRATOR"
    assert synthesis["agent_relation"]["executions"] == []


def test_the_existing_fields_of_a_task_are_all_still_there(client, factory):
    task = relations(client, run_mission(factory))["supplier_sourcing"]

    for field in ("id", "project_id", "name", "capability", "status", "input", "output", "error", "depends_on"):
        assert field in task
    assert task["status"] == "COMPLETED"


def test_a_historical_mission_is_read_from_its_audit_event_and_no_assignment_is_invented(client, factory):
    with factory() as db:
        project = Project(objective_id="obj-old", name="Old", status="VALIDATING")
        db.add(project)
        db.flush()
        done = Task(
            project_id=project.id, name="product_validation", capability="market_validation", status="COMPLETED"
        )
        synthesis = Task(
            project_id=project.id, name="decision_synthesis", capability="decision_synthesis", status="COMPLETED"
        )
        db.add_all([done, synthesis])
        db.flush()
        db.add(
            AuditLog(
                actor="agent-product-1",
                action="task.completed",
                resource=f"task:{done.id}",
                before=None,
                after={"recommendation": "GO"},
                correlation_id="c-old",
            )
        )
        db.add(
            AgentExecutionLog(
                agent_id="agent-product-1",
                capability="market_validation",
                duration_ms=1.0,
                success=True,
                correlation_id="c-old",
            )
        )
        db.commit()
        project_id = project.id

    tasks = relations(client, project_id)

    old = tasks["product_validation"]
    assert old["assigned_agent_id"] is None
    assert old["agent_relation"]["status"] == "EXECUTED_UNASSIGNED"
    assert old["agent_relation"]["executed_by_agent_id"] == "agent-product-1"
    assert [item["source"] for item in old["agent_relation"]["executions"]] == ["audit"]
    assert tasks["decision_synthesis"]["agent_relation"]["status"] == "ORCHESTRATOR"
    with factory() as db:
        assert db.query(Task).filter(Task.assigned_agent_id.isnot(None)).count() == 0, "leer no asigna nada"


def test_an_agent_the_registry_does_not_know_is_reported_as_unknown_never_as_unassigned(client, factory):
    with factory() as db:
        project = Project(objective_id="obj-x", name="X", status="VALIDATING")
        db.add(project)
        db.flush()
        db.add(
            Task(
                project_id=project.id,
                name="product_validation",
                capability="market_validation",
                status="PENDING",
                assigned_agent_id="agent-ghost-9",
            )
        )
        db.commit()
        project_id = project.id

    relation = relations(client, project_id)["product_validation"]["agent_relation"]

    assert relation["status"] == "UNKNOWN_AGENT"
    assert relation["assigned_agent_known"] is False
    assert relation["assigned_agent_id"] == "agent-ghost-9"


def test_a_completed_agent_task_with_no_trace_is_reported_as_an_inconsistency(client, factory):
    with factory() as db:
        project = Project(objective_id="obj-y", name="Y", status="VALIDATING")
        db.add(project)
        db.flush()
        db.add(Task(project_id=project.id, name="legal_validation", capability="legal_validation", status="COMPLETED"))
        db.commit()
        project_id = project.id

    assert relations(client, project_id)["legal_validation"]["agent_relation"]["status"] == "INCONSISTENT"


def test_a_deviation_is_visible_in_the_api(client, factory):
    project_id = run_mission(factory)
    with factory() as db:
        task = db.query(Task).filter_by(name="product_validation").one()
        row = db.query(AgentExecutionLog).filter_by(task_id=task.id).one()
        row.agent_id = "agent-supplier-1"  # alguien que no era el asignado la ejecutó
        db.commit()

    relation = relations(client, project_id)["product_validation"]["agent_relation"]

    assert relation["status"] == "MISMATCH"
    assert relation["assigned_agent_id"] == "agent-product-1"
    assert relation["executed_by_agent_id"] == "agent-supplier-1"


def test_a_reassignment_is_reported_with_the_current_assignment(client, factory):
    project_id = run_mission(factory)
    with factory() as db:
        from app.tasks.assignment import TaskAssignmentService

        task = db.query(Task).filter_by(name="product_validation").one()
        service = TaskAssignmentService(db, {"agent-product-1", "agent-supplier-1"})
        service.reassign(task, "agent-supplier-1", actor="ceo", reason="manual", correlation_id="c-9")
        db.commit()

    relation = relations(client, project_id)["product_validation"]["agent_relation"]

    assert relation["reassigned"] is True
    assert relation["assigned_agent_id"] == "agent-supplier-1"
    assert relation["status"] == "MISMATCH", "la ejecución anterior fue de otro agente: no se reescribe"


def test_the_executions_endpoint_adds_the_link_to_the_task_without_removing_anything(client, factory):
    run_mission(factory)

    rows = client.get("/api/agent-executions").json()

    assert len(rows) == 4
    for row in rows:
        for field in ("id", "agent_id", "capability", "duration_ms", "success", "correlation_id", "created_at"):
            assert field in row
        assert row["task_id"]
        assert row["assigned_agent_id"] == row["agent_id"]
        assert row["attempt"] == 1
        assert row["started_at"] and row["completed_at"]


def test_historical_executions_have_null_links_and_are_not_filled_in(client, factory):
    with factory() as db:
        db.add(
            AgentExecutionLog(
                agent_id="agent-product-1",
                capability="market_validation",
                duration_ms=1.0,
                success=True,
                correlation_id="c-old",
            )
        )
        db.commit()

    row = client.get("/api/agent-executions").json()[0]

    assert (row["task_id"], row["assigned_agent_id"], row["attempt"], row["started_at"], row["completed_at"]) == (
        None,
        None,
        None,
        None,
        None,
    )


def test_a_project_with_no_tasks_reads_an_empty_list_not_an_error(client, factory):
    with factory() as db:
        project = Project(objective_id="obj-z", name="Z", status="VALIDATING")
        db.add(project)
        db.commit()
        project_id = project.id

    response = client.get("/api/tasks", params={"project_id": project_id})

    assert response.status_code == 200
    assert response.json() == []


def test_the_tasks_endpoint_needs_no_new_route(client):
    paths = set(app.openapi()["paths"])
    assert "/api/tasks" in paths
    assert not [path for path in paths if "assignment" in path or "task-agent" in path]


def test_an_execution_by_an_agent_the_registry_does_not_know_is_reported_unknown_on_the_trace_too(client, factory):
    project_id = run_mission(factory)
    with factory() as db:
        task = db.query(Task).filter_by(name="product_validation").one()
        row = db.query(AgentExecutionLog).filter_by(task_id=task.id).one()
        row.agent_id = "agent-ghost-9"
        db.commit()

    relation = relations(client, project_id)["product_validation"]["agent_relation"]

    assert relation["status"] == "UNKNOWN_AGENT"
    assert [(item["agent_id"], item["agent_known"]) for item in relation["executions"]] == [("agent-ghost-9", False)]
    assert relation["executed_by_agent_id"] == "agent-ghost-9"


def test_a_known_executor_is_reported_known_on_the_trace(client, factory):
    project_id = run_mission(factory)

    relation = relations(client, project_id)["product_validation"]["agent_relation"]

    assert [(item["agent_id"], item["agent_known"]) for item in relation["executions"]] == [("agent-product-1", True)]
