from sqlalchemy import JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import IdMixin, TimestampMixin


class MemoryRecord(IdMixin, TimestampMixin, Base):
    __tablename__ = "memory_records"
    __table_args__ = (UniqueConstraint("scope", "scope_id", "key", name="uq_memory_records_scope_key"),)

    scope: Mapped[str] = mapped_column(String(50))
    scope_id: Mapped[str] = mapped_column(String(36))
    key: Mapped[str] = mapped_column(String(100))
    value: Mapped[dict] = mapped_column(JSON)
