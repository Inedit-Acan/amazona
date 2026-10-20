import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.db.models.agent_execution_log import AgentExecutionLog as AgentExecutionLogModel
from app.db.session import get_db

router = APIRouter(prefix="/api/agent-executions", tags=["monitoring"])


class AgentExecutionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    agent_id: str
    capability: str
    duration_ms: float
    success: bool
    correlation_id: str
    created_at: datetime.datetime
    #: El vinculo EXPLICITO con la tarea (M48, Commit 7), la foto de la asignacion vigente al ejecutar, el intento y
    #: las horas. Nulos en las ejecuciones anteriores al vinculo: no se rellenan a posteriori.
    task_id: str | None = None
    assigned_agent_id: str | None = None
    attempt: int | None = None
    started_at: datetime.datetime | None = None
    completed_at: datetime.datetime | None = None


@router.get("", response_model=list[AgentExecutionOut])
def list_agent_executions(
    correlation_id: str | None = None, db: Session = Depends(get_db)
) -> list[AgentExecutionLogModel]:
    query = db.query(AgentExecutionLogModel)
    if correlation_id is not None:
        query = query.filter(AgentExecutionLogModel.correlation_id == correlation_id)
    return query.order_by(AgentExecutionLogModel.created_at.desc()).limit(100).all()
