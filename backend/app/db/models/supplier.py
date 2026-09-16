from sqlalchemy import JSON, Boolean, Float, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import IdMixin, TimestampMixin


class Supplier(IdMixin, TimestampMixin, Base):
    __tablename__ = "suppliers"

    name: Mapped[str] = mapped_column(String(255))
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    region: Mapped[str | None] = mapped_column(String(100), nullable=True)
    contact_info: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    reliability_score: Mapped[float] = mapped_column(Float, default=0.0)
