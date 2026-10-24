"""Reanudar una misión después de recuperar tareas (M50, Commit 9).

REANUDAR ≠ CREAR UNA MISIÓN NUEVA. `CEOOrchestrator.resume_project` continúa el MISMO objetivo y el MISMO proyecto,
con la misma correlación: ejecuta solo lo pendiente y desbloqueable, no repite ninguna tarea COMPLETED, ejecuta la
síntesis al final y escribe una decisión NUEVA. La decisión anterior queda como estaba (nunca se actualiza). Cada
prueba parte de una misión incompleta REAL (el orquestador, agentes guionizados y el reintento de Commit 8)."""

import pytest
from mission_test_support import (
    P1,
    SPECIALISTS,
    FlakyFinance,
    counts,
    incomplete_mission,
    recovered_mission,
)
from recovery_test_support import CONTEXT
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.budgets.service import BudgetLedgerService
from app.ceo.orchestrator import CEOOrchestrator
from app.core.errors import AuthorityError, ConflictError, NotFoundError
from app.db.base import Base
from app.db.models.approval import Approval
from app.db.models.budget import FinancialEvent
from app.db.models.decision import DecisionEvidence
from app.db.models.task import Task

SPEND_CONTEXT = {
    **CONTEXT,
    "requests_simulated_spend": True,
    "spend_action": "launch_marketing_campaign",
    "spend_amount": 150.0,
}


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


def snapshot(decision) -> tuple:
    return (
        decision.id,
        decision.project_id,
        decision.status,
        decision.opportunity_score,
        decision.confidence,
        decision.rationale,
        decision.correlation_id,
        decision.created_at,
        decision.updated_at,
    )


# A. una misión incompleta y recuperada continúa


def test_A_a_recovered_incomplete_mission_is_resumed_to_the_end(db: Session):
    mission = recovered_mission(db)
    assert mission.statuses() == {
        "product_validation": "COMPLETED",
        "supplier_sourcing": "PENDING",
        "legal_validation": "PENDING",
        "finance_validation": "BLOCKED",
        "decision_synthesis": "BLOCKED",
    }

    decision = mission.resume()

    assert set(mission.statuses().values()) == {"COMPLETED"}
    assert decision.status != "REVIEW"
    assert not (decision.rationale or "").startswith("incomplete_mission")
    assert mission.project.status in {"APPROVED", "VALIDATING", "REJECTED"}


# B. las tareas COMPLETED no se repiten


def test_B_completed_tasks_are_not_executed_again(db: Session):
    mission = recovered_mission(db)
    before = [(r.id, r.attempt, r.success) for r in mission.executions("product_validation")]
    calls = mission.product.calls

    mission.resume()

    assert mission.product.calls == calls == 2  # el intento fallido y el reintento: ninguno más
    assert [(r.id, r.attempt, r.success) for r in mission.executions("product_validation")] == before
    for name in ("supplier_sourcing", "legal_validation", "finance_validation"):
        assert [(r.attempt, r.success) for r in mission.executions(name)] == [(1, True)]


# C. una tarea BLOQUEADA se desbloquea cuando su dependencia está completa y entonces se ejecuta


def test_C_a_blocked_task_is_released_when_its_dependencies_complete_and_then_runs(db: Session):
    mission = recovered_mission(db)
    assert mission.task("finance_validation").status == "BLOCKED"

    mission.resume()

    finance_id = mission.task("finance_validation").id
    released = [e for e in mission.audit("task.unblocked") if e.resource == f"task:{finance_id}"]
    assert [e.after["reason"] for e in released] == ["dependencies_completed"]
    assert mission.task("finance_validation").status == "COMPLETED"
    # y el orden de ejecución respeta el grafo: finanzas, después de producto y proveedor
    order = [entry["agent_id"] for entry in mission.manager.execution_log]
    assert order.index("agent-supplier-1") < order.index("agent-finance-1")


