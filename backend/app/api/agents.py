from fastapi import APIRouter
from pydantic import BaseModel

from app.agents.registry import build_default_agent_manager

router = APIRouter(prefix="/api/agents", tags=["agents"])

_registry, _ = build_default_agent_manager()


class AgentOut(BaseModel):
    id: str
    name: str
    role: str
    capabilities: list[str]
    status: str
    reliability_score: float
    version: str
    cost_profile: dict


@router.get("", response_model=list[AgentOut])
def list_agents() -> list[AgentOut]:
    return [
        AgentOut(
            id=agent.id,
            name=agent.name,
            role=agent.role,
            capabilities=agent.capabilities,
            status=agent.status.value,
            reliability_score=agent.reliability_score,
            version=agent.version,
            cost_profile=agent.cost_profile,
        )
        for agent in _registry.list_all()
    ]
