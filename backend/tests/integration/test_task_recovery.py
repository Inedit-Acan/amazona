"""Recuperación de tareas: reintento, reasignación, desviación, agente desconocido y dependencias (M49, Commit 8).

Cada prueba parte de una misión REAL ejecutada por el orquestador con agentes guionizados (`recovery_test_support`),
de modo que el estado inicial (una tarea FAILED con sus intentos en el log, sus dependientes BLOCKED…) es el que el
sistema produce. El historial es de solo añadir: ningún intento se sobrescribe y una reasignación conserva la
asignación anterior en la auditoría."""

import pytest
from recovery_test_support import (
    AlwaysFails,
    Scripted,
    audit_actions,
    build_manager,
    executions_of,
    run_mission,
    tasks_by_name,
)
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.ceo.orchestrator import CEOOrchestrator
from app.core.errors import AuthorityError, ConflictError, NotFoundError, ValidationError
from app.db.base import Base
from app.db.models.agent_execution_log import AgentExecutionLog
from app.db.models.task import Task, TaskDependency
from app.tasks.assignment import AssignmentStatus, TaskAssignmentService, load_relations
from app.tasks.recovery import RecoveryKind, TaskRecoveryService, describe_recovery

P1, P2 = "agent-product-1", "agent-product-2"


@pytest.fixture()
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def failed_product(db: Session, script, *, max_task_retries: int, second: Scripted | None = None):
    """Una misión en la que el agente de producto sigue `script`. Devuelve (manager, decision, product_task)."""
    first = Scripted(script)
    agents = {P1: first, **({P2: second} if second is not None else {})}
    _, manager = build_manager(agents)
    decision = run_mission(db, manager, max_task_retries=max_task_retries)
    return manager, decision, tasks_by_name(db)["product_validation"]


def rows(db: Session, task: Task):
    return [(r.attempt, r.agent_id, r.assigned_agent_id, r.success) for r in executions_of(db, task)]


# A. un intento que falla deja la tarea FAILED y el hecho a la vista


def test_A_a_failed_first_attempt_leaves_the_task_failed_with_its_attempt_recorded(db):
    _, _, task = failed_product(db, [False], max_task_retries=0)

    assert task.status == "FAILED"
    assert "simulated failure #1" in (task.error or "")
    assert rows(db, task) == [(1, P1, P1, False)]
    assert [e.after["attempt"] for e in audit_actions(db, task, action="task.execution_started")] == [1]
    failed = audit_actions(db, task, action="task.execution_failed")
    assert [(e.actor, e.after["attempt"], e.after["agent_id"]) for e in failed] == [(P1, 1, P1)]


# B / C. el reintento: mismo agente, intento siguiente; y puede completar


def test_B_a_retry_is_the_next_attempt_by_the_same_assigned_agent_with_a_new_execution(db):
    manager, _, task = failed_product(db, [False, True], max_task_retries=0)
    before = rows(db, task)
    old_ids = {r.id for r in executions_of(db, task)}

    TaskRecoveryService(db, manager).retry(task.id, actor="ceo", after_attempt=1, reason="transient")
    db.commit()

    after = rows(db, task)
    assert before == [(1, P1, P1, False)]
    assert after == [(1, P1, P1, False), (2, P1, P1, True)]
    assert task.assigned_agent_id == P1  # un retry NO cambia la asignación
    new = [r for r in executions_of(db, task) if r.id not in old_ids]
    assert len(new) == 1
    requested = audit_actions(db, task, action="task.retry_requested")
    started = audit_actions(db, task, action="task.retry_started")
    assert [(e.actor, e.after["after_attempt"], e.after["agent_id"]) for e in requested] == [("ceo", 1, P1)]
    assert [(e.after["attempt"], e.after["agent_id"]) for e in started] == [(2, P1)]
    assert not audit_actions(db, task, action="task.reassigned")


