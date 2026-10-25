"""Confirmar o rechazar lo que el CEO propone (M52): el único camino de una escritura hecha desde el chat.

Las propuestas nacen del servicio de chat (con un modelo falso) sobre misiones REALES del orquestador, y se confirman
con `ActionService`: los mismos
servicios que las rutas de siempre (`TaskRecoveryService`, `CEOOrchestrator`, aprobaciones), que vuelven a validar
todo. Aquí se prueba que se ejecuta UNA
vez, que lo rechazado no se ejecuta, que una propuesta vieja no hace daño y que cada paso queda en la auditoría y
enlazado a la conversación."""

import json

import pytest
from ceo_chat_test_support import OTHER_OWNER, OWNER, ScriptedProvider, call, say
from mission_test_support import P1, counts, incomplete_mission, recovered_mission
from recovery_test_support import Scripted
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.ceo.mission import MissionState, load_mission
from app.ceo_chat.actions import ActionService
from app.ceo_chat.service import CEOChatService
from app.core.config import Settings
from app.core.errors import ConflictError, NotFoundError
from app.db.base import Base
from app.db.models.approval import Approval
from app.db.models.audit import AuditLog
from app.db.models.ceo_chat import CeoActionProposal, CeoMessage
from app.db.models.objective import Objective

SETTINGS = Settings(_env_file=None)


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


def propose(db: Session, mission, tool: str, arguments: dict) -> CeoActionProposal:
    """Una propuesta de verdad: el modelo (falso) la pide y el servicio de chat la crea."""
    chat = CEOChatService(
        db,
        provider=ScriptedProvider([call((tool, arguments)), say("Te propongo esto.")]),
        manager=mission.manager,
        settings=SETTINGS,
    )
    turn = chat.chat(actor=OWNER, text="propón", conversation_id=None)
    assert len(turn.proposals) == 1, [m.structured for m in turn.tool_messages]
    return turn.proposals[0]


def actions(db: Session, mission) -> ActionService:
    return ActionService(db, mission.manager, SETTINGS)


def audits(db: Session, action: str) -> list[AuditLog]:
    db.expire_all()
    return db.query(AuditLog).filter_by(action=action).order_by(AuditLog.created_at, AuditLog.id).all()


def fresh(db: Session, proposal: CeoActionProposal) -> CeoActionProposal:
    db.expire_all()
    return db.get(CeoActionProposal, proposal.id)


# C/E. confirmar ejecuta exactamente una vez


def test_E_confirming_a_retry_runs_one_more_attempt_once_and_links_everything(db):
    mission = incomplete_mission(db)
    proposal = propose(
        db,
        mission,
        "propose_retry_task",
        {"task_id": mission.task("product_validation").id, "after_attempt": 1, "reason": "fallo transitorio"},
    )
    assert mission.task("product_validation").status == "FAILED"

    outcome = actions(db, mission).confirm(OWNER, proposal.id)

    done = fresh(db, proposal)
    assert (done.status, done.resolved_by) == ("EXECUTED", "owner-sub-1")
    assert done.execution_result == {"task_id": done.parameters["task_id"], "status": "COMPLETED", "attempt": 2}
    assert mission.task("product_validation").status == "COMPLETED"
    assert [e.attempt for e in mission.executions("product_validation")] == [1, 2]
    message = db.get(CeoMessage, outcome.result_message_id)
    assert message.conversation_id == done.conversation_id and done.result_message_id == message.id
    assert message.structured["kind"] == "action_result" and message.structured["status"] == "EXECUTED"
    assert [a.after["proposal_id"] for a in audits(db, "ceo.action_confirmed")] == [proposal.id]
    executed = audits(db, "ceo.action_executed")
    assert [a.after["proposal_id"] for a in executed] == [proposal.id] and executed[0].after["message_id"] == message.id
    assert audits(db, "ceo.action_failed") == []


def test_T_a_second_confirmation_does_not_execute_again(db):
    mission = incomplete_mission(db)
    proposal = propose(
        db,
        mission,
        "propose_retry_task",
        {"task_id": mission.task("product_validation").id, "after_attempt": 1, "reason": "reintento"},
    )
    service = actions(db, mission)
    service.confirm(OWNER, proposal.id)
    before = counts(db)

    with pytest.raises(ConflictError, match="EXECUTED"):
        service.confirm(OWNER, proposal.id)

    assert counts(db) == before and len(mission.executions("product_validation")) == 2
    assert len(audits(db, "ceo.action_executed")) == 1


