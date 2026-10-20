"""La relación TAREA ↔ AGENTE como función pura (M48, Commit 7).

ASIGNACIÓN ≠ EJECUCIÓN: una tarea puede estar sin asignar, asignada y sin ejecutar, ejecutada por quien tenía
asignada, ejecutada por otro agente, o ser del orquestador. `describe_relation` lo dice en UNA sola palabra (`status`)
sin colapsar esos casos, y nunca infiere un agente de la capacidad, del nombre, del orden ni de la correlación."""

import datetime

import pytest

from app.tasks.assignment import AssignmentStatus, ExecutionTrace, describe_relation

KNOWN = {"agent-product-1", "agent-product-2", "agent-supplier-1"}
T0 = datetime.datetime(2026, 10, 20, 12, 0, tzinfo=datetime.UTC)


def trace(
    agent_id: str, *, success: bool | None = True, attempt: int | None = 1, source: str = "execution_log", n: int = 0
):
    return ExecutionTrace(
        source=source,  # type: ignore[arg-type]
        agent_id=agent_id,
        success=success,
        attempt=attempt,
        execution_id=f"e-{n}" if source == "execution_log" else None,
        assigned_agent_id=None,
        started_at=None,
        completed_at=None,
        created_at=T0 + datetime.timedelta(seconds=n),
    )


def relation(
    *, capability="market_validation", status="PENDING", assigned=None, traces=(), known=KNOWN, reassigned=False
):
    return describe_relation(
        capability=capability,
        task_status=status,
        assigned_agent_id=assigned,
        traces=list(traces),
        known_agent_ids=known,
        reassigned=reassigned,
    )


# --- A · B · C --------------------------------------------------------------------------------------------------------


def test_A_a_task_with_no_assignment_and_no_execution_is_unassigned():
    result = relation()
    assert result.status is AssignmentStatus.UNASSIGNED
    assert result.assigned_agent_id is None
    assert result.assigned_agent_known is None
    assert result.executed_by_agent_id is None


def test_B_a_task_assigned_to_an_existing_agent_is_assigned_and_not_executed():
    result = relation(assigned="agent-product-1")
    assert result.status is AssignmentStatus.ASSIGNED
    assert result.assigned_agent_known is True
    assert result.executed_by_agent_id is None


def test_C_a_task_assigned_to_a_nonexistent_agent_is_an_unknown_agent_and_never_unassigned():
    result = relation(assigned="agent-ghost-9")
    assert result.status is AssignmentStatus.UNKNOWN_AGENT
    assert result.assigned_agent_known is False
    assert result.status is not AssignmentStatus.UNASSIGNED


def test_C2_an_unknown_assigned_agent_stays_unknown_even_if_somebody_executed_the_task():
    result = relation(assigned="agent-ghost-9", traces=[trace("agent-product-1")])
    assert result.status is AssignmentStatus.UNKNOWN_AGENT


def test_L_an_unknown_executor_is_an_unknown_agent_not_an_available_one():
    result = relation(assigned="agent-product-1", traces=[trace("agent-removed-3")])
    assert result.status is AssignmentStatus.UNKNOWN_AGENT
    assert result.executed_by_agent_id == "agent-removed-3"


# --- D · E ------------------------------------------------------------------------------------------------------------


def test_D_a_task_executed_by_the_assigned_agent_is_a_match():
    result = relation(status="COMPLETED", assigned="agent-product-1", traces=[trace("agent-product-1")])
    assert result.status is AssignmentStatus.MATCH
    assert result.executed_by_agent_id == "agent-product-1"


def test_E_a_task_executed_by_a_different_agent_is_an_explicit_mismatch_never_a_match():
    result = relation(status="COMPLETED", assigned="agent-product-1", traces=[trace("agent-supplier-1")])
    assert result.status is AssignmentStatus.MISMATCH
    assert result.assigned_agent_id == "agent-product-1"
    assert result.executed_by_agent_id == "agent-supplier-1", (
        "quién la ejecutó NO se sustituye por quién la tenía asignada"
    )


# --- F · G · H · retries and reassignment -----------------------------------------------------------------------------


def test_F_a_retry_by_the_same_agent_keeps_every_execution_and_the_latest_decides():
    traces = [
        trace("agent-product-1", success=False, attempt=1, n=1),
        trace("agent-product-1", success=True, attempt=2, n=2),
    ]

    result = relation(status="COMPLETED", assigned="agent-product-1", traces=traces)

    assert result.status is AssignmentStatus.MATCH
    assert [(item.attempt, item.success) for item in result.executions] == [(1, False), (2, True)]


