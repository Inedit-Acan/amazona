import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import IdMixin, TimestampMixin


class PipelineReview(IdMixin, TimestampMixin, Base):
    """Human review gate for a risky PipelineRun (Milestone 14, ADR 0006)
    — same approve/reject/expire lifecycle as `Approval`, but FKs to
    `pipeline_runs.id` instead of `decisions.id` (Approval's FK is
    non-nullable and tied to the Milestone-1 Decision domain, which a
    PipelineRun is not part of). Resolving a review is a governance
    annotation — it does not revert or retry the pipeline run, which is
    already a completed fact."""

    __tablename__ = "pipeline_reviews"

    pipeline_run_id: Mapped[str] = mapped_column(ForeignKey("pipeline_runs.id"))
    #: Qué clase de decisión se pide (Milestone 33):
    #:
    #: - `POST_HOC`: mirar una ejecución de riesgo que **ya terminó** (M14). No
    #:   revierte nada; es gobernanza.
    #: - `ACTION_GATE`: autorizar una acción con efecto que **todavía no se ha
    #:   ejecutado**. Aprobarla continúa la ejecución; rechazarla deja ese paso
    #:   denegado.
    #:
    #: Viven en la misma tabla y en la misma bandeja porque para quien decide
    #: son la misma pregunta —«¿esto sigue adelante?»—, y separarlas habría
    #: significado dos bandejas que revisar en vez de una.
    kind: Mapped[str] = mapped_column(String(16), default="POST_HOC", index=True)
    #: Sobre qué paso, y qué acción con efecto. Nulos en las post-hoc: esas
    #: hablan de la ejecución entera.
    step: Mapped[str | None] = mapped_column(String(32), nullable=True)
    action: Mapped[str | None] = mapped_column(String(40), nullable=True)
    reasons: Mapped[list] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), default="PENDING")
    resolved_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(36))
