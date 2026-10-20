"""El servicio de asignación tarea ↔ agente (M48, Commit 7): asignar, reasignar, historia, ejecución registrada y
lectura de la relación.

La asignación vive en `tasks.assigned_agent_id`; la ejecución, en `agent_execution_log` (con `task_id`, la foto de la
asignación vigente y el intento); la historia de reasignaciones, en el `audit_log` (solo se añade). Nada de esto se
infiere de la capacidad, del nombre ni de la correlación."""

import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.errors import ValidationError
from app.db.base import Base
from app.db.models.agent_execution_log import AgentExecutionLog
from app.db.models.audit import AuditLog
from app.db.models.project import Project
from app.db.models.task import Task
from app.tasks.assignment import AssignmentStatus, TaskAssignmentService, load_relations

KNOWN = {"agent-product-1", "agent-product-2", "agent-supplier-1"}
NOW = datetime.datetime(2026, 10, 20, 12, 0, tzinfo=datetime.UTC)


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


@pytest.fixture()
def service(db: Session) -> TaskAssignmentService:
    return TaskAssignmentService(db, KNOWN)


def make_task(
    db: Session, *, capability="market_validation", name="product_validation", status="PENDING", project_id=None
) -> Task:
    if project_id is None:
        project = Project(objective_id="obj-1", name="P", status="VALIDATING")
        db.add(project)
        db.flush()
        project_id = project.id
    task = Task(project_id=project_id, name=name, capability=capability, status=status)
    db.add(task)
    db.flush()
    return task


def audit_actions(db: Session, task: Task) -> list[str]:
    rows = db.query(AuditLog).filter_by(resource=f"task:{task.id}").order_by(AuditLog.created_at, AuditLog.id).all()
    return [row.action for row in rows]


def execute(service: TaskAssignmentService, task: Task, agent_id: str, *, success=True, attempt=1, correlation="c-1"):
    return service.record_execution(
        task,
        executing_agent_id=agent_id,
        success=success,
        duration_ms=1.5,
        started_at=NOW,
        completed_at=NOW + datetime.timedelta(milliseconds=2),
        attempt=attempt,
        correlation_id=correlation,
    )


# --- asignar ----------------------------------------------------------------------------------------------------------


def test_assigning_an_existing_agent_sets_it_and_audits_the_assignment(db, service):
    task = make_task(db)

    changed = service.assign(
        task, "agent-product-1", actor="ceo", reason="selected by capability", correlation_id="c-1"
    )

    assert changed is True
    assert task.assigned_agent_id == "agent-product-1"
    assert audit_actions(db, task) == ["task.assigned"]
    event = db.query(AuditLog).filter_by(action="task.assigned").one()
    assert (event.actor, event.before) == ("ceo", None)
    assert event.after["agent_id"] == "agent-product-1"
    assert event.after["reason"] == "selected by capability"
    assert event.correlation_id == "c-1"


def test_assigning_the_same_agent_again_is_a_no_op_with_no_new_event(db, service):
    task = make_task(db)
    service.assign(task, "agent-product-1", actor="ceo", reason="r", correlation_id="c-1")

    assert service.assign(task, "agent-product-1", actor="ceo", reason="r", correlation_id="c-1") is False

    assert audit_actions(db, task) == ["task.assigned"]


def test_B_an_agent_that_does_not_exist_cannot_be_assigned_and_nothing_is_written(db, service):
    task = make_task(db)

    with pytest.raises(ValidationError, match="agent-ghost-9"):
        service.assign(task, "agent-ghost-9", actor="ceo", reason="r", correlation_id="c-1")

    assert task.assigned_agent_id is None
    assert audit_actions(db, task) == []


def test_an_agent_id_is_not_a_free_string_near_misses_are_rejected(db, service):
    task = make_task(db)
    for bad in ("", "Agent-Product-1", "agent-product", " agent-product-1", "agent-product-1 "):
        with pytest.raises(ValidationError):
            service.assign(task, bad, actor="ceo", reason="r", correlation_id="c-1")
    assert task.assigned_agent_id is None


def test_a_task_the_orchestrator_owns_cannot_be_given_to_an_agent(db, service):
    task = make_task(db, capability="decision_synthesis", name="decision_synthesis")

    with pytest.raises(ValidationError, match="orchestrator"):
        service.assign(task, "agent-product-1", actor="ceo", reason="r", correlation_id="c-1")

    assert task.assigned_agent_id is None


