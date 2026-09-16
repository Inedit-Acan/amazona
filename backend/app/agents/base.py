from abc import ABC, abstractmethod
from enum import StrEnum
from typing import ClassVar

from pydantic import BaseModel, Field


class AgentStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    BUSY = "BUSY"
    WAITING = "WAITING"
    BLOCKED = "BLOCKED"
    DEGRADED = "DEGRADED"
    DISABLED = "DISABLED"
    FAILED = "FAILED"


class AgentResultStatus(StrEnum):
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"


class AgentResult(BaseModel):
    """Structured outcome of an agent executing one task. Decision-critical:
    the CEO never accepts free-form agent output."""

    status: AgentResultStatus
    recommendation: str
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[str]
    risks: list[str]
    assumptions: list[str]
    data: dict


class AgentDescriptor(BaseModel):
    id: str
    name: str
    role: str
    version: str
    capabilities: list[str]
    permissions: list[str] = Field(default_factory=list)
    status: AgentStatus = AgentStatus.AVAILABLE
    reliability_score: float = Field(default=1.0, ge=0.0, le=1.0)
    cost_profile: dict = Field(default_factory=dict)
    latency_profile: dict = Field(default_factory=dict)
    regions: list[str] = Field(default_factory=list)


class Agent(ABC):
    """Base interface every simulated or real specialist agent implements.

    `input_schema`/`output_schema` are optional (see ADR 0002): when
    declared, the AgentManager validates task_input / AgentResult.data
    against them before/after calling `run()`. Agents that don't declare
    them (Milestone 1's four specialists) are unaffected.
    """

    capability: str
    input_schema: ClassVar[type[BaseModel] | None] = None
    output_schema: ClassVar[type[BaseModel] | None] = None

    @abstractmethod
    def run(self, task_input: dict) -> AgentResult:
        raise NotImplementedError
