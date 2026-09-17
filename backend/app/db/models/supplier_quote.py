from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import IdMixin, TimestampMixin


class SupplierQuote(IdMixin, TimestampMixin, Base):
    __tablename__ = "supplier_quotes"

    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), index=True)
    supplier_id: Mapped[str] = mapped_column(ForeignKey("suppliers.id"))
    analysis_type: Mapped[str] = mapped_column(String(32), default="sourcing")
    unit_price: Mapped[float] = mapped_column(Float)
    moq: Mapped[int] = mapped_column(Integer)
    lead_time_days: Mapped[int] = mapped_column(Integer)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    reliability_score: Mapped[float] = mapped_column(Float, default=0.0)
    logistics_cost_per_unit: Mapped[float] = mapped_column(Float)
    total_landed_cost_per_unit: Mapped[float] = mapped_column(Float)
    data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(36))
