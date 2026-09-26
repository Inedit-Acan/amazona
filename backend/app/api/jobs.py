import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.auth.actor import Actor
from app.auth.dependencies import authorize
from app.core.errors import NotFoundError
from app.db.models.job import Job as JobModel
from app.db.models.job import JobAttempt as JobAttemptModel
from app.db.models.job import JobEvent as JobEventModel
from app.db.session import get_db
from app.jobs import handlers as _handlers  # noqa: F401 - importar registra los tipos
from app.jobs.queue import JobQueue
from app.jobs.registry import UnknownJobTypeError, known_types, resolve
from app.jobs.schemas import JobStatus
from app.permissions.policies import ApiAction

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


class JobCreate(BaseModel):
    type: str
    payload: dict = Field(default_factory=dict)
    #: Encolar dos veces con la misma clave devuelve el mismo trabajo.
    idempotency_key: str | None = None
    max_attempts: int = Field(default=3, ge=1, le=10)


class JobAttemptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    number: int
    worker: str
    status: str
    started_at: datetime.datetime
    finished_at: datetime.datetime | None
    error: str | None


class JobEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    kind: str
    detail: dict | None
    created_at: datetime.datetime


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    type: str
    status: str
    payload: dict
    correlation_id: str
    attempt: int
    max_attempts: int
    available_at: datetime.datetime
    created_at: datetime.datetime
    started_at: datetime.datetime | None
    completed_at: datetime.datetime | None
    failed_at: datetime.datetime | None
    cancelled_at: datetime.datetime | None
    error: str | None
    result_reference: str | None
    created_by: str | None


class JobDetailOut(JobOut):
    attempts: list[JobAttemptOut]
    events: list[JobEventOut]


class JobTypesOut(BaseModel):
    types: list[str]


def _detail(job: JobModel, db: Session) -> JobDetailOut:
    attempts = db.query(JobAttemptModel).filter_by(job_id=job.id).order_by(JobAttemptModel.number).all()
    events = db.query(JobEventModel).filter_by(job_id=job.id).order_by(JobEventModel.created_at).all()
    return JobDetailOut(
        **JobOut.model_validate(job).model_dump(),
        attempts=[JobAttemptOut.model_validate(a) for a in attempts],
        events=[JobEventOut.model_validate(e) for e in events],
    )


@router.get("/types", response_model=JobTypesOut)
def list_job_types() -> JobTypesOut:
    """Qué sabe ejecutar este despliegue. Encolar un tipo que no esté aquí
    falla en el acto."""
    return JobTypesOut(types=known_types())


@router.get("", response_model=list[JobOut])
def list_jobs(
    status: JobStatus | None = None,
    job_type: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[JobModel]:
    query = db.query(JobModel)
    if status is not None:
        query = query.filter(JobModel.status == status)
    if job_type is not None:
        query = query.filter(JobModel.type == job_type)
    return query.order_by(JobModel.created_at.desc()).limit(limit).all()


@router.get("/{job_id}", response_model=JobDetailOut)
def get_job(job_id: str, db: Session = Depends(get_db)) -> JobDetailOut:
    job = db.get(JobModel, job_id)
    if job is None:
        raise NotFoundError(f"job {job_id} not found")
    return _detail(job, db)


@router.post("", response_model=JobOut, status_code=201)
def create_job(
    payload: JobCreate,
    db: Session = Depends(get_db),
    identity: Actor = Depends(authorize(ApiAction.JOB_WRITE)),
) -> JobModel:
    """Encola un trabajo. No lo ejecuta: de eso se encarga un worker."""
    # Un tipo desconocido se rechaza aquí y no en el worker: el que llama se
    # entera en el acto en vez de que el trabajo muera en la cola.
    try:
        resolve(payload.type)
    except UnknownJobTypeError as exc:
        raise NotFoundError(str(exc)) from exc

    return JobQueue(db).enqueue(
        job_type=payload.type,
        payload=payload.payload,
        idempotency_key=payload.idempotency_key,
        max_attempts=payload.max_attempts,
        created_by=identity.audit_name,
    )


@router.post("/{job_id}/cancel", response_model=JobOut)
def cancel_job(
    job_id: str,
    db: Session = Depends(get_db),
    identity: Actor = Depends(authorize(ApiAction.JOB_WRITE)),
) -> JobModel:
    try:
        return JobQueue(db).cancel(job_id, actor=identity.audit_name)
    except LookupError as exc:
        raise NotFoundError(str(exc)) from exc


@router.post("/{job_id}/requeue", response_model=JobOut)
def requeue_job(
    job_id: str,
    db: Session = Depends(get_db),
    identity: Actor = Depends(authorize(ApiAction.JOB_WRITE)),
) -> JobModel:
    """Devuelve a la cola un trabajo fallado o cancelado. Es cómo se vacía la
    cola de mensajes muertos, que aquí es sencillamente el conjunto de trabajos
    en FAILED."""
    try:
        return JobQueue(db).requeue(job_id, actor=identity.audit_name)
    except LookupError as exc:
        raise NotFoundError(str(exc)) from exc
