"""La máquina de estados de una tarea, la política de intentos y la lectura de «qué se puede hacer» (M49, Commit 8).

RETRY, REASIGNACIÓN, DESVIACIÓN y OVERRIDE no son lo mismo y aquí se fijan como contrato:

- un retry repite con el MISMO agente asignado y es el intento siguiente;
- una reasignación cambia la asignación vigente (la anterior queda en la auditoría) y el siguiente intento usa al
  nuevo;
- una desviación (ejecuta otro agente) se ve y NO cambia la asignación;
- un override (aceptar una desviación) es explícito y autorizado — no existe todavía: nada convierte una desviación
  en otra cosa."""

import datetime
import inspect
import re
from pathlib import Path

import pytest

import app.ceo.orchestrator as orchestrator_module
from app.tasks import policy
from app.tasks.assignment import AssignmentStatus, ExecutionTrace
from app.tasks.lifecycle import ALLOWED_TRANSITIONS, InvalidTaskTransitionError, can_transition, ensure_transition
from app.tasks.recovery import RecoveryKind, describe_recovery
from app.tasks.schemas import TaskStatus

S = TaskStatus
T0 = datetime.datetime(2026, 10, 24, 10, 0, tzinfo=datetime.UTC)
KNOWN = {"agent-product-1", "agent-product-2", "agent-supplier-1"}

# --- transiciones
# ------------------------------------------------------------------------------------------------------

EXPECTED = {
    S.PENDING: {S.RUNNING, S.BLOCKED, S.CANCELLED},
    S.RUNNING: {S.COMPLETED, S.FAILED},
    S.FAILED: {S.PENDING, S.CANCELLED},
    S.BLOCKED: {S.PENDING, S.CANCELLED},
    S.COMPLETED: set(),
    S.CANCELLED: set(),
}


def test_the_transition_table_is_exactly_the_agreed_one():
    assert {state: set(targets) for state, targets in ALLOWED_TRANSITIONS.items()} == EXPECTED


@pytest.mark.parametrize("current", list(S))
@pytest.mark.parametrize("new", list(S))
def test_every_pair_is_allowed_only_if_it_is_in_the_table(current, new):
    allowed = new in EXPECTED.get(current, set())
    assert can_transition(current, new) is allowed
    if allowed:
        assert ensure_transition(current, new) is new
    else:
        with pytest.raises(InvalidTaskTransitionError):
            ensure_transition(current, new)


def test_a_completed_task_can_never_run_again_and_strings_are_accepted():
    assert not can_transition("COMPLETED", "RUNNING")
    assert not can_transition("COMPLETED", "PENDING")
    assert can_transition("FAILED", "PENDING")
    with pytest.raises(InvalidTaskTransitionError):
        ensure_transition("COMPLETED", "FAILED")


def test_statuses_the_task_flow_never_uses_have_no_transitions_in_or_out():
    for unused in (S.QUEUED, S.WAITING, S.WAITING_APPROVAL):
        assert unused not in EXPECTED
        assert not any(can_transition(unused, other) or can_transition(other, unused) for other in S)


def test_an_unknown_status_string_is_not_a_valid_transition():
    assert not can_transition("PENDIENTE", "RUNNING")
    with pytest.raises(InvalidTaskTransitionError):
        ensure_transition("RUNNING", "ASSIGNED")  # ASSIGNED no es un estado de la tarea: es la relación con su agente


# --- política de intentos: una sola definición
# -------------------------------------------------------------------------


def test_the_attempt_limits_come_from_the_single_retry_policy():
    assert policy.MAX_ATTEMPTS_PER_ASSIGNMENT == policy.DEFAULT_MAX_TASK_RETRIES + 1 == 3
    assert policy.MAX_ATTEMPTS_PER_TASK == 2 * policy.MAX_ATTEMPTS_PER_ASSIGNMENT == 6
    assert orchestrator_module.DEFAULT_MAX_TASK_RETRIES is policy.DEFAULT_MAX_TASK_RETRIES


def test_the_retry_bound_is_not_written_down_twice():
    app_dir = Path(inspect.getsourcefile(policy)).parent.parent  # type: ignore[arg-type]
    definitions = [
        path.relative_to(app_dir).as_posix()
        for path in app_dir.rglob("*.py")
        if re.search(r"^DEFAULT_MAX_TASK_RETRIES\s*(:\s*int\s*)?=", path.read_text(encoding="utf-8"), re.M)
    ]
    assert definitions == ["tasks/policy.py"]