def test_assigning_a_different_agent_to_an_assigned_task_is_not_allowed_it_has_to_be_a_reassignment(db, service):
    task = make_task(db)
    service.assign(task, "agent-product-1", actor="ceo", reason="r", correlation_id="c-1")

    with pytest.raises(ValidationError, match="reassign"):
        service.assign(task, "agent-product-2", actor="ceo", reason="r", correlation_id="c-1")

    assert task.assigned_agent_id == "agent-product-1"


# --- H · reasignar ----------------------------------------------------------------------------------------------------


def test_H_a_reassignment_keeps_the_previous_assignment_in_the_history(db, service):
    task = make_task(db)
    service.assign(task, "agent-product-1", actor="ceo", reason="selected", correlation_id="c-1")

    service.reassign(task, "agent-product-2", actor="ceo", reason="assigned agent not routable", correlation_id="c-1")

    assert task.assigned_agent_id == "agent-product-2"
    assert audit_actions(db, task) == ["task.assigned", "task.reassigned"]
    history = service.history(task.id)
    assert [(item.kind, item.before_agent_id, item.agent_id) for item in history] == [
        ("assigned", None, "agent-product-1"),
        ("reassigned", "agent-product-1", "agent-product-2"),
    ]
    assert history[1].reason == "assigned agent not routable"


def test_H2_several_reassignments_all_stay_in_order(db, service):
    task = make_task(db)
    service.assign(task, "agent-product-1", actor="ceo", reason="r", correlation_id="c-1")
    service.reassign(task, "agent-product-2", actor="ceo", reason="r1", correlation_id="c-1")
    service.reassign(task, "agent-product-1", actor="ceo", reason="r2", correlation_id="c-1")

    assert [item.agent_id for item in service.history(task.id)] == [
        "agent-product-1",
        "agent-product-2",
        "agent-product-1",
    ]


def test_a_reassignment_needs_a_current_assignment_a_different_agent_and_an_existing_one(db, service):
    unassigned = make_task(db)
    with pytest.raises(ValidationError, match="not assigned"):
        service.reassign(unassigned, "agent-product-2", actor="ceo", reason="r", correlation_id="c-1")

    task = make_task(db)
    service.assign(task, "agent-product-1", actor="ceo", reason="r", correlation_id="c-1")
    with pytest.raises(ValidationError, match="same agent"):
        service.reassign(task, "agent-product-1", actor="ceo", reason="r", correlation_id="c-1")
    with pytest.raises(ValidationError, match="agent-ghost-9"):
        service.reassign(task, "agent-ghost-9", actor="ceo", reason="r", correlation_id="c-1")

    assert task.assigned_agent_id == "agent-product-1"
    assert audit_actions(db, task) == ["task.assigned"]


def test_the_history_of_one_task_does_not_mix_in_another_task(db, service):
    one, other = make_task(db), make_task(db)
    service.assign(one, "agent-product-1", actor="ceo", reason="r", correlation_id="c-1")
    service.assign(other, "agent-supplier-1", actor="ceo", reason="r", correlation_id="c-1")

    assert [item.agent_id for item in service.history(one.id)] == ["agent-product-1"]
    assert [item.agent_id for item in service.history(other.id)] == ["agent-supplier-1"]


# --- ejecutar: asignación ≠ ejecución ---------------------------------------------------------------------------------


def test_D_an_execution_by_the_assigned_agent_is_linked_to_the_task_with_a_snapshot_of_the_assignment(db, service):
    task = make_task(db)
    service.assign(task, "agent-product-1", actor="ceo", reason="r", correlation_id="c-1")

    row = execute(service, task, "agent-product-1", attempt=1)

    assert isinstance(row, AgentExecutionLog)
    assert (row.task_id, row.agent_id, row.assigned_agent_id, row.attempt, row.success) == (
        task.id,
        "agent-product-1",
        "agent-product-1",
        1,
        True,
    )
    assert row.capability == task.capability
    assert row.correlation_id == "c-1"
    assert (row.started_at, row.completed_at) == (NOW, NOW + datetime.timedelta(milliseconds=2))
    assert "task.executed_by_other_agent" not in audit_actions(db, task)


