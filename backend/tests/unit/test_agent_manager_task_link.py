"""El AgentManager dice si un agente puede ejecutar una capacidad y mide cuándo empezó y terminó cada ejecución (M48,
Commit 7)."""

import datetime

import pytest

from app.agents.base import Agent, AgentDescriptor, AgentResult, AgentStatus
from app.agents.manager import AgentManager
from app.agents.registry import AgentRegistry
from app.tasks.schemas import Task


class Echo(Agent):
    capability = "market_validation"

    def run(self, task_input: dict) -> AgentResult:
        return AgentResult(
            status="COMPLETED", recommendation="GO", confidence=0.9, evidence=["e"], risks=[], assumptions=[], data={}
        )


class Boom(Agent):
    capability = "market_validation"

    def run(self, task_input: dict) -> AgentResult:
        raise RuntimeError("boom")


@pytest.fixture()
def manager() -> AgentManager:
    registry = AgentRegistry()
    for agent_id, capability in (("agent-a", "market_validation"), ("agent-b", "supplier_sourcing")):
        registry.register(AgentDescriptor(id=agent_id, name=agent_id, role="x", version="1", capabilities=[capability]))
    manager = AgentManager(registry)
    manager.register_executor("agent-a", Echo())
    return manager


def task() -> Task:
    return Task(project_id="p", name="t", capability="market_validation")


def test_an_agent_is_routable_for_its_own_capability_when_it_is_available(manager):
    assert manager.is_routable("agent-a", "market_validation") is True


def test_an_agent_is_not_routable_for_a_capability_it_does_not_have_nor_when_unknown_or_unavailable(manager):
    assert manager.is_routable("agent-a", "supplier_sourcing") is False
    assert manager.is_routable("agent-ghost", "market_validation") is False
    for status in (AgentStatus.DISABLED, AgentStatus.FAILED, AgentStatus.BUSY, AgentStatus.BLOCKED):
        manager._registry.set_status("agent-a", status)
        assert manager.is_routable("agent-a", "market_validation") is False, status


def test_is_routable_uses_the_same_rule_as_select_agent(manager):
    assert manager.select_agent("market_validation").id == "agent-a"
    assert manager.is_routable("agent-a", "market_validation")
    manager._registry.set_status("agent-a", AgentStatus.DISABLED)
    assert not manager.is_routable("agent-a", "market_validation")


def test_an_execution_records_when_it_started_and_when_it_finished(manager):
    before = datetime.datetime.now(datetime.UTC)

    manager.execute("agent-a", task())

    entry = manager.execution_log[-1]
    assert before <= entry["started_at"] <= entry["completed_at"] <= datetime.datetime.now(datetime.UTC)
    assert entry["started_at"].tzinfo is not None
    assert (entry["agent_id"], entry["capability"], entry["success"]) == ("agent-a", "market_validation", True)


def test_a_failed_execution_also_records_its_times(manager):
    manager.register_executor("agent-a", Boom())

    with pytest.raises(RuntimeError):
        manager.execute("agent-a", task())

    entry = manager.execution_log[-1]
    assert entry["success"] is False
    assert entry["started_at"] <= entry["completed_at"]


def test_the_existing_keys_of_the_log_entry_are_unchanged(manager):
    manager.execute("agent-a", task())

    assert {"agent_id", "capability", "duration_ms", "success"} <= set(manager.execution_log[-1])