def test_C_a_retry_that_completes_leaves_the_task_completed_and_clears_the_stale_error(db):
    manager, _, task = failed_product(db, [False, True], max_task_retries=0)

    TaskRecoveryService(db, manager).retry(task.id, actor="ceo", after_attempt=1, reason=None)
    db.commit()

    assert task.status == "COMPLETED"
    assert task.output is not None
    assert task.error is None
    assert audit_actions(db, task, action="task.completed")[-1].actor == P1


def test_a_retry_that_fails_again_is_recorded_and_leaves_the_task_failed(db):
    manager, _, task = failed_product(db, [False, False, True], max_task_retries=0)

    TaskRecoveryService(db, manager).retry(task.id, actor="ceo", after_attempt=1, reason=None)
    db.commit()

    assert task.status == "FAILED"
    assert rows(db, task) == [(1, P1, P1, False), (2, P1, P1, False)]
    assert len(audit_actions(db, task, action="task.execution_failed")) == 2


# D / E. dos fallos, reasignación, intento 3 con el agente nuevo; todo el historial sigue


def test_D_two_failures_then_a_reassignment_then_attempt_three_runs_on_the_new_agent(db):
    manager, _, task = failed_product(db, [False, False], max_task_retries=1, second=Scripted([True]))
    assert rows(db, task) == [(1, P1, P1, False), (2, P1, P1, False)]
    service = TaskRecoveryService(db, manager)

    service.reassign(task.id, agent_id=P2, actor="ceo", reason="agent-product-1 keeps failing")
    db.commit()
    assert task.assigned_agent_id == P2
    assert task.status == "FAILED"  # reasignar no ejecuta
    service.retry(task.id, actor="ceo", after_attempt=2, reason=None)
    db.commit()

    assert rows(db, task) == [(1, P1, P1, False), (2, P1, P1, False), (3, P2, P2, True)]
    assert task.status == "COMPLETED"
    event = audit_actions(db, task, action="task.reassigned")[-1]
    assert event.actor == "ceo"
    assert event.before == {"agent_id": P1}
    assert event.after["agent_id"] == P2
    assert event.after["reason"] == "agent-product-1 keeps failing"


def test_E_the_history_keeps_every_attempt_untouched(db):
    manager, _, task = failed_product(db, [False, False], max_task_retries=1, second=Scripted([True]))
    snapshot = {
        r.id: (r.attempt, r.agent_id, r.assigned_agent_id, r.success, r.correlation_id, r.created_at)
        for r in executions_of(db, task)
    }
    service = TaskRecoveryService(db, manager)

    service.reassign(task.id, agent_id=P2, actor="ceo", reason="x")
    service.retry(task.id, actor="ceo", after_attempt=2, reason=None)
    db.commit()

    now = {
        r.id: (r.attempt, r.agent_id, r.assigned_agent_id, r.success, r.correlation_id, r.created_at)
        for r in executions_of(db, task)
    }
    assert len(now) == 3
    assert {k: v for k, v in now.items() if k in snapshot} == snapshot  # las dos primeras, byte a byte
    relation = load_relations(db, [task], manager.agent_ids())[task.id]
    assert relation.reassigned is True
    assert [t.attempt for t in relation.executions] == [1, 2, 3]
    assert relation.status is AssignmentStatus.MATCH


# F / G / H. lo que NO se puede reintentar


def test_F_a_completed_task_cannot_be_retried_and_nothing_is_written(db):
    manager, _, _ = failed_product(db, [], max_task_retries=0)
    task = tasks_by_name(db)["product_validation"]
    assert task.status == "COMPLETED"
    count = db.query(AgentExecutionLog).count()

    with pytest.raises(ConflictError, match="COMPLETED"):
        TaskRecoveryService(db, manager).retry(task.id, actor="ceo", after_attempt=1, reason=None)

    assert db.query(AgentExecutionLog).count() == count
    assert task.status == "COMPLETED"


