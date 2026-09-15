from enum import StrEnum

from pydantic import BaseModel, Field


class ProjectStatus(StrEnum):
    DRAFT = "DRAFT"
    VALIDATING = "VALIDATING"
    APPROVED = "APPROVED"
    EXECUTING = "EXECUTING"
    MONITORING = "MONITORING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"


class DecisionStatus(StrEnum):
    GO = "GO"
    REVIEW = "REVIEW"
    NO_GO = "NO_GO"
    HUMAN_APPROVAL = "HUMAN_APPROVAL"


class ApprovalStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class Objective(BaseModel):
    id: str
    title: str
    description: str | None = None


class TaskSpec(BaseModel):
    name: str
    capability: str
    input: dict = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)


class ProjectPlan(BaseModel):
    project_name: str
    tasks: list[TaskSpec]