def test_confirming_a_resume_continues_the_same_mission_and_writes_a_new_decision(db):
    mission = recovered_mission(db)
    proposal = propose(
        db, mission, "propose_resume_mission", {"objective_id": mission.objective.id, "reason": "ya recuperada"}
    )
    before = len(mission.decisions())

    actions(db, mission).confirm(OWNER, proposal.id)

    assert len(mission.decisions()) == before + 1
    assert load_mission(db, mission.manager, mission.project.id).state is MissionState.COMPLETE
    result = fresh(db, proposal).execution_result
    assert result["mission_state"] == "complete" and result["decision_status"] == "GO"
    assert db.query(Objective).count() == 1  # reanudar no crea otra misión


def test_confirming_a_reassignment_changes_the_agent_and_does_not_run_anything(db):
    mission = incomplete_mission(db, extra_agents={"agent-product-2": Scripted([])})
    proposal = propose(
        db,
        mission,
        "propose_reassign_task",
        {"task_id": mission.task("product_validation").id, "agent_id": "agent-product-2", "reason": "el primero falla"},
    )
    executions = len(mission.executions("product_validation"))

    actions(db, mission).confirm(OWNER, proposal.id)

    assert mission.task("product_validation").assigned_agent_id == "agent-product-2"
    assert mission.task("product_validation").status == "FAILED"  # reasignar no ejecuta
    assert len(mission.executions("product_validation")) == executions
    assert fresh(db, proposal).execution_result["assigned_agent_id"] == "agent-product-2"


def test_confirming_a_new_mission_creates_the_pre_announced_objective_and_runs_it(db):
    mission = recovered_mission(db)
    proposal = propose(
        db, mission, "propose_create_mission", {"title": "Investigar bidones", "reason": "análisis pedido"}
    )
    announced = proposal.target["objective_id"]
    assert db.get(Objective, announced) is None  # proponer no crea nada

    actions(db, mission).confirm(OWNER, proposal.id)

    objective = db.get(Objective, announced)
    assert (objective.title, objective.created_by) == ("Investigar bidones", "owner-sub-1")
    result = fresh(db, proposal).execution_result
    assert result["objective_id"] == announced and result["mission_state"] == "complete"
    assert db.query(Objective).count() == 2


@pytest.mark.parametrize(("decision", "status"), [("approve", "APPROVED"), ("reject", "REJECTED")])
def test_confirming_an_approval_resolves_it_through_the_real_path(db, decision, status):
    mission = recovered_mission(db)
    approval = Approval(
        decision_id=mission.latest().id, action="launch", amount=0, status="PENDING", correlation_id="c-1"
    )
    db.add(approval)
    db.commit()
    proposal = propose(
        db,
        mission,
        "propose_resolve_approval",
        {"approval_id": approval.id, "decision": decision, "reason": "decisión del propietario"},
    )

    actions(db, mission).confirm(OWNER, proposal.id)

    db.expire_all()
    assert db.get(Approval, approval.id).status == status
    assert [a.action for a in audits(db, f"approval.{decision}")] == [
        f"approval.{decision}"
    ]  # la auditoría real de las aprobaciones
    assert fresh(db, proposal).execution_result == {"approval_id": approval.id, "status": status}


# R. rechazar no ejecuta


def test_R_rejecting_executes_nothing_and_cannot_be_confirmed_afterwards(db):
    mission = incomplete_mission(db)
    proposal = propose(
        db,
        mission,
        "propose_retry_task",
        {"task_id": mission.task("product_validation").id, "after_attempt": 1, "reason": "reintento"},
    )
    before = counts(db)
    service = actions(db, mission)

    outcome = service.reject(OWNER, proposal.id)

    assert counts(db) == before and mission.task("product_validation").status == "FAILED"
    assert (fresh(db, proposal).status, fresh(db, proposal).resolved_by) == ("REJECTED", "owner-sub-1")
    assert db.get(CeoMessage, outcome.result_message_id).structured["status"] == "REJECTED"
    assert [a.after["proposal_id"] for a in audits(db, "ceo.action_rejected")] == [proposal.id]
    with pytest.raises(ConflictError, match="REJECTED"):
        service.confirm(OWNER, proposal.id)
    with pytest.raises(ConflictError):
        service.reject(OWNER, proposal.id)
    assert audits(db, "ceo.action_confirmed") == [] and audits(db, "ceo.action_executed") == []