@pytest.mark.parametrize("name", ["supplier_sourcing", "decision_synthesis"])
def test_G_a_task_with_no_failed_attempt_cannot_be_retried_blocked_or_orchestrator(db, name):
    manager, _, _ = failed_product(db, [False, False, False], max_task_retries=0)
    task = tasks_by_name(db)[name]
    assert task.status == "BLOCKED"

    with pytest.raises((ConflictError, ValidationError)):
        TaskRecoveryService(db, manager).retry(task.id, actor="ceo", after_attempt=1, reason=None)

    assert db.query(AgentExecutionLog).filter_by(task_id=task.id).count() == 0


def test_G2_a_pending_task_that_never_ran_cannot_be_retried(db):
    manager, _, product = failed_product(db, [], max_task_retries=0)
    fresh = Task(
        project_id=product.project_id,
        name="extra",
        capability="market_validation",
        status="PENDING",
        assigned_agent_id=P1,
    )
    db.add(fresh)
    db.commit()

    with pytest.raises(ConflictError, match="FAILED"):
        TaskRecoveryService(db, manager).retry(fresh.id, actor="ceo", after_attempt=1, reason=None)


def test_H_an_agent_that_used_its_attempts_is_refused_and_must_be_reassigned(db):
    manager, _, task = failed_product(db, [False, False, False], max_task_retries=2)
    assert rows(db, task) == [(1, P1, P1, False), (2, P1, P1, False), (3, P1, P1, False)]

    with pytest.raises(ConflictError, match="reassign"):
        TaskRecoveryService(db, manager).retry(task.id, actor="ceo", after_attempt=3, reason=None)

    assert len(rows(db, task)) == 3  # no retry infinito
    recovery = describe_recovery(
        task_status=task.status,
        assigned_agent_id=task.assigned_agent_id,
        known_agent_ids=manager.agent_ids(),
        traces=load_relations(db, [task], manager.agent_ids())[task.id].executions,
        relation_status=AssignmentStatus.MATCH,
    )
    assert recovery.kind is RecoveryKind.REASSIGN_REQUIRED


def test_H2_the_task_total_is_capped_even_across_reassignments(db):
    manager, _, task = failed_product(
        db, [False, False, False], max_task_retries=2, second=Scripted([False, False, False, False])
    )
    service = TaskRecoveryService(db, manager)
    service.reassign(task.id, agent_id=P2, actor="ceo", reason="second agent")
    for after in (3, 4, 5):
        service.retry(task.id, actor="ceo", after_attempt=after, reason=None)
        db.commit()

    assert len(rows(db, task)) == 6
    with pytest.raises(ConflictError, match="limit"):
        service.retry(task.id, actor="ceo", after_attempt=6, reason=None)
    assert len(rows(db, task)) == 6


def test_a_stale_retry_is_refused_it_must_name_the_attempt_it_is_retrying(db):
    manager, _, task = failed_product(db, [False, False, True], max_task_retries=1)
    assert len(rows(db, task)) == 2

    with pytest.raises(ConflictError, match="attempt"):
        TaskRecoveryService(db, manager).retry(task.id, actor="ceo", after_attempt=1, reason=None)

    assert len(rows(db, task)) == 2


def test_a_retry_of_a_task_that_does_not_exist_is_not_found(db):
    _, manager = build_manager({P1: Scripted([])})
    with pytest.raises(NotFoundError):
        TaskRecoveryService(db, manager).retry("no-such-task", actor="ceo", after_attempt=1, reason=None)


def test_a_retry_when_the_assigned_agent_is_not_available_is_refused_without_a_fallback(db):
    from app.agents.base import AgentStatus

    manager, _, task = failed_product(db, [False, True], max_task_retries=0, second=Scripted([]))
    manager._registry.set_status(P1, AgentStatus.DISABLED)

    with pytest.raises(ConflictError, match="not available"):
        TaskRecoveryService(db, manager).retry(task.id, actor="ceo", after_attempt=1, reason=None)

    assert task.assigned_agent_id == P1  # no se pasó a agent-product-2 por la capacidad
    assert len(rows(db, task)) == 1