def test_E_an_execution_by_a_different_agent_is_recorded_as_it_happened_and_audited_as_a_deviation(db, service):
    task = make_task(db)
    service.assign(task, "agent-product-1", actor="ceo", reason="r", correlation_id="c-1")

    row = execute(service, task, "agent-supplier-1")

    assert (row.agent_id, row.assigned_agent_id) == ("agent-supplier-1", "agent-product-1")
    event = db.query(AuditLog).filter_by(action="task.executed_by_other_agent").one()
    assert event.actor == "agent-supplier-1"
    assert event.before == {"assigned_agent_id": "agent-product-1"}
    assert event.after["executing_agent_id"] == "agent-supplier-1"
    assert event.resource == f"task:{task.id}"


def test_an_execution_of_a_task_with_no_assignment_is_recorded_with_no_snapshot_and_audited_as_a_deviation(db, service):
    task = make_task(db)

    row = execute(service, task, "agent-product-1")

    assert row.assigned_agent_id is None
    assert task.assigned_agent_id is None, "ejecutar no asigna"
    assert "task.executed_by_other_agent" in audit_actions(db, task)


def test_F_retries_by_the_same_agent_add_rows_and_never_overwrite_the_previous_one(db, service):
    task = make_task(db)
    service.assign(task, "agent-product-1", actor="ceo", reason="r", correlation_id="c-1")

    first = execute(service, task, "agent-product-1", success=False, attempt=1)
    second = execute(service, task, "agent-product-1", success=True, attempt=2)
    db.flush()

    assert first.id != second.id
    rows = db.query(AgentExecutionLog).filter_by(task_id=task.id).order_by(AgentExecutionLog.attempt).all()
    assert [(row.attempt, row.success) for row in rows] == [(1, False), (2, True)]


def test_G_a_retry_by_another_agent_after_a_reassignment_keeps_both_executions_and_each_snapshot(db, service):
    task = make_task(db)
    service.assign(task, "agent-product-1", actor="ceo", reason="r", correlation_id="c-1")
    execute(service, task, "agent-product-1", success=False, attempt=1)
    service.reassign(task, "agent-product-2", actor="ceo", reason="not routable", correlation_id="c-1")
    execute(service, task, "agent-product-2", success=True, attempt=2)
    db.flush()

    rows = db.query(AgentExecutionLog).filter_by(task_id=task.id).order_by(AgentExecutionLog.attempt).all()
    assert [(row.agent_id, row.assigned_agent_id) for row in rows] == [
        ("agent-product-1", "agent-product-1"),
        ("agent-product-2", "agent-product-2"),
    ]
    assert [item.agent_id for item in service.history(task.id)] == ["agent-product-1", "agent-product-2"]


def test_I_an_execution_needs_a_task_that_exists_in_the_database(db, service):
    ghost = Task(
        project_id="p-1", name="x", capability="market_validation", status="PENDING"
    )  # nunca añadida ni confirmada

    with pytest.raises(ValidationError, match="task"):
        execute(service, ghost, "agent-product-1")

    assert db.query(AgentExecutionLog).count() == 0


# --- leer la relación -------------------------------------------------------------------------------------------------


def test_relations_are_read_from_the_persisted_data_one_entry_per_task(db, service):
    matched = make_task(db, name="product_validation")
    deviated = make_task(db, capability="supplier_sourcing", name="supplier_sourcing", project_id=matched.project_id)
    waiting = make_task(db, capability="legal_validation", name="legal_validation", project_id=matched.project_id)
    synthesis = make_task(
        db,
        capability="decision_synthesis",
        name="decision_synthesis",
        status="COMPLETED",
        project_id=matched.project_id,
    )
    service.assign(matched, "agent-product-1", actor="ceo", reason="r", correlation_id="c-1")
    service.assign(deviated, "agent-supplier-1", actor="ceo", reason="r", correlation_id="c-1")
    service.assign(waiting, "agent-product-2", actor="ceo", reason="r", correlation_id="c-1")
    execute(service, matched, "agent-product-1")
    execute(service, deviated, "agent-product-2")
    matched.status = deviated.status = "COMPLETED"
    db.commit()

    relations = load_relations(db, [matched, deviated, waiting, synthesis], KNOWN)

    assert relations[matched.id].status is AssignmentStatus.MATCH
    assert relations[deviated.id].status is AssignmentStatus.MISMATCH
    assert relations[deviated.id].executed_by_agent_id == "agent-product-2"
    assert relations[waiting.id].status is AssignmentStatus.ASSIGNED
    assert relations[synthesis.id].status is AssignmentStatus.ORCHESTRATOR


