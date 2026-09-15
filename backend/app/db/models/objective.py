from sqlalchemy import JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import IdMixin, TimestampMixin


class Objective(IdMixin, TimestampMixin, Base):
    __tablename__ = "objectives"

    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), default="RECEIVED")
    context: Mapped[dict | None] = mapped_column(JSON, nullable=True)
