"""Estado de una misión a partir de sus tareas (M50, Commit 9). Función pura: sin base de datos ni agentes.

«Completa» es una sola cosa: la tarea de síntesis está COMPLETED (solo se completa cuando las cuatro especialistas
lo estaban). Todo lo demás es «incompleta», y se reparte en: lista para reanudar (nada atascado: lo que falta está
PENDING o BLOQUEADO solo por algo que aún va a ejecutarse) o recuperación pendiente (algo atascado que alguien con
autoridad tiene que resolver antes: una tarea FAILED, un agente desconocido, una desviación sin resolver…)."""

import pytest

from app.ceo.mission import MissionState, TaskFact, describe_mission

ORDER = ["product_validation", "supplier_sourcing", "legal_validation", "finance_validation", "decision_synthesis"]


def facts(statuses: dict[str, str], **override) -> list[TaskFact]:
    out = []
    for name in ORDER:
        base = {
            "id": f"id-{name}",
            "name": name,
            "capability": "decision_synthesis" if name == "decision_synthesis" else name,
            "status": statuses.get(name, "COMPLETED"),
            "assigned_agent_id": None if name == "decision_synthesis" else f"agent-{name}",
            "agent_known": True,
            "agent_available": True,
            "recovery_kind": "none",
        }
        base.update(override.get(name, {}))
        out.append(TaskFact(**base))
    return out


def view(statuses, decisions=("d1",), **override):
    return describe_mission(facts(statuses, **override), decision_ids=decisions)


def test_a_mission_whose_synthesis_is_completed_is_complete_and_not_resumable():
    mission = view({})
    assert mission.state is MissionState.COMPLETE
    assert mission.resumed is False
    assert mission.resumable is False


def test_a_complete_mission_with_two_decisions_is_marked_as_resumed():
    mission = view({}, decisions=("d1", "d2"))
    assert mission.state is MissionState.COMPLETE
    assert mission.resumed is True
    assert mission.current_decision_id == "d2"


def test_pending_work_with_nothing_stuck_is_ready_to_resume():
    mission = view(
        {
            "supplier_sourcing": "PENDING",
            "legal_validation": "PENDING",
            "finance_validation": "BLOCKED",
            "decision_synthesis": "BLOCKED",
        }
    )
    assert mission.state is MissionState.READY_TO_RESUME
    assert mission.resumable is True
    assert mission.blockers == ()
    assert mission.pending_tasks == (
        "supplier_sourcing",
        "legal_validation",
        "finance_validation",
        "decision_synthesis",
    )


def test_only_the_synthesis_left_is_ready_to_resume():
    assert view({"decision_synthesis": "BLOCKED"}).state is MissionState.READY_TO_RESUME
    assert view({"decision_synthesis": "PENDING"}).state is MissionState.READY_TO_RESUME


@pytest.mark.parametrize(
    ("kind", "reason"),
    [
        ("recoverable", "failed_recoverable"),
        ("reassign_required", "failed_reassign_required"),
        ("definitive", "failed_definitive"),
    ],
)
def test_a_failed_task_is_recovery_pending_with_the_reason_of_its_recovery_kind(kind, reason):
    mission = view(
        {"product_validation": "FAILED", "supplier_sourcing": "BLOCKED", "decision_synthesis": "BLOCKED"},
        product_validation={"recovery_kind": kind},
    )
    assert mission.state is MissionState.RECOVERY_PENDING
    assert mission.resumable is False
    assert [(b.task_name, b.reason) for b in mission.blockers] == [("product_validation", reason)]


def test_an_unknown_agent_on_an_unfinished_task_is_recovery_pending():
    mission = view(
        {"supplier_sourcing": "BLOCKED", "decision_synthesis": "BLOCKED"}, supplier_sourcing={"agent_known": False}
    )
    assert mission.state is MissionState.RECOVERY_PENDING
    assert [(b.task_name, b.reason) for b in mission.blockers] == [("supplier_sourcing", "unknown_agent")]


def test_an_unknown_agent_on_a_completed_task_does_not_block():
    mission = view({"decision_synthesis": "PENDING"}, product_validation={"agent_known": False})
    assert mission.state is MissionState.READY_TO_RESUME


def test_an_unresolved_mismatch_on_an_unfinished_task_blocks_but_on_a_completed_one_it_does_not():
    blocked = view(
        {"legal_validation": "PENDING", "decision_synthesis": "BLOCKED"}, legal_validation={"recovery_kind": "mismatch"}
    )
    assert blocked.state is MissionState.RECOVERY_PENDING
    assert [b.reason for b in blocked.blockers] == ["mismatch"]
    visible_only = view({"decision_synthesis": "PENDING"}, product_validation={"recovery_kind": "mismatch"})
    assert visible_only.state is MissionState.READY_TO_RESUME


def test_no_agent_available_for_a_pending_task_is_recovery_pending():
    mission = view(
        {"supplier_sourcing": "PENDING", "decision_synthesis": "BLOCKED"}, supplier_sourcing={"agent_available": False}
    )
    assert mission.state is MissionState.RECOVERY_PENDING
    assert [b.reason for b in mission.blockers] == ["no_agent_available"]


def test_a_cancelled_task_makes_the_mission_cancelled():
    mission = view({"legal_validation": "CANCELLED", "decision_synthesis": "BLOCKED"})
    assert mission.state is MissionState.CANCELLED
    assert mission.resumable is False


def test_a_cancelled_project_makes_the_mission_cancelled_even_if_everything_else_is_pending():
    mission = describe_mission(facts({"supplier_sourcing": "PENDING"}), decision_ids=("d1",), cancelled=True)
    assert mission.state is MissionState.CANCELLED


def test_a_running_task_means_the_mission_is_being_resumed_and_is_not_resumable():
    mission = view({"supplier_sourcing": "RUNNING", "decision_synthesis": "BLOCKED"})
    assert mission.state is MissionState.RESUMING
    assert mission.resumable is False
    assert [b.reason for b in mission.blockers] == ["running"]


def test_a_plan_without_a_required_task_is_inconsistent_and_never_resumable():
    tasks = [t for t in facts({"decision_synthesis": "PENDING"}) if t.name != "finance_validation"]
    mission = describe_mission(tasks, decision_ids=("d1",))
    assert mission.state is MissionState.INCONSISTENT
    assert mission.resumable is False


def test_a_mission_with_no_decision_has_no_current_decision():
    assert describe_mission(facts({"decision_synthesis": "PENDING"}), decision_ids=()).current_decision_id is None


def test_the_pending_list_follows_the_plan_order_and_excludes_completed_tasks():
    mission = view({"finance_validation": "BLOCKED", "decision_synthesis": "BLOCKED", "legal_validation": "PENDING"})
    assert mission.pending_tasks == ("legal_validation", "finance_validation", "decision_synthesis")
    assert mission.completed_tasks == ("product_validation", "supplier_sourcing")
