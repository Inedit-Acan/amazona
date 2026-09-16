from pydantic import ValidationError

from app.agents.base import Agent, AgentDescriptor, AgentResult, AgentStatus
from app.agents.registry import AgentRegistry
from app.core.errors import AgentIOValidationError, NoAgentAvailableError, NotFoundError
from app.tasks.schemas import Task


def _simulated_cost(agent: AgentDescriptor) -> float:
    return float(agent.cost_profile.get("simulated_cost_per_task", 0.0))


class AgentManager:
    """Routes tasks to the best available agent for a capability.

    Selection is deterministic for a fixed registry state: highest
    reliability first, then lowest simulated cost, then agent id as a
    stable tiebreaker.
    """

    def __init__(self, registry: AgentRegistry) -> None:
        self._registry = registry
        self._executors: dict[str, Agent] = {}

    def register_executor(self, agent_id: str, executor: Agent) -> None:
        self._executors[agent_id] = executor

    def select_agent(self, capability: str, context: dict | None = None) -> AgentDescriptor:
        context = context or {}
        candidates = [
            agent
            for agent in self._registry.find_by_capability(capability, region=context.get("region"))
            if agent.status == AgentStatus.AVAILABLE
        ]
        if not candidates:
            raise NoAgentAvailableError(f"no available agent for capability {capability!r}")

        candidates.sort(key=lambda agent: (-agent.reliability_score, _simulated_cost(agent), agent.id))
        return candidates[0]

    def execute(self, agent_id: str, task: Task) -> AgentResult:
        executor = self._executors.get(agent_id)
        if executor is None:
            raise NotFoundError(f"no executor registered for agent {agent_id}")

        if executor.input_schema is not None:
            try:
                executor.input_schema.model_validate(task.input)
            except ValidationError as exc:
                raise AgentIOValidationError(
                    f"agent {agent_id} input does not match {executor.input_schema.__name__}: {exc}"
                ) from exc

        result = executor.run(task.input)

        if executor.output_schema is not None:
            try:
                executor.output_schema.model_validate(result.data)
            except ValidationError as exc:
                raise AgentIOValidationError(
                    f"agent {agent_id} output does not match {executor.output_schema.__name__}: {exc}"
                ) from exc

        return result