# Una propuesta vieja: el servicio real vuelve a validar


def test_a_stale_proposal_fails_cleanly_and_does_not_repeat_what_was_done_meanwhile(db):
    mission = incomplete_mission(db)
    task_id = mission.task("product_validation").id
    proposal = propose(
        db, mission, "propose_retry_task", {"task_id": task_id, "after_attempt": 1, "reason": "reintento"}
    )
    mission.retry()  # otra persona reintentó antes (intento 2 → COMPLETED)
    before = counts(db)

    outcome = actions(db, mission).confirm(OWNER, proposal.id)

    failed = fresh(db, proposal)
    assert failed.status == "FAILED" and "FAILED" in failed.error  # «solo una tarea FAILED se reintenta»
    assert counts(db) == before and len(mission.executions("product_validation")) == 2
    assert "No se ha podido ejecutar" in db.get(CeoMessage, outcome.result_message_id).content
    assert [a.after["proposal_id"] for a in audits(db, "ceo.action_failed")] == [proposal.id]
    assert audits(db, "ceo.action_executed") == []


def test_an_unexpected_failure_leaves_the_proposal_unresolvable_and_says_so(db, monkeypatch):
    mission = incomplete_mission(db)
    proposal = propose(
        db,
        mission,
        "propose_retry_task",
        {"task_id": mission.task("product_validation").id, "after_attempt": 1, "reason": "reintento"},
    )

    def boom(*args, **kwargs):
        raise RuntimeError("corte inesperado con password=hunter2")

    monkeypatch.setattr("app.ceo_chat.actions.TaskRecoveryService.retry", boom)
    service = actions(db, mission)

    with pytest.raises(RuntimeError):
        service.confirm(OWNER, proposal.id)

    assert fresh(db, proposal).status == "EXECUTING"  # no se sabe si llegó a producir efecto: no se repite
    unknown = audits(db, "ceo.action_failed")[0]
    assert unknown.after["outcome"] == "unknown" and unknown.after["error_class"] == "RuntimeError"
    assert "hunter2" not in json.dumps(unknown.after)
    with pytest.raises(ConflictError, match="EXECUTING"):
        service.confirm(OWNER, proposal.id)


# X. identidad: solo el dueño de la conversación


def test_X_only_the_owner_of_the_conversation_can_confirm_or_reject(db):
    mission = incomplete_mission(db)
    proposal = propose(
        db,
        mission,
        "propose_retry_task",
        {"task_id": mission.task("product_validation").id, "after_attempt": 1, "reason": "reintento"},
    )
    service = actions(db, mission)
    before = counts(db)

    with pytest.raises(NotFoundError):
        service.confirm(OTHER_OWNER, proposal.id)
    with pytest.raises(NotFoundError):
        service.reject(OTHER_OWNER, proposal.id)
    with pytest.raises(NotFoundError):
        service.confirm(OWNER, "no-existe")

    assert fresh(db, proposal).status == "PROPOSED" and counts(db) == before
    assert audits(db, "ceo.action_confirmed") == []


def test_the_audit_of_a_confirmation_carries_ids_and_never_message_text(db):
    mission = incomplete_mission(db)
    proposal = propose(
        db,
        mission,
        "propose_retry_task",
        {
            "task_id": mission.task("product_validation").id,
            "after_attempt": 1,
            "reason": "reintento con password=hunter2",
        },
    )
    actions(db, mission).confirm(OWNER, proposal.id)

    everything = json.dumps([a.after for a in db.query(AuditLog).all() if a.action.startswith("ceo.")], default=str)

    assert "hunter2" not in everything and "reintento con" not in everything
    assert P1 in json.dumps(fresh(db, proposal).target)