def test_G_a_retry_by_a_different_agent_keeps_the_first_execution_and_the_latest_executor_wins():
    traces = [
        trace("agent-product-1", success=False, attempt=1, n=1),
        trace("agent-product-2", success=True, attempt=2, n=2),
    ]

    result = relation(status="COMPLETED", assigned="agent-product-2", traces=traces, reassigned=True)

    assert result.status is AssignmentStatus.MATCH
    assert result.executed_by_agent_id == "agent-product-2"
    assert [item.agent_id for item in result.executions] == ["agent-product-1", "agent-product-2"]
    assert result.reassigned is True


def test_G2_executions_are_ordered_by_time_not_by_the_order_they_were_given():
    traces = [trace("agent-product-2", attempt=2, n=2), trace("agent-product-1", success=False, attempt=1, n=1)]

    result = relation(assigned="agent-product-2", traces=traces)

    assert [item.attempt for item in result.executions] == [1, 2]
    assert result.executed_by_agent_id == "agent-product-2"


def test_H_a_reassignment_is_reported_without_hiding_the_current_assignment():
    result = relation(assigned="agent-product-2", reassigned=True)
    assert result.status is AssignmentStatus.ASSIGNED
    assert result.assigned_agent_id == "agent-product-2"
    assert result.reassigned is True


# --- J · completed without an execution -------------------------------------------------------------------------------


def test_J_a_completed_agent_task_with_no_execution_trace_is_an_inconsistency_even_if_it_has_an_assignment():
    assert relation(status="COMPLETED", assigned="agent-product-1").status is AssignmentStatus.INCONSISTENT
    assert relation(status="COMPLETED").status is AssignmentStatus.INCONSISTENT


def test_J2_a_task_that_is_not_completed_and_has_no_trace_is_not_an_inconsistency():
    for status in ("PENDING", "RUNNING", "FAILED", "CANCELLED"):
        assert relation(status=status, assigned="agent-product-1").status is AssignmentStatus.ASSIGNED


# --- K · the capability is never enough to name an agent --------------------------------------------------------------


@pytest.mark.parametrize("capability", ["market_validation", "supplier_sourcing", "legal_validation", "unheard_of"])
def test_K_a_capability_with_agents_in_the_registry_never_fills_an_unassigned_task(capability):
    result = relation(capability=capability)
    assert result.assigned_agent_id is None
    assert result.status is AssignmentStatus.UNASSIGNED


def test_K2_an_executed_task_with_no_assignment_is_said_so_and_never_assigned_after_the_fact():
    result = relation(status="COMPLETED", traces=[trace("agent-product-1", source="audit", attempt=None)])
    assert result.status is AssignmentStatus.EXECUTED_UNASSIGNED
    assert result.assigned_agent_id is None, "la ejecución no crea una asignación"
    assert result.executed_by_agent_id == "agent-product-1"
    assert result.executions[0].source == "audit"


# --- el orquestador ---------------------------------------------------------------------------------------------------


def test_the_orchestrator_capability_is_owned_by_the_orchestrator_not_unassigned():
    result = relation(capability="decision_synthesis", status="COMPLETED")
    assert result.status is AssignmentStatus.ORCHESTRATOR
    assert result.assigned_agent_id is None


def test_an_orchestrator_task_with_an_assignment_or_an_agent_execution_is_an_inconsistency():
    assert relation(capability="decision_synthesis", assigned="agent-product-1").status is AssignmentStatus.INCONSISTENT
    assert (
        relation(capability="decision_synthesis", traces=[trace("agent-product-1")]).status
        is AssignmentStatus.INCONSISTENT
    )


# --- validaciones de la función ---------------------------------------------------------------------------------------


def test_the_function_does_not_depend_on_the_names_or_the_order_of_the_known_agents():
    assert (
        relation(assigned="agent-product-1", known=["agent-supplier-1", "agent-product-1"]).status
        is AssignmentStatus.ASSIGNED
    )
    assert relation(assigned="agent-product-1", known=set()).status is AssignmentStatus.UNKNOWN_AGENT


def test_an_agent_id_is_compared_exactly_no_prefix_no_case_folding():
    assert relation(assigned="Agent-Product-1").status is AssignmentStatus.UNKNOWN_AGENT
    assert relation(assigned="agent-product").status is AssignmentStatus.UNKNOWN_AGENT


def test_the_models_have_no_foreign_key_on_the_assignment_and_one_from_the_execution_to_its_task():
    from app.db.models.agent_execution_log import AgentExecutionLog
    from app.db.models.task import Task

    assert not Task.__table__.c.assigned_agent_id.foreign_keys, "los agentes viven en el registro, no en `agents`"
    assert {fk.target_fullname for fk in AgentExecutionLog.__table__.c.task_id.foreign_keys} == {"tasks.id"}
    assert not AgentExecutionLog.__table__.c.assigned_agent_id.foreign_keys