# I / J. la reasignación solo a agentes del registro y compatibles


def test_I_reassigning_to_an_agent_the_registry_does_not_know_is_refused(db):
    manager, _, task = failed_product(db, [False, False], max_task_retries=1)

    with pytest.raises(ValidationError, match="registry"):
        TaskRecoveryService(db, manager).reassign(task.id, agent_id="agent-ghost-9", actor="ceo", reason="x")

    assert task.assigned_agent_id == P1
    assert not audit_actions(db, task, action="task.reassigned")


def test_J_reassigning_to_an_agent_without_the_capability_is_refused(db):
    manager, _, task = failed_product(db, [False, False], max_task_retries=1)

    with pytest.raises(ValidationError, match="capab"):
        TaskRecoveryService(db, manager).reassign(task.id, agent_id="agent-supplier-1", actor="ceo", reason="x")

    assert task.assigned_agent_id == P1
    assert not audit_actions(db, task, action="task.reassigned")


def test_a_free_text_agent_is_not_an_agent(db):
    manager, _, task = failed_product(db, [False, False], max_task_retries=1)
    for bad in ("", "  ", "Product Validation Agent", "market_validation"):
        with pytest.raises(ValidationError):
            TaskRecoveryService(db, manager).reassign(task.id, agent_id=bad, actor="ceo", reason="x")
    assert task.assigned_agent_id == P1


def test_reassigning_to_the_same_agent_or_a_completed_task_is_refused(db):
    manager, _, task = failed_product(db, [False, False], max_task_retries=1, second=Scripted([]))
    service = TaskRecoveryService(db, manager)
    with pytest.raises(ValidationError, match="same agent|already assigned"):
        service.reassign(task.id, agent_id=P1, actor="ceo", reason="x")

    done = tasks_by_name(db)["decision_synthesis"]  # BLOCKED y del orquestador
    with pytest.raises(ValidationError, match="orchestrator"):
        service.reassign(done.id, agent_id=P1, actor="ceo", reason="x")


def test_reassigning_a_completed_task_is_refused(db):
    manager, _, _ = failed_product(db, [], max_task_retries=0, second=Scripted([]))
    task = tasks_by_name(db)["product_validation"]
    with pytest.raises(ConflictError, match="COMPLETED"):
        TaskRecoveryService(db, manager).reassign(task.id, agent_id=P2, actor="ceo", reason="x")
    assert task.assigned_agent_id == P1


# autoridad: el agente informa, el orquestador decide


@pytest.mark.parametrize("actor", [P1, P2, "agent-supplier-1"])
def test_an_agent_cannot_reassign_or_retry_even_itself(db, actor):
    manager, _, task = failed_product(db, [False, False], max_task_retries=1, second=Scripted([]))
    service = TaskRecoveryService(db, manager)

    with pytest.raises(AuthorityError):
        service.reassign(task.id, agent_id=P2, actor=actor, reason="I would rather not")
    with pytest.raises(AuthorityError):
        service.retry(task.id, actor=actor, after_attempt=2, reason=None)

    assert task.assigned_agent_id == P1
    assert len(rows(db, task)) == 2


@pytest.mark.parametrize("actor", ["", "   "])
def test_an_actor_is_always_required(db, actor):
    manager, _, task = failed_product(db, [False, False], max_task_retries=1, second=Scripted([]))
    with pytest.raises(AuthorityError):
        TaskRecoveryService(db, manager).reassign(task.id, agent_id=P2, actor=actor, reason="x")


# K / L. una desviación se ve y no se convierte en nada