def test_a_blocked_task_left_behind_with_its_dependencies_complete_is_released_when_resuming(db: Session):
    """Un estado que dejó otra versión: BLOQUEADA, con todas sus dependencias ya completadas. Ni el reintento ni la
    pasada la liberan (su dependencia no se completa ahora): la libera el inicio de la reanudación."""
    mission = recovered_mission(db)
    legal = mission.task("legal_validation")
    legal.status = "BLOCKED"
    db.commit()

    mission.resume()

    assert mission.task("legal_validation").status == "COMPLETED"
    released = [e for e in mission.audit("task.unblocked") if e.resource == f"task:{legal.id}"]
    # una vez al recuperar la tarea de producto (Commit 8) y otra, ahora, al reanudar
    assert [e.after["reason"] for e in released] == ["dependencies_completed", "dependencies_completed"]
    assert mission.audit("mission.resume_started")[0].after["unblocked"] == ["legal_validation"]


# D. la síntesis se ejecuta SOLO al final, cuando todas las requeridas están completas


def test_D_synthesis_runs_only_when_every_required_task_is_completed(db: Session):
    mission = recovered_mission(db, overrides={"agent-finance-1": FlakyFinance(failures=1)})

    decision = mission.resume()  # finanzas falla en este intento

    assert mission.task("finance_validation").status == "FAILED"
    assert mission.task("decision_synthesis").status == "BLOCKED"
    assert mission.task("decision_synthesis").output is None  # no se ejecutó, no hay resultado inventado
    assert decision.status == "REVIEW"
    assert "finance_validation(FAILED)" in (decision.rationale or "")


def test_D2_synthesis_completes_after_all_four_specialists(db: Session):
    mission = recovered_mission(db)

    mission.resume()

    assert mission.task("decision_synthesis").status == "COMPLETED"
    assert mission.task("decision_synthesis").output == {"synthesized": True}
    assert mission.executions("decision_synthesis") == []  # es del orquestador: sin agente ni ejecución


# E. la decisión anterior permanece


def test_E_the_previous_decision_is_never_rewritten(db: Session):
    mission = recovered_mission(db)
    before = snapshot(mission.latest())
    evidence_before = sorted(
        (e.source, e.summary) for e in db.query(DecisionEvidence).filter_by(decision_id=mission.latest().id).all()
    )

    mission.resume()

    first = next(d for d in mission.decisions() if d.id == before[0])
    assert snapshot(first) == before  # ni un campo, ni `updated_at`: no hubo UPDATE
    assert first.status == "REVIEW"
    assert first.rationale.startswith("incomplete_mission")
    assert (
        sorted((e.source, e.summary) for e in db.query(DecisionEvidence).filter_by(decision_id=first.id).all())
        == evidence_before
    )


# F / V. se crea una decisión NUEVA, con id propio, en el mismo proyecto y con la misma correlación


def test_F_a_new_decision_is_created_in_the_same_project_with_the_same_correlation(db: Session):
    mission = recovered_mission(db)
    old = mission.latest()

    new = mission.resume()

    decisions = mission.decisions()
    assert [d.id for d in decisions] == [old.id, new.id]
    assert new.id != old.id
    assert new.project_id == old.project_id == mission.project.id
    assert new.correlation_id == old.correlation_id
    assert {e.source for e in db.query(DecisionEvidence).filter_by(decision_id=new.id).all()} == set(SPECIALISTS)


# G. una misión completa no se reanuda


def test_G_a_complete_mission_cannot_be_resumed(db: Session):
    mission = recovered_mission(db)
    mission.resume()
    before = counts(db)

    with pytest.raises(ConflictError, match="complete"):
        mission.resume()

    assert {k: v for k, v in counts(db).items()} == before


def test_G2_a_mission_that_was_never_incomplete_cannot_be_resumed(db: Session):
    mission = incomplete_mission(db, script=(True,))  # todo acierta a la primera
    assert mission.first_decision.status != "REVIEW"
    before = counts(db)

    with pytest.raises(ConflictError, match="complete"):
        mission.resume()

    assert counts(db) == before


