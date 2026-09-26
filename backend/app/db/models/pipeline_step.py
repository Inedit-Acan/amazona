import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import IdMixin, TimestampMixin
from app.pipeline.schemas import PipelineStepStatus


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


class PipelineStep(IdMixin, TimestampMixin, Base):
    """Un paso de una ejecución del pipeline (Milestone 32, ADR 0010).

    Hasta el Milestone 31 esto era un JSON (`pipeline_runs.steps`) que se
    escribía una sola vez, al final: si la ejecución moría a mitad, lo que ya
    había hecho quedaba huérfano y no había por dónde reanudar. Ahora cada paso
    es una fila que se escribe cuando el paso empieza y cuando termina, y esa
    fila es la **única** verdad: la API reconstruye el JSON a partir de aquí.

    `detail` guarda lo que el paso expone del negocio (`recommendation`,
    `status`, `candidate_count`) — deliberadamente separado de `status`, que es
    el estado de **ejecución** del paso. Son dos preguntas distintas: un paso
    puede estar COMPLETED y su recomendación ser NO_GO.
    """

    __tablename__ = "pipeline_steps"
    __table_args__ = (
        # Un paso por nombre y por ejecución: reanudar no puede duplicar filas.
        UniqueConstraint("pipeline_run_id", "name", name="uq_pipeline_steps_run_name"),
        # Por aquí entra el bucle de ejecución: los pasos de una ejecución, en orden.
        Index("ix_pipeline_steps_run_ordinal", "pipeline_run_id", "ordinal"),
    )

    pipeline_run_id: Mapped[str] = mapped_column(ForeignKey("pipeline_runs.id"), index=True)
    name: Mapped[str] = mapped_column(String(32))
    #: Posición en la cadena (0 = research). Es lo que hace el orden explícito en
    #: vez de depender del orden de las claves de un JSON.
    ordinal: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default=PipelineStepStatus.PENDING, index=True)

    #: El `correlation_id` propio del paso: cada servicio de Fase 3 genera el
    #: suyo y audita con él (ADR 0005). No se sustituye por el de la ejecución.
    correlation_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    #: La fila que el paso produjo, si produjo alguna.
    entity_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    attempt: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(String(2000), nullable=True)

    started_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PipelineStepAttempt(IdMixin, Base):
    """Cada pasada por un paso (el `PipelineAttempt` del plan maestro §21).

    Un paso que falló dos veces y salió a la tercera tiene tres filas aquí, cada
    una con el trabajo que lo intentó y su error. Sin esto, reanudar borraría la
    historia del intento anterior — y el motivo por el que alguien tuvo que
    reanudar es justamente lo que se quiere leer después.

    No sustituye a `job_attempts`: allí está cada pasada del **trabajo**, aquí
    cada pasada de **un paso**. Un trabajo que muere en el paso 5 tiene un
    intento allí y cinco filas aquí.
    """

    __tablename__ = "pipeline_step_attempts"

    pipeline_step_id: Mapped[str] = mapped_column(ForeignKey("pipeline_steps.id"), index=True)
    #: Qué trabajo lo intentó. Nulo si el paso se ejecutó sin runtime (llamada
    #: directa al orquestador, como en los tests).
    job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id"), nullable=True)
    number: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16))
    error: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    started_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    finished_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
