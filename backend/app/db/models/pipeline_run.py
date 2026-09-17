from sqlalchemy import JSON, Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import IdMixin, TimestampMixin


class PipelineRun(IdMixin, TimestampMixin, Base):
    """One PipelineOrchestrator invocation (Milestone 12, ADR 0005): the
    9 Fase 3 steps (research through CFO) chained automatically instead
    of a human clicking through 9 Control Center pages. `steps` records
    each step's own correlation_id/entity id/status — this table's own
    correlation_id is an additional grouping level, not a replacement
    for each step's individual audit trail."""

    __tablename__ = "pipeline_runs"

    product_id: Mapped[str | None] = mapped_column(ForeignKey("products.id"), nullable=True, index=True)
    category: Mapped[str] = mapped_column(String(64))
    market: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16))
    failed_step: Mapped[str | None] = mapped_column(String(32), nullable=True)
    steps: Mapped[dict] = mapped_column(JSON)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    correlation_id: Mapped[str] = mapped_column(String(36))