# H. con una tarea FAILED sin resolver no se reanuda (reanudar no reintenta)


def test_H_a_failed_task_must_be_recovered_first(db: Session):
    mission = incomplete_mission(db)
    before = counts(db)
    calls = mission.product.calls

    with pytest.raises(ConflictError, match="product_validation"):
        mission.resume()

    assert not db.in_transaction()  # el rechazo confirmó SOLO su evento y soltó el bloqueo
    assert mission.product.calls == calls  # reanudar NO reintentó nada
    assert counts(db) == before
    blocked = mission.audit("mission.resume_blocked")
    assert len(blocked) == 1
    assert blocked[0].after["reason"] == "recovery_pending"
    assert blocked[0].after["blockers"] == [{"task": "product_validation", "reason": "failed_recoverable"}]


# I. un agente desconocido impide reanudar


def test_I_an_unknown_agent_blocks_the_resume(db: Session):
    mission = recovered_mission(db)
    supplier = mission.task("supplier_sourcing")
    supplier.assigned_agent_id = "agent-ghost-9"
    db.commit()
    before = counts(db)

    with pytest.raises(ConflictError, match="supplier_sourcing"):
        mission.resume()

    assert counts(db) == before
    assert mission.audit("mission.resume_blocked")[0].after["blockers"] == [
        {"task": "supplier_sourcing", "reason": "unknown_agent"}
    ]
    assert mission.executions("supplier_sourcing") == []  # no se ejecutó con otro agente


# misiones canceladas o en curso


def test_a_cancelled_task_blocks_the_resume(db: Session):
    mission = recovered_mission(db)
    mission.task("legal_validation").status = "CANCELLED"
    db.commit()

    with pytest.raises(ConflictError, match="cancelled"):
        mission.resume()


def test_a_cancelled_project_blocks_the_resume(db: Session):
    mission = recovered_mission(db)
    mission.project.status = "CANCELLED"
    db.commit()

    with pytest.raises(ConflictError, match="cancelled"):
        mission.resume()


def test_a_running_task_means_the_mission_is_already_being_resumed(db: Session):
    mission = recovered_mission(db)
    mission.task("supplier_sourcing").status = "RUNNING"
    db.commit()

    with pytest.raises(ConflictError, match="running|resum"):
        mission.resume()


# M / N. si una tarea vuelve a fallar a mitad, el historial queda consistente y un segundo resume continúa


def test_M_a_task_that_fails_again_keeps_the_completed_work_and_records_an_incomplete_decision(db: Session):
    mission = recovered_mission(db, overrides={"agent-finance-1": FlakyFinance(failures=1)})
    old = mission.latest()
    new = mission.resume()

    statuses = mission.statuses()
    assert statuses["finance_validation"] == "FAILED"
    assert statuses["decision_synthesis"] == "BLOCKED"
    assert {n: statuses[n] for n in ("product_validation", "supplier_sourcing", "legal_validation")} == {
        "product_validation": "COMPLETED",
        "supplier_sourcing": "COMPLETED",
        "legal_validation": "COMPLETED",
    }
    assert len(mission.executions("supplier_sourcing")) == 1  # lo completado en esta reanudación se conserva
    assert new.status == "REVIEW"
    assert new.rationale.startswith("incomplete_mission")
    assert [d.id for d in mission.decisions()] == [old.id, new.id]
    failed = mission.audit("mission.resume_failed")
    assert len(failed) == 1
    assert failed[0].after["outcome"] == "incomplete"
    assert failed[0].after["failed_tasks"] == {"finance_validation": "FAILED"}
    assert failed[0].after["decision_id"] == new.id
    assert mission.audit("mission.resume_completed") == []


