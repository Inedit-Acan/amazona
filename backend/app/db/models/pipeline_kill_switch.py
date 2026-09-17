from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import IdMixin, TimestampMixin


class PipelineKillSwitch(IdMixin, TimestampMixin, Base):
    """A single canonical row (Milestone 14, ADR 0006) gating whether
    PipelineOrchestrator.run_pipeline() may start a new run — the first
    kill switch in the system. Get-or-create by `name`, same pattern
    BudgetLedgerService (Milestone 11) uses for its canonical Budget row."""

    __tablename__ = "pipeline_kill_switch"

    name: Mapped[str] = mapped_column(String(64))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
