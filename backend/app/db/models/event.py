from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import IdMixin, TimestampMixin


class Event(IdMixin, TimestampMixin, Base):
    __tablename__ = "events"

    type: Mapped[str] = mapped_column(String(100))
    correlation_id: Mapped[str] = mapped_column(String(36))
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