def test_N_a_second_resume_continues_where_the_first_one_stopped(db: Session):
    mission = recovered_mission(db, overrides={"agent-finance-1": FlakyFinance(failures=1)})
    mission.resume()  # finanzas falla
    mission.retry("finance_validation", after_attempt=1)  # Commit 8: recuperación explícita
    assert mission.task("decision_synthesis").status == "PENDING"
    executions_before = {n: len(mission.executions(n)) for n in SPECIALISTS}

    final = mission.resume()

    assert final.status != "REVIEW"
    assert set(mission.statuses().values()) == {"COMPLETED"}
    assert {n: len(mission.executions(n)) for n in SPECIALISTS} == executions_before  # solo la síntesis corrió
    completed = mission.audit("mission.resume_completed")
    assert len(completed) == 1
    assert completed[0].after["executed_tasks"] == ["decision_synthesis"]
    assert len(mission.decisions()) == 3  # v1 incompleta, v2 incompleta, v3 definitiva


def test_M2_an_unexpected_error_rolls_back_everything_and_leaves_a_failure_record(db: Session, monkeypatch):
    mission = recovered_mission(db)
    before_counts = counts(db)
    before_statuses = mission.statuses()

    def boom(*args, **kwargs):
        raise RuntimeError("secret-looking detail that must not be stored")

    monkeypatch.setattr(CEOOrchestrator, "_synthesize_decision", boom)
    with pytest.raises(RuntimeError):
        mission.resume()
    monkeypatch.undo()

    assert mission.statuses() == before_statuses
    assert counts(db) == before_counts
    failed = mission.audit("mission.resume_failed")
    assert len(failed) == 1
    assert failed[0].after["error_class"] == "RuntimeError"
    assert "secret" not in str(failed[0].after)
    # y se puede reanudar después, desde el mismo punto
    assert mission.resume().status != "REVIEW"


# O / P / Q. nada se duplica


def test_O_P_Q_nothing_is_duplicated(db: Session):
    mission = recovered_mission(db)
    before = counts(db)

    mission.resume()

    after = counts(db)
    delta = {k: after[k] - before[k] for k in before}
    assert delta == {
        "objectives": 0,
        "projects": 0,
        "tasks": 0,
        "task_dependencies": 0,
        "executions": 3,  # proveedor, legal y finanzas: lo pendiente. Ni producto ni la síntesis
        "decisions": 1,
        "evidence": 4,
        "approvals": 0,
        "financial_events": 0,
    }
    assert db.query(Task).filter_by(name="decision_synthesis").count() == 1


# R / S. aprobaciones y presupuesto


def test_R_S_a_new_decision_that_needs_approval_gets_its_own_approval_and_one_reserve(db: Session):
    BudgetLedgerService(db).authorise_budget(hard_limit=100_000.0, actor="owner@amazona.local")
    mission = recovered_mission(db, context=SPEND_CONTEXT)
    old = mission.latest()
    assert db.query(Approval).count() == 0 and db.query(FinancialEvent).count() == 0

    new = mission.resume()

    assert new.status == "HUMAN_APPROVAL"
    approvals = db.query(Approval).all()
    assert [a.decision_id for a in approvals] == [new.id]  # la anterior no tenía ni se le inventa una
    assert db.query(Approval).filter_by(decision_id=old.id).count() == 0
    events = db.query(FinancialEvent).all()
    assert [(e.type, e.reference) for e in events] == [("RESERVE", f"approval:{approvals[0].id}")]


def test_R2_repeating_the_resume_does_not_create_a_second_approval_or_reserve(db: Session):
    BudgetLedgerService(db).authorise_budget(hard_limit=100_000.0, actor="owner@amazona.local")
    mission = recovered_mission(db, context=SPEND_CONTEXT)
    old_id = mission.latest().id
    mission.resume()

    with pytest.raises(ConflictError):
        mission.resume(after_decision_id=old_id)  # la misma petición, repetida

    assert db.query(Approval).count() == 1
    assert db.query(FinancialEvent).count() == 1


