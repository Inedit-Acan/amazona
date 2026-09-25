from functools import lru_cache

from fastapi import APIRouter
from pydantic import BaseModel

from app.agents.registry import AgentRegistry, build_default_agent_manager

router = APIRouter(prefix="/api/agents", tags=["agents"])


@lru_cache
def _agent_registry() -> AgentRegistry:
    """Built on first use, not on import.

    Constructing it at import time built every agent — and therefore resolved
    every external provider — before `app.main` had a chance to validate the
    configuration, so a misconfigured deployment failed with the message of
    whichever agent happened to be built first instead of the one the startup
    check gives (Milestone 30).
    """
    registry, _ = build_default_agent_manager()
    return registry


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
        for agent in _agent_registry().list_all()
    ]
