import pytest
from pydantic import ValidationError

from app.agents.base import AgentDescriptor, AgentResult, AgentStatus
from app.ceo.schemas import ApprovalStatus, DecisionStatus, ProjectStatus
from app.events.schemas import Event
from app.tasks.schemas import TaskStatus


def test_task_status_has_all_required_states():
    expected = {
        "PENDING",
        "QUEUED",
        "RUNNING",
        "WAITING",
        "WAITING_APPROVAL",
        "COMPLETED",
        "FAILED",
        "CANCELLED",
        "BLOCKED",
    }
    assert {member.value for member in TaskStatus} == expected


def test_project_status_has_all_required_states():
    expected = {
        "DRAFT",
        "VALIDATING",
        "APPROVED",
        "EXECUTING",
        "MONITORING",
        "PAUSED",
        "COMPLETED",
        "REJECTED",
        "FAILED",
    }
    assert {member.value for member in ProjectStatus} == expected


def test_decision_status_has_all_required_states():
    assert {member.value for member in DecisionStatus} == {"GO", "REVIEW", "NO_GO", "HUMAN_APPROVAL"}


def test_agent_status_has_all_required_states():
    expected = {"AVAILABLE", "BUSY", "WAITING", "BLOCKED", "DEGRADED", "DISABLED", "FAILED"}
    assert {member.value for member in AgentStatus} == expected


def test_approval_status_has_all_required_states():
    expected = {"PENDING", "APPROVED", "REJECTED", "EXPIRED", "CANCELLED"}
    assert {member.value for member in ApprovalStatus} == expected


def test_agent_result_accepts_a_valid_confidence():
    result = AgentResult(
        status="COMPLETED",
        recommendation="GO",
        confidence=0.82,
        evidence=["market size is $50M with 12% YoY growth"],
        risks=["single supplier dependency"],
        assumptions=["demand estimate based on category averages"],
        data={"opportunity_score": 0.7},
    )

    assert result.confidence == 0.82


@pytest.mark.parametrize("invalid_confidence", [-0.1, 1.1, 2, -5])
def test_agent_result_rejects_confidence_outside_unit_interval(invalid_confidence):
    with pytest.raises(ValidationError):
        AgentResult(
            status="COMPLETED",
            recommendation="GO",
            confidence=invalid_confidence,
            evidence=[],
            risks=[],
            assumptions=[],
            data={},
        )


def test_agent_result_rejects_arbitrary_free_form_payload():
    with pytest.raises(ValidationError):
        AgentResult(status="COMPLETED", confidence=0.5)  # missing required structured fields


def test_agent_descriptor_requires_capabilities_list():
    descriptor = AgentDescriptor(
        id="agent-product-1",
        name="Product Research Agent",
        role="product",
        version="1.0.0",
        capabilities=["market_validation"],
        permissions=["research.read"],
        reliability_score=0.95,
        cost_profile={"simulated_cost_per_task": 0.0},
        latency_profile={"p50_ms": 100},
        regions=["EU"],
    )

    assert descriptor.status == AgentStatus.AVAILABLE
    assert "market_validation" in descriptor.capabilities


def test_event_requires_correlation_id():
    with pytest.raises(ValidationError):
        Event(type="task.completed", payload={})  # missing correlation_id


def test_event_accepts_valid_payload():
    event = Event(type="task.completed", correlation_id="corr-1", payload={"task_id": "t1"})

    assert event.type == "task.completed"
    assert event.payload["task_id"] == "t1"
