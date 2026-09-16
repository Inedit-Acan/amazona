import pytest
from pydantic import BaseModel

from app.agents.base import Agent, AgentResult
from app.agents.manager import AgentManager
from app.agents.registry import AgentRegistry
from app.core.errors import AgentIOValidationError
from app.tasks.schemas import Task


class StrictInputSchema(BaseModel):
    required_field: int


class StrictOutputSchema(BaseModel):
    score: float


class StrictAgent(Agent):
    capability = "strict_capability"
    input_schema = StrictInputSchema
    output_schema = StrictOutputSchema

    def run(self, task_input: dict) -> AgentResult:
        return AgentResult(
            status="COMPLETED",
            recommendation="GO",
            confidence=0.9,
            evidence=[],
            risks=[],
            assumptions=[],
            data={"score": 0.5},
        )


class LenientAgent(Agent):
    capability = "lenient_capability"

    def run(self, task_input: dict) -> AgentResult:
        return AgentResult(
            status="COMPLETED",
            recommendation="GO",
            confidence=0.9,
            evidence=[],
            risks=[],
            assumptions=[],
            data={"anything": "goes"},
        )


def make_task(capability: str, input: dict) -> Task:
    return Task(project_id="proj-1", name="t", capability=capability, input=input)


@pytest.fixture()
def manager() -> AgentManager:
    registry = AgentRegistry()
    mgr = AgentManager(registry)
    return mgr


def test_agent_without_declared_schema_is_unaffected(manager: AgentManager):
    manager.register_executor("agent-lenient", LenientAgent())

    result = manager.execute("agent-lenient", make_task("lenient_capability", {"whatever": 1}))

    assert result.data == {"anything": "goes"}


def test_valid_input_passes_schema_validation(manager: AgentManager):
    manager.register_executor("agent-strict", StrictAgent())

    result = manager.execute("agent-strict", make_task("strict_capability", {"required_field": 42}))

    assert result.data == {"score": 0.5}


def test_invalid_input_is_rejected_before_running_the_agent(manager: AgentManager):
    manager.register_executor("agent-strict", StrictAgent())

    with pytest.raises(AgentIOValidationError):
        manager.execute("agent-strict", make_task("strict_capability", {"wrong_field": "x"}))


def test_output_not_matching_declared_schema_is_rejected():
    class BadOutputAgent(Agent):
        capability = "strict_capability"
        input_schema = StrictInputSchema
        output_schema = StrictOutputSchema

        def run(self, task_input: dict) -> AgentResult:
            return AgentResult(
                status="COMPLETED",
                recommendation="GO",
                confidence=0.9,
                evidence=[],
                risks=[],
                assumptions=[],
                data={"not_a_score": "oops"},
            )

    registry = AgentRegistry()
    manager = AgentManager(registry)
    manager.register_executor("agent-bad", BadOutputAgent())

    with pytest.raises(AgentIOValidationError):
        manager.execute("agent-bad", make_task("strict_capability", {"required_field": 1}))
