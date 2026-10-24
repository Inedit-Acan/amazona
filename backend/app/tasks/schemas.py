from enum import StrEnum

from pydantic import BaseModel, Field

from app.core.ids import new_id


class TaskStatus(StrEnum):
    PENDING = "PENDING"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    BLOCKED = "BLOCKED"


class Task(BaseModel):
    id: str = Field(default_factory=new_id)
    project_id: str
    name: str
    capability: str
    status: TaskStatus = TaskStatus.PENDING
    depends_on: list[str] = Field(default_factory=list)
    input: dict = Field(default_factory=dict)
    output: dict | None = None
    error: str | None = None
    assigned_agent_id: str | None = None
    retry_count: int = 0
    #: El objetivo de la misión a la que pertenece (M51A): el fault injection de ensayo se arma por objetivo.
    #: `None` fuera de una misión del orquestador.
    objective_id: str | None = None
