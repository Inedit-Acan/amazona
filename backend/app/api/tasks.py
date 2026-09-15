from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.db.models.task import Task as TaskModel
from app.db.session import get_db

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    name: str
    capability: str
    status: str
    input: dict | None
    output: dict | None
    error: str | None


@router.get("", response_model=list[TaskOut])
def list_tasks(project_id: str, db: Session = Depends(get_db)) -> list[TaskModel]:
    return db.query(TaskModel).filter(TaskModel.project_id == project_id).all()
