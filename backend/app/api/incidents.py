import datetime
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.core.errors import IncidentNotOpenError, NotFoundError
from app.core.ids import new_correlation_id
from app.db.models.audit import AuditLog
from app.db.models.incident import Incident as IncidentModel
from app.db.session import get_db

router = APIRouter(prefix="/api/incidents", tags=["incidents"])

Severity = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]


class IncidentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    description: str | None
    severity: str
    status: str
    resolved_at: datetime.datetime | None
    created_at: datetime.datetime


class IncidentCreate(BaseModel):
    title: str
    description: str | None = None
    severity: Severity
    actor: str


class IncidentResolveIn(BaseModel):
    actor: str


@router.get("", response_model=list[IncidentOut])
def list_incidents(db: Session = Depends(get_db)) -> list[IncidentModel]:
    return db.query(IncidentModel).order_by(IncidentModel.created_at.desc()).all()


@router.post("", response_model=IncidentOut, status_code=201)
def create_incident(payload: IncidentCreate, db: Session = Depends(get_db)) -> IncidentModel:
    """v1: manual reporting only — a human records what they observed.
    Deliberately does not auto-create incidents from system signals (e.g.
    ServiceMap showing the backend down, or a stale PipelineReview) —
    that's a "when does this count as an incident" design decision of
    its own, out of scope here (see docs/design/
    AMAZONA_handoff_backend_paneles_pendientes.md §4)."""
    correlation_id = new_correlation_id()
    incident = IncidentModel(
        title=payload.title,
        description=payload.description,
        severity=payload.severity,
        status="OPEN",
    )
    db.add(incident)
    db.flush()

    db.add(
        AuditLog(
            actor=payload.actor,
            action="incident.create",
            resource=f"incident:{incident.id}",
            before=None,
            after={"title": payload.title, "severity": payload.severity},
            correlation_id=correlation_id,
        )
    )
    db.commit()
    db.refresh(incident)
    return incident


@router.post("/{incident_id}/resolve", response_model=IncidentOut)
def resolve_incident(incident_id: str, payload: IncidentResolveIn, db: Session = Depends(get_db)) -> IncidentModel:
    incident = db.get(IncidentModel, incident_id)
    if incident is None:
        raise NotFoundError(f"incident {incident_id} not found")
    if incident.status != "OPEN":
        raise IncidentNotOpenError(f"incident {incident_id} is not open (status={incident.status})")

    before_status = incident.status
    incident.status = "RESOLVED"
    incident.resolved_at = datetime.datetime.now(datetime.UTC)

    db.add(
        AuditLog(
            actor=payload.actor,
            action="incident.resolve",
            resource=f"incident:{incident.id}",
            before={"status": before_status},
            after={"status": "RESOLVED"},
            correlation_id=new_correlation_id(),
        )
    )
    db.commit()
    db.refresh(incident)
    return incident