# --- qué se puede hacer con una tarea (lectura pura)
# -------------------------------------------------------------------


def trace(agent: str, *, assigned: str | None, ok: bool, attempt: int, n: int = 0) -> ExecutionTrace:
    return ExecutionTrace(
        source="execution_log",
        agent_id=agent,
        success=ok,
        attempt=attempt,
        execution_id=f"e-{attempt}-{n}",
        assigned_agent_id=assigned,
        started_at=None,
        completed_at=None,
        created_at=T0 + datetime.timedelta(seconds=attempt),
    )


def recovery(status: str, assigned: str | None, traces, relation=AssignmentStatus.MATCH):
    return describe_recovery(
        task_status=status,
        assigned_agent_id=assigned,
        known_agent_ids=KNOWN,
        traces=traces,
        relation_status=relation,
    )


def test_a_task_that_is_not_failed_has_nothing_to_recover():
    done = recovery(
        "COMPLETED", "agent-product-1", [trace("agent-product-1", assigned="agent-product-1", ok=True, attempt=1)]
    )
    assert done.kind is RecoveryKind.NONE
    assert done.can_retry is False
    assert recovery("PENDING", "agent-product-1", []).kind is RecoveryKind.NONE


def test_a_failed_task_with_attempts_left_is_recoverable_and_the_next_attempt_is_numbered():
    one = [trace("agent-product-1", assigned="agent-product-1", ok=False, attempt=1)]
    result = recovery("FAILED", "agent-product-1", one)
    assert result.kind is RecoveryKind.RECOVERABLE
    assert (result.attempts_current_assignment, result.attempts_total, result.next_attempt) == (1, 1, 2)
    assert result.can_retry is True


def test_an_agent_that_used_all_its_attempts_needs_a_reassignment_not_another_retry():
    three = [trace("agent-product-1", assigned="agent-product-1", ok=False, attempt=n) for n in (1, 2, 3)]
    result = recovery("FAILED", "agent-product-1", three)
    assert result.kind is RecoveryKind.REASSIGN_REQUIRED
    assert result.can_retry is False


def test_a_reassignment_gives_the_new_agent_its_own_attempts_but_the_task_total_is_capped():
    old = [trace("agent-product-1", assigned="agent-product-1", ok=False, attempt=n) for n in (1, 2, 3)]
    fresh = recovery("FAILED", "agent-product-2", old)
    assert fresh.kind is RecoveryKind.RECOVERABLE
    assert (fresh.attempts_current_assignment, fresh.attempts_total, fresh.next_attempt) == (0, 3, 4)

    both = old + [trace("agent-product-2", assigned="agent-product-2", ok=False, attempt=n) for n in (4, 5, 6)]
    capped = recovery("FAILED", "agent-product-2", both)
    assert capped.kind is RecoveryKind.DEFINITIVE
    assert capped.can_retry is False


def test_an_unknown_assigned_agent_is_its_own_case_with_no_fallback():
    result = recovery("BLOCKED", "agent-ghost-9", [], AssignmentStatus.UNKNOWN_AGENT)
    assert result.kind is RecoveryKind.UNKNOWN_AGENT
    assert result.can_retry is False
    assert recovery("FAILED", "agent-ghost-9", [], AssignmentStatus.UNKNOWN_AGENT).kind is RecoveryKind.UNKNOWN_AGENT


def test_a_deviation_is_reported_as_such_and_is_not_a_recoverable_failure():
    traces = [trace("agent-supplier-1", assigned="agent-product-1", ok=False, attempt=1)]
    result = recovery("FAILED", "agent-product-1", traces, AssignmentStatus.MISMATCH)
    assert result.kind is RecoveryKind.MISMATCH
    assert result.can_retry is False


def test_a_blocked_task_waits_for_its_dependencies_and_cannot_be_retried():
    result = recovery("BLOCKED", "agent-supplier-1", [])
    assert result.kind is RecoveryKind.BLOCKED
    assert result.can_retry is False


def test_only_execution_log_traces_count_as_attempts_audit_traces_do_not():
    legacy = ExecutionTrace(
        source="audit",
        agent_id="agent-product-1",
        success=False,
        attempt=None,
        execution_id=None,
        assigned_agent_id=None,
        started_at=None,
        completed_at=None,
        created_at=T0,
    )
    result = recovery("FAILED", "agent-product-1", [legacy])
    assert result.attempts_total == 0
    assert result.can_retry is False  # sin ningún intento registrado no hay nada que repetir
    assert result.kind is RecoveryKind.NONE
