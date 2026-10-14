import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, field_validator
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
    # El momento en que se insertó el proyecto (`projects.created_at`, NOT NULL): ninguna otra fecha lo sustituye.
    created_at: datetime.datetime

    @field_validator("created_at")
    @classmethod
    def _as_aware_utc(cls, value: datetime.datetime) -> datetime.datetime:
        """SQLite descarta la zona al leer; todo lo que se guarda aquí es UTC (default `datetime.now(UTC)`).
        Sin esto el cliente leería `2026-09-12T10:00:00` como hora local y la fecha se desplazaría."""
        return value if value.tzinfo is not None else value.replace(tzinfo=datetime.UTC)


@router.get("", response_model=list[ProjectOut])
def list_projects(db: Session = Depends(get_db)) -> list[ProjectModel]:
    return db.query(ProjectModel).order_by(ProjectModel.created_at.desc()).all()


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(project_id: str, db: Session = Depends(get_db)) -> ProjectModel:
    project = db.get(ProjectModel, project_id)
    if project is None:
        raise NotFoundError(f"project {project_id} not found")
    return project