def test_S_a_resume_without_spend_writes_no_budget_event(db: Session):
    BudgetLedgerService(db).authorise_budget(hard_limit=100_000.0, actor="owner@amazona.local")
    mission = recovered_mission(db)
    events = db.query(FinancialEvent).count()

    mission.resume()

    assert db.query(FinancialEvent).count() == events == 0


# T / U. la correlación se conserva y las ejecuciones nuevas son filas nuevas


def test_T_the_correlation_id_of_the_mission_is_kept_everywhere(db: Session):
    mission = recovered_mission(db)
    correlation = mission.first_decision.correlation_id

    new = mission.resume()

    assert new.correlation_id == correlation
    for name in ("supplier_sourcing", "legal_validation", "finance_validation"):
        assert {r.correlation_id for r in mission.executions(name)} == {correlation}
    for action in ("mission.resume_requested", "mission.resume_started", "mission.resume_completed"):
        assert [e.correlation_id for e in mission.audit(action)] == [correlation]


def test_U_new_executions_are_new_rows_and_old_ones_are_untouched(db: Session):
    mission = recovered_mission(db)
    old = {r.id: (r.task_id, r.attempt, r.success, r.created_at) for r in mission.executions("product_validation")}

    mission.resume()

    now = {r.id: (r.task_id, r.attempt, r.success, r.created_at) for r in mission.executions("product_validation")}
    assert now == old  # la ejecución completada no se reutiliza ni se toca
    ids = {r.id for n in SPECIALISTS for r in mission.executions(n)}
    assert len(ids) == 5  # producto x2 (fallo, reintento) + proveedor + legal + finanzas
    assert [r.attempt for r in mission.executions("supplier_sourcing")] == [1]


# auditoría


def test_the_audit_trail_answers_what_failed_what_was_recovered_and_what_decision_followed(db: Session):
    mission = recovered_mission(db)
    old = mission.latest()

    new = mission.resume(actor="owner-1")

    requested = mission.audit("mission.resume_requested")[0]
    assert requested.actor == "owner-1"
    assert requested.resource == f"project:{mission.project.id}"
    assert requested.after["objective_id"] == mission.objective.id
    assert requested.after["after_decision_id"] == old.id
    assert requested.after["pending_tasks"] == [
        "supplier_sourcing",
        "legal_validation",
        "finance_validation",
        "decision_synthesis",
    ]
    started = mission.audit("mission.resume_started")[0]
    assert started.after["objective_id"] == mission.objective.id
    assert started.after["pending_tasks"] == requested.after["pending_tasks"]
    completed = mission.audit("mission.resume_completed")[0]
    assert completed.after["previous_decision_id"] == old.id
    assert completed.after["previous_status"] == "REVIEW"
    assert completed.after["decision_id"] == new.id
    assert completed.after["decision_status"] == new.status
    assert completed.after["outcome"] == "complete"
    assert sorted(completed.after["executed_tasks"]) == sorted(
        ["supplier_sourcing", "legal_validation", "finance_validation", "decision_synthesis"]
    )
    for event in (requested, started, completed):
        assert "password" not in str(event.after).lower()


# contrato de la petición


def test_an_agent_cannot_resume_a_mission(db: Session):
    mission = recovered_mission(db)

    with pytest.raises(AuthorityError):
        mission.resume(actor=P1)
    with pytest.raises(AuthorityError):
        mission.resume(actor="  ")


def test_a_stale_decision_id_is_rejected_and_nothing_runs(db: Session):
    mission = recovered_mission(db)
    before = counts(db)

    with pytest.raises(ConflictError, match="stale"):
        mission.resume(after_decision_id="00000000-0000-0000-0000-000000000000")

    assert not db.in_transaction()
    assert counts(db) == before
    assert mission.audit("mission.resume_blocked")[0].after["reason"] == "stale_decision"


def test_an_unknown_project_is_not_found(db: Session):
    mission = recovered_mission(db)

    with pytest.raises(NotFoundError):
        CEOOrchestrator(db, agent_manager=mission.manager).resume_project(
            "no-such-project", actor="ceo", after_decision_id=mission.latest().id
        )
