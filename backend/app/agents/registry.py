from app.agents.base import AgentDescriptor, AgentStatus
from app.core.errors import NotFoundError

_EXCLUDED_FROM_ROUTING = {AgentStatus.DISABLED, AgentStatus.FAILED}


class AgentRegistry:
    """Holds known agent descriptors so the CEO can route by capability
    instead of hardcoding a concrete agent implementation."""

    def __init__(self) -> None:
        self._agents: dict[str, AgentDescriptor] = {}

    def register(self, descriptor: AgentDescriptor) -> None:
        self._agents[descriptor.id] = descriptor

    def find_by_capability(self, capability: str, region: str | None = None) -> list[AgentDescriptor]:
        return [
            agent
            for agent in self._agents.values()
            if capability in agent.capabilities
            and agent.status not in _EXCLUDED_FROM_ROUTING
            and (region is None or not agent.regions or region in agent.regions)
        ]

    def set_status(self, agent_id: str, status: AgentStatus) -> None:
        self._get(agent_id).status = status

    def get_health(self, agent_id: str) -> AgentDescriptor:
        return self._get(agent_id)

    def _get(self, agent_id: str) -> AgentDescriptor:
        agent = self._agents.get(agent_id)
        if agent is None:
            raise NotFoundError(f"agent {agent_id} not found")
        return agent