def test_K_an_execution_by_another_agent_is_a_mismatch_and_it_is_audited(db):
    manager, _, task = failed_product(db, [], max_task_retries=0)
    other = Task(
        project_id=task.project_id, name="x", capability="market_validation", status="RUNNING", assigned_agent_id=P1
    )
    db.add(other)
    db.flush()

    TaskAssignmentService(db, manager.agent_ids()).record_execution(
        other,
        executing_agent_id="agent-supplier-1",
        success=True,
        duration_ms=1.0,
        started_at=None,
        completed_at=None,
        attempt=1,
        correlation_id="c-1",
    )
    db.commit()

    relation = load_relations(db, [other], manager.agent_ids())[other.id]
    assert relation.status is AssignmentStatus.MISMATCH
    event = audit_actions(db, other, action="task.executed_by_other_agent")[-1]
    assert event.before == {"assigned_agent_id": P1}
    assert event.after["executing_agent_id"] == "agent-supplier-1"


def test_L_a_mismatch_never_changes_the_assignment_nor_becomes_a_reassignment(db):
    manager, _, task = failed_product(db, [], max_task_retries=0)
    other = Task(
        project_id=task.project_id, name="x", capability="market_validation", status="RUNNING", assigned_agent_id=P1
    )
    db.add(other)
    db.flush()

    TaskAssignmentService(db, manager.agent_ids()).record_execution(
        other,
        executing_agent_id="agent-supplier-1",
        success=True,
        duration_ms=1.0,
        started_at=None,
        completed_at=None,
        attempt=1,
        correlation_id="c-1",
    )
    db.commit()

    assert other.assigned_agent_id == P1
    assert not audit_actions(db, other, action="task.reassigned")
    assert not audit_actions(db, other, action="task.assigned")


# M. un agente desconocido no tiene fallback


def test_M_a_failed_task_whose_agent_is_no_longer_in_the_registry_is_not_retried_by_capability(db):
    manager, _, task = failed_product(db, [False, False], max_task_retries=1, second=Scripted([]))
    manager._registry._agents.pop(P1)  # el registro deja de conocer al agente asignado

    with pytest.raises(ConflictError, match="unknown"):
        TaskRecoveryService(db, manager).retry(task.id, actor="ceo", after_attempt=2, reason=None)

    assert task.assigned_agent_id == P1
    assert len(rows(db, task)) == 2
    relation = load_relations(db, [task], manager.agent_ids())[task.id]
    assert relation.status is AssignmentStatus.UNKNOWN_AGENT