def test_relations_report_a_reassignment_from_the_audit_history(db, service):
    task = make_task(db)
    service.assign(task, "agent-product-1", actor="ceo", reason="r", correlation_id="c-1")
    service.reassign(task, "agent-product-2", actor="ceo", reason="r", correlation_id="c-1")
    db.commit()

    relation = load_relations(db, [task], KNOWN)[task.id]

    assert relation.reassigned is True
    assert relation.assigned_agent_id == "agent-product-2"


def test_J_a_completed_agent_task_with_no_execution_is_read_as_an_inconsistency(db):
    task = make_task(db, status="COMPLETED")
    db.commit()

    assert load_relations(db, [task], KNOWN)[task.id].status is AssignmentStatus.INCONSISTENT


def test_historical_tasks_are_read_from_their_audit_event_never_assigned_after_the_fact(db):
    """Las misiones anteriores a este commit: sin asignación, con un `task.completed` cuyo actor es el agente y cuyo
    recurso es la tarea."""
    task = make_task(db, status="COMPLETED")
    db.add(
        AuditLog(
            actor="agent-product-1",
            action="task.completed",
            resource=f"task:{task.id}",
            before=None,
            after={"recommendation": "GO"},
            correlation_id="c-old",
        )
    )
    db.commit()

    relation = load_relations(db, [task], KNOWN)[task.id]

    assert relation.status is AssignmentStatus.EXECUTED_UNASSIGNED
    assert relation.assigned_agent_id is None
    assert relation.executed_by_agent_id == "agent-product-1"
    assert task.assigned_agent_id is None, "leer no escribe"
    assert [item.source for item in relation.executions] == ["audit"]


def test_N_ambiguous_history_is_left_unassigned_not_guessed(db):
    """Una tarea ejecutada de la que no consta ningún evento propio: ni se asigna ni se le atribuye el agente de otra
    tarea de la capacidad."""
    other = make_task(db, status="COMPLETED")
    lonely = make_task(db, status="COMPLETED", project_id=other.project_id)
    db.add(
        AuditLog(
            actor="agent-product-1",
            action="task.completed",
            resource=f"task:{other.id}",
            before=None,
            after=None,
            correlation_id="c-old",
        )
    )
    db.commit()

    relations = load_relations(db, [other, lonely], KNOWN)

    assert relations[other.id].executed_by_agent_id == "agent-product-1"
    assert relations[lonely.id].executed_by_agent_id is None
    assert relations[lonely.id].status is AssignmentStatus.INCONSISTENT


def test_M_an_execution_row_without_a_task_link_is_never_attached_to_a_task_by_coincidence(db):
    """Misma capacidad, mismo agente y misma correlación que la tarea, pero sin `task_id`: no se vincula."""
    task = make_task(db, status="COMPLETED")
    db.add(
        AgentExecutionLog(
            agent_id="agent-product-1",
            capability=task.capability,
            duration_ms=1.0,
            success=True,
            correlation_id="c-same",
        )
    )
    db.add(
        AuditLog(
            actor="ceo",
            action="tasks.created",
            resource=f"project:{task.project_id}",
            before=None,
            after=None,
            correlation_id="c-same",
        )
    )
    db.commit()

    relation = load_relations(db, [task], KNOWN)[task.id]

    assert relation.executions == ()
    assert relation.status is AssignmentStatus.INCONSISTENT


def test_an_audit_event_of_another_task_with_the_same_agent_is_not_attached(db):
    task = make_task(db, status="COMPLETED")
    other = make_task(db, status="COMPLETED", project_id=task.project_id)
    db.add(
        AuditLog(
            actor="agent-product-1",
            action="task.completed",
            resource=f"task:{other.id}",
            before=None,
            after=None,
            correlation_id="c-1",
        )
    )
    db.commit()

    assert load_relations(db, [task], KNOWN)[task.id].executed_by_agent_id is None


def test_the_execution_log_wins_over_the_audit_for_the_same_task_no_double_counting(db, service):
    task = make_task(db)
    service.assign(task, "agent-product-1", actor="ceo", reason="r", correlation_id="c-1")
    execute(service, task, "agent-product-1")
    db.add(
        AuditLog(
            actor="agent-product-1",
            action="task.completed",
            resource=f"task:{task.id}",
            before=None,
            after=None,
            correlation_id="c-1",
        )
    )
    task.status = "COMPLETED"
    db.commit()

    relation = load_relations(db, [task], KNOWN)[task.id]

    assert [item.source for item in relation.executions] == ["execution_log"]
    assert relation.status is AssignmentStatus.MATCH


def test_an_empty_list_of_tasks_reads_nothing(db):
    assert load_relations(db, [], KNOWN) == {}
