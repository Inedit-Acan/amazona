from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.db.models.project import Project as ProjectModel
from app.db.session import get_db

router = APIRouter(prefix="/api/projects", tags=["projects"])


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    objective_id: str
    name: str
    status: str


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(project_id: str, db: Session = Depends(get_db)) -> ProjectModel:
    project = db.get(ProjectModel, project_id)
    if project is None:
        raise NotFoundError(f"project {project_id} not found")
    return project