def test_M2_the_orchestrator_blocks_a_task_whose_assigned_agent_vanished_it_does_not_fall_back(db):
    first = Scripted([])
    _, manager = build_manager({P1: first, P2: Scripted([])})
    original = CEOOrchestrator._create_tasks

    def vanish_after_creation(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        manager._registry._agents.pop(P1)
        return result

    CEOOrchestrator._create_tasks = vanish_after_creation  # type: ignore[method-assign]
    try:
        run_mission(db, manager, max_task_retries=1)
    finally:
        CEOOrchestrator._create_tasks = original  # type: ignore[method-assign]

    task = tasks_by_name(db)["product_validation"]
    assert first.calls == 0
    assert task.status == "BLOCKED"
    assert task.assigned_agent_id == P1
    assert executions_of(db, task) == []
    blocked = audit_actions(db, task, action="task.blocked")
    assert [e.after["reason"] for e in blocked] == ["unknown_agent"]
    assert not audit_actions(db, task, action="task.reassigned")
    assert all(t.status == "BLOCKED" for n, t in tasks_by_name(db).items() if n != "product_validation")


def test_M3_reassigning_a_blocked_task_to_a_valid_agent_resolves_it(db):
    first = Scripted([])
    _, manager = build_manager({P1: first, P2: Scripted([])})
    original = CEOOrchestrator._create_tasks

    def vanish_after_creation(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        manager._registry._agents.pop(P1)
        return result

    CEOOrchestrator._create_tasks = vanish_after_creation  # type: ignore[method-assign]
    try:
        run_mission(db, manager, max_task_retries=1)
    finally:
        CEOOrchestrator._create_tasks = original  # type: ignore[method-assign]
    task = tasks_by_name(db)["product_validation"]

    TaskRecoveryService(db, manager).reassign(
        task.id, agent_id=P2, actor="ceo", reason="agent-product-1 left the registry"
    )
    db.commit()

    assert task.assigned_agent_id == P2
    assert task.status == "PENDING"  # desbloqueada, NO ejecutada: reanudar la misión es otra operación
    assert [e.after["agent_id"] for e in audit_actions(db, task, action="task.reassigned")] == [P2]
    assert audit_actions(db, task, action="task.unblocked")


# N / O. dependencias


def test_N_a_failed_dependency_blocks_every_dependent_and_none_of_them_runs(db):
    _, _, product = failed_product(db, [False, False], max_task_retries=1)
    tasks = tasks_by_name(db)

    assert product.status == "FAILED"
    for name in ("supplier_sourcing", "legal_validation", "finance_validation", "decision_synthesis"):
        assert tasks[name].status == "BLOCKED", name
        assert executions_of(db, tasks[name]) == []
        event = audit_actions(db, tasks[name], action="task.blocked")[-1]
        assert event.after["reason"] == "dependency_not_completed"
        assert product.id in event.after["blocked_by"]
    assert not any(t.status == "COMPLETED" for t in tasks.values())


def test_O_a_recovered_dependency_unblocks_what_it_can_and_nothing_more(db):
    manager, _, product = failed_product(db, [False, False, True], max_task_retries=1)
    TaskRecoveryService(db, manager).retry(product.id, actor="ceo", after_attempt=2, reason=None)
    db.commit()
    tasks = tasks_by_name(db)

    assert product.status == "COMPLETED"
    assert tasks["supplier_sourcing"].status == "PENDING"
    assert tasks["legal_validation"].status == "PENDING"
    assert tasks["finance_validation"].status == "BLOCKED"  # depende también de supplier, que aún no se ejecutó
    assert tasks["decision_synthesis"].status == "BLOCKED"
    assert {e.resource for e in audit_actions(db, action="task.unblocked")} == {
        f"task:{tasks['supplier_sourcing'].id}",
        f"task:{tasks['legal_validation'].id}",
    }
    # y no se ejecutó por arrastre
    assert executions_of(db, tasks["supplier_sourcing"]) == []


# P. la decisión no se fabrica


def test_P_a_mission_with_a_required_task_failed_does_not_produce_a_go_nor_invented_evidence(db):
    _, decision, product = failed_product(db, [False, False], max_task_retries=1)

    assert decision.status == "REVIEW"
    assert "incomplete" in decision.rationale
    assert "product_validation" in decision.rationale
    assert "legal_status=CLEAR" not in decision.rationale  # no se inventa un «legal despejado» que nadie comprobó
    from app.db.models.decision import DecisionEvidence
    from app.db.models.project import Project

    assert db.query(DecisionEvidence).filter_by(decision_id=decision.id).count() == 0
    assert db.get(Project, product.project_id).status == "VALIDATING"
    synthesis = tasks_by_name(db)["decision_synthesis"]
    assert synthesis.status == "BLOCKED"
    assert synthesis.assigned_agent_id is None  # sigue siendo del orquestador
    assert executions_of(db, synthesis) == []


def test_P2_one_missing_task_is_enough_even_if_the_others_look_attractive(db):
    _, manager = build_manager({P1: Scripted([])}, overrides={"agent-legal-1": AlwaysFails("legal_validation")})
    decision = run_mission(db, manager, max_task_retries=0)
    tasks = tasks_by_name(db)

    assert tasks["legal_validation"].status == "FAILED"
    assert (
        tasks["product_validation"].status
        == tasks["supplier_sourcing"].status
        == tasks["finance_validation"].status
        == "COMPLETED"
    )
    assert decision.status == "REVIEW"
    assert "legal_validation" in decision.rationale
    assert tasks["decision_synthesis"].status == "BLOCKED"


def test_P3_a_complete_mission_is_unchanged_by_all_this(db):
    _, manager = build_manager({P1: Scripted([])})
    decision = run_mission(db, manager, max_task_retries=1)
    tasks = tasks_by_name(db)

    assert decision.status in {"GO", "HUMAN_APPROVAL"}
    assert "incomplete" not in decision.rationale
    assert all(t.status == "COMPLETED" for t in tasks.values())
    assert not audit_actions(db, action="task.blocked")


# Q / R / S. correlación, ids y numeración


def test_Q_the_mission_correlation_id_never_substitutes_the_task_link(db):
    manager, decision, task = failed_product(db, [False, False], max_task_retries=1)
    stray = AgentExecutionLog(
        agent_id=P1,
        capability="market_validation",
        duration_ms=1.0,
        success=True,
        correlation_id=decision.correlation_id,  # la MISMA correlación, pero sin task_id
        task_id=None,
        attempt=9,
    )
    db.add(stray)
    db.commit()

    assert [r.attempt for r in executions_of(db, task)] == [1, 2]
    relation = load_relations(db, [task], manager.agent_ids())[task.id]
    assert len(relation.executions) == 2
    # y la numeración del siguiente intento no la tiene en cuenta
    TaskRecoveryService(db, manager).retry(task.id, actor="ceo", after_attempt=2, reason=None)
    db.commit()
    assert [r.attempt for r in executions_of(db, task)] == [1, 2, 3]


def test_R_a_retry_keeps_the_mission_correlation_id_but_has_its_own_execution_id(db):
    manager, decision, task = failed_product(db, [False, True], max_task_retries=0)
    first = executions_of(db, task)[0]

    TaskRecoveryService(db, manager).retry(task.id, actor="ceo", after_attempt=1, reason=None)
    db.commit()

    second = executions_of(db, task)[1]
    assert second.id != first.id
    assert second.correlation_id == first.correlation_id == decision.correlation_id
    for action in ("task.retry_requested", "task.retry_started", "task.completed"):
        assert audit_actions(db, task, action=action)[-1].correlation_id == decision.correlation_id


def test_S_the_attempt_number_is_strictly_monotonic_per_task(db):
    manager, _, task = failed_product(
        db, [False, False, False], max_task_retries=2, second=Scripted([False, False, True])
    )
    service = TaskRecoveryService(db, manager)
    service.reassign(task.id, agent_id=P2, actor="ceo", reason="x")
    service.retry(task.id, actor="ceo", after_attempt=3, reason=None)
    db.commit()
    service.retry(task.id, actor="ceo", after_attempt=4, reason=None)
    db.commit()
    service.retry(task.id, actor="ceo", after_attempt=5, reason=None)
    db.commit()

    attempts = [r.attempt for r in executions_of(db, task)]
    assert attempts == [1, 2, 3, 4, 5, 6]
    assert task.status == "COMPLETED"


# eventos: sin ruido ni retroactivos


def test_a_normal_mission_adds_only_the_execution_started_events_to_the_old_audit_trail(db):
    _, manager = build_manager({P1: Scripted([])})
    run_mission(db, manager, max_task_retries=1)

    actions = [e.action for e in audit_actions(db)]
    assert actions.count("task.execution_started") == 4
    for name in (
        "task.execution_failed",
        "task.blocked",
        "task.unblocked",
        "task.retry_requested",
        "task.retry_started",
        "task.reassigned",
    ):
        assert name not in actions, name


def test_an_in_run_retry_keeps_the_legacy_events_and_adds_the_attempt_facts(db):
    _, _, task = failed_product(db, [False, False, False], max_task_retries=2)

    actions = [e.action for e in audit_actions(db, task)]
    assert actions.count("task.execution_started") == 3
    assert actions.count("task.execution_failed") == 3
    assert actions.count("task.retried") == 2
    assert actions.count("task.failed") == 1


# bloqueo en cascada y desbloqueo: sobre un grafo propio, para fijar lo que el plan de producto no distingue


def _chain(db: Session, project_id: str) -> dict[str, Task]:
    """t1 (FAILED) <- t2 <- t3 (PENDING, cadena); t4 (COMPLETED) depende de t1; t5 (RUNNING) de t2; t6 sin relación."""
    names = {
        "t1": "FAILED",
        "t2": "PENDING",
        "t3": "PENDING",
        "t4": "COMPLETED",
        "t5": "RUNNING",
        "t6": "PENDING",
    }
    tasks = {
        n: Task(project_id=project_id, name=n, capability="market_validation", status=st) for n, st in names.items()
    }
    db.add_all(tasks.values())
    db.flush()
    for parent, child in (("t1", "t2"), ("t2", "t3"), ("t1", "t4"), ("t2", "t5")):
        db.add(TaskDependency(parent_task_id=tasks[parent].id, child_task_id=tasks[child].id))
    db.commit()
    return tasks


def test_blocking_cascades_through_the_whole_chain_and_touches_only_pending_dependents(db):
    manager, _, product = failed_product(db, [], max_task_retries=0)
    tasks = _chain(db, product.project_id)

    blocked = TaskRecoveryService(db, manager).block_dependents(tasks["t1"], "corr-x")
    db.commit()

    assert {t.name for t in blocked} == {"t2", "t3"}
    assert [tasks[n].status for n in ("t2", "t3")] == ["BLOCKED", "BLOCKED"]
    assert tasks["t4"].status == "COMPLETED"  # ya terminó: no se toca
    assert tasks["t5"].status == "RUNNING"  # se está ejecutando: no se toca
    assert tasks["t6"].status == "PENDING"  # no depende de nada fallido
    event = audit_actions(db, tasks["t3"], action="task.blocked")[-1]
    assert event.after["blocked_by"] == [tasks["t2"].id]  # t3 espera a t2, que a su vez está bloqueada


def test_unblocking_releases_only_the_children_whose_every_dependency_is_completed(db):
    manager, _, product = failed_product(db, [], max_task_retries=0)
    tasks = _chain(db, product.project_id)
    service = TaskRecoveryService(db, manager)
    service.block_dependents(tasks["t1"], "corr-x")
    tasks["t1"].status = "COMPLETED"  # el padre se recuperó

    released = service.unblock_dependents(tasks["t1"], "corr-x")
    db.commit()

    assert [t.name for t in released] == ["t2"]
    assert tasks["t2"].status == "PENDING"
    assert tasks["t3"].status == "BLOCKED"  # su padre (t2) aún no se completó


def test_a_blocked_task_with_an_unknown_agent_is_not_released_by_its_dependencies(db):
    manager, _, product = failed_product(db, [], max_task_retries=0)
    tasks = _chain(db, product.project_id)
    tasks["t2"].assigned_agent_id = "agent-ghost-9"
    service = TaskRecoveryService(db, manager)
    service.block_dependents(tasks["t1"], "corr-x")
    tasks["t1"].status = "COMPLETED"

    assert service.unblock_dependents(tasks["t1"], "corr-x") == []
    assert tasks["t2"].status == "BLOCKED"  # su agente sigue sin existir: hace falta reasignarla


def test_the_orchestrator_keeps_retrying_inside_a_run_without_an_explicit_request(db):
    """El reintento AUTOMÁTICO sigue existiendo, acotado por la política única: tres intentos del mismo agente."""
    _, _, task = failed_product(db, [False, False, True], max_task_retries=2)

    assert task.status == "COMPLETED"
    assert [r[0] for r in rows(db, task)] == [1, 2, 3]
    assert not audit_actions(db, task, action="task.retry_requested")  # no hubo petición explícita


def test_a_task_that_recovers_inside_the_run_does_not_keep_the_old_error(db):
    _, _, task = failed_product(db, [False, True], max_task_retries=1)

    assert task.status == "COMPLETED"
    assert task.error is None  # el fallo del intento 1 vive en la ejecución y en la auditoría, no en la tarea
    assert executions_of(db, task)[0].success is False
    assert audit_actions(db, task, action="task.execution_failed")[0].after["error"] == "simulated failure #1"
