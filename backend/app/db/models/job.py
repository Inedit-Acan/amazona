import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import IdMixin
from app.jobs.schemas import JobStatus


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


class Job(IdMixin, Base):
    """Una unidad de ejecución del runtime (Milestone 31, ADR 0009).

    PostgreSQL es la fuente de verdad **y** la cola: el estado que importa
    —incluidos `WAITING_APPROVAL` y `BLOCKED`, que ninguna librería de colas
    modela— tiene que ser durable y consultable de todos modos, y tenerlo en dos
    sitios a la vez es la forma más segura de que se desincronicen.
    """

    __tablename__ = "jobs"
    __table_args__ = (
        # Por este índice entra el reclamo: estado + cuándo está disponible.
        Index("ix_jobs_claim", "status", "available_at"),
        Index("ix_jobs_lease", "status", "lease_expires_at"),
    )

    type: Mapped[str] = mapped_column(String(100), index=True)
    status: Mapped[str] = mapped_column(String(20), default=JobStatus.QUEUED, index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    correlation_id: Mapped[str] = mapped_column(String(36), index=True)

    #: Encolar dos veces con la misma clave devuelve el mismo trabajo. Es lo que
    #: hace seguro reintentar una petición HTTP que no se sabe si llegó.
    idempotency_key: Mapped[str | None] = mapped_column(String(200), unique=True, nullable=True)

    attempt: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)

    #: A partir de cuándo puede reclamarse. Es lo que implementa la espera entre
    #: reintentos sin necesidad de un temporizador aparte.
    available_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    #: Arriendo: qué worker lo tiene y hasta cuándo. Un arriendo vencido es un
    #: worker muerto, y el segador lo devuelve a la cola.
    lease_worker: Mapped[str | None] = mapped_column(String(100), nullable=True)
    lease_expires_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    started_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    error: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    #: Dónde vive el resultado, no el resultado: un correlation_id, el id de una
    #: fila. La tabla de trabajos no es un almacén de payloads.
    result_reference: Mapped[str | None] = mapped_column(String(200), nullable=True)

    #: Identidad verificada de quien lo encoló (Milestone 29).
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)


class JobAttempt(IdMixin, Base):
    """Cada pasada por un worker. Un trabajo que falló tres veces tiene tres
    filas aquí, con su error y quién lo intentó — sin eso, un reintento borra la
    historia del anterior."""

    __tablename__ = "job_attempts"

    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    worker: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20))
    started_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    finished_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(String(2000), nullable=True)


class JobEvent(IdMixin, Base):
    """Bitácora de solo añadir de lo que le pasó a un trabajo y cuándo."""

    __tablename__ = "job_events"

    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), index=True)
    kind: Mapped[str] = mapped_column(String(30))
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
