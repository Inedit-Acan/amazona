from sqlalchemy import JSON, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import IdMixin, TimestampMixin


class Decision(IdMixin, TimestampMixin, Base):
    __tablename__ = "decisions"

    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"))
    status: Mapped[str] = mapped_column(String(32))
    opportunity_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(36))


class DecisionEvidence(IdMixin, TimestampMixin, Base):
    __tablename__ = "decision_evidence"

    decision_id: Mapped[str] = mapped_column(ForeignKey("decisions.id"))
    source: Mapped[str] = mapped_column(String(100))
    summary: Mapped[str] = mapped_column(Text)
    data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
