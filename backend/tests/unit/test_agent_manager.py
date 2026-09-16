import pytest

from app.agents.base import Agent, AgentDescriptor, AgentResult, AgentStatus
from app.agents.manager import AgentManager, NoAgentAvailableError
from app.agents.registry import AgentRegistry
from app.tasks.schemas import Task


def make_descriptor(**overrides) -> AgentDescriptor:
    defaults = dict(
        id="agent-1",
        name="Agent",
        role="product",
        version="1.0.0",
        capabilities=["market_validation"],
        reliability_score=1.0,
        cost_profile={"simulated_cost_per_task": 0.0},
    )
    defaults.update(overrides)
    return AgentDescriptor(**defaults)


class StubAgent(Agent):
    capability = "market_validation"

    def __init__(self, result: AgentResult):
        self._result = result

    def run(self, task_input: dict) -> AgentResult:
        return self._result


def make_result(**overrides) -> AgentResult:
    defaults = dict(
        status="COMPLETED",
        recommendation="GO",
        confidence=0.9,
        evidence=["evidence"],
        risks=[],
        assumptions=[],
        data={},
    )
    defaults.update(overrides)
    return AgentResult(**defaults)


@pytest.fixture()
def registry() -> AgentRegistry:
    return AgentRegistry()


@pytest.fixture()
def manager(registry: AgentRegistry) -> AgentManager:
    return AgentManager(registry)


def test_select_agent_prefers_higher_reliability(manager: AgentManager, registry: AgentRegistry):
    weak = make_descriptor(id="agent-weak", reliability_score=0.5)
    strong = make_descriptor(id="agent-strong", reliability_score=0.95)
    registry.register(weak)
    registry.register(strong)

    selected = manager.select_agent("market_validation")

    assert selected.id == "agent-strong"


def test_select_agent_skips_unavailable_agents(manager: AgentManager, registry: AgentRegistry):
    busy_but_reliable = make_descriptor(id="agent-busy", reliability_score=0.99, status=AgentStatus.BUSY)
    available = make_descriptor(id="agent-available", reliability_score=0.6, status=AgentStatus.AVAILABLE)
    registry.register(busy_but_reliable)
    registry.register(available)

    selected = manager.select_agent("market_validation")

    assert selected.id == "agent-available"


def test_select_agent_raises_when_no_agent_is_available(manager: AgentManager, registry: AgentRegistry):
    registry.register(make_descriptor(id="agent-busy", status=AgentStatus.BUSY))

    with pytest.raises(NoAgentAvailableError):
        manager.select_agent("market_validation")


def test_select_agent_is_deterministic_for_the_same_registry_state(
    manager: AgentManager, registry: AgentRegistry
):
    registry.register(make_descriptor(id="agent-a", reliability_score=0.8))
    registry.register(make_descriptor(id="agent-b", reliability_score=0.8))

    first = manager.select_agent("market_validation")
    second = manager.select_agent("market_validation")

    assert first.id == second.id


def test_execute_runs_the_registered_executor_and_returns_agent_result(
    manager: AgentManager, registry: AgentRegistry
):
    descriptor = make_descriptor(id="agent-1")
    registry.register(descriptor)
    expected = make_result(recommendation="GO", confidence=0.77)
    manager.register_executor("agent-1", StubAgent(expected))
    task = Task(project_id="proj-1", name="Product validation", capability="market_validation")

    result = manager.execute("agent-1", task)

    assert result == expected


def test_execute_records_a_successful_execution_with_measured_duration(
    manager: AgentManager, registry: AgentRegistry
):
    registry.register(make_descriptor(id="agent-1"))
    manager.register_executor("agent-1", StubAgent(make_result()))
    task = Task(project_id="proj-1", name="t", capability="market_validation")

    manager.execute("agent-1", task)

    assert len(manager.execution_log) == 1
    entry = manager.execution_log[-1]
    assert entry["agent_id"] == "agent-1"
    assert entry["capability"] == "market_validation"
    assert entry["success"] is True
    assert entry["duration_ms"] >= 0


def test_execute_records_a_failed_execution_before_reraising(manager: AgentManager, registry: AgentRegistry):
    class FailingAgent(Agent):
        capability = "market_validation"

        def run(self, task_input: dict) -> AgentResult:
            raise RuntimeError("boom")

    registry.register(make_descriptor(id="agent-fail"))
    manager.register_executor("agent-fail", FailingAgent())
    task = Task(project_id="proj-1", name="t", capability="market_validation")

    with pytest.raises(RuntimeError):
        manager.execute("agent-fail", task)

    assert len(manager.execution_log) == 1
    assert manager.execution_log[-1]["success"] is False
