from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.models.task import Task as TaskModel
from app.db.models.task import TaskDependency as TaskDependencyModel
from app.db.session import get_db

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


class TaskOut(BaseModel):
    id: str
    project_id: str
    name: str
    capability: str
    status: str
    input: dict | None
    output: dict | None
    error: str | None
    depends_on: list[str]


@router.get("", response_model=list[TaskOut])
def list_tasks(project_id: str, db: Session = Depends(get_db)) -> list[TaskOut]:
    tasks = db.query(TaskModel).filter(TaskModel.project_id == project_id).all()
    dependencies = (
        db.query(TaskDependencyModel)
        .filter(TaskDependencyModel.child_task_id.in_([t.id for t in tasks]))
        .all()
    )
    depends_on_by_task: dict[str, list[str]] = {}
    for dep in dependencies:
        depends_on_by_task.setdefault(dep.child_task_id, []).append(dep.parent_task_id)

    return [
        TaskOut(
            id=t.id,
            project_id=t.project_id,
            name=t.name,
            capability=t.capability,
            status=t.status,
            input=t.input,
            output=t.output,
            error=t.error,
            depends_on=depends_on_by_task.get(t.id, []),
        )
        for t in tasks
    ]
