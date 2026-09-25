import datetime

from sqlalchemy import JSON, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import IdMixin


class AuditLog(IdMixin, Base):
    """Append-only audit trail. Rows are never updated or deleted."""

    __tablename__ = "audit_log"

    actor: Mapped[str] = mapped_column(String(255))
    #: Role the actor held when it acted, and where its identity came from
    #: (token / declared / cli / system). Nullable: rows written before
    #: Milestone 29 predate verified identity and are never rewritten.
    actor_role: Mapped[str | None] = mapped_column(String(50), nullable=True)
    actor_source: Mapped[str | None] = mapped_column(String(20), nullable=True)
    action: Mapped[str] = mapped_column(String(255))
    resource: Mapped[str] = mapped_column(String(255))
    before: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    after: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(36), index=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.UTC)
    )
