from sqlalchemy import JSON, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import IdMixin, TimestampMixin


class ProductAnalysis(IdMixin, TimestampMixin, Base):
    __tablename__ = "product_analyses"

    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"))
    objective_id: Mapped[str | None] = mapped_column(ForeignKey("objectives.id"), nullable=True)
    analysis_type: Mapped[str] = mapped_column(String(32))
    opportunity_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
