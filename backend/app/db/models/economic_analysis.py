from sqlalchemy import JSON, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import IdMixin, TimestampMixin


class EconomicAnalysis(IdMixin, TimestampMixin, Base):
    __tablename__ = "economic_analyses"

    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), index=True)
    supplier_quote_id: Mapped[str] = mapped_column(ForeignKey("supplier_quotes.id"))
    analysis_type: Mapped[str] = mapped_column(String(32), default="economic_risk")
    sale_price: Mapped[float] = mapped_column(Float)
    monthly_fixed_costs: Mapped[float] = mapped_column(Float)
    margin_percent: Mapped[float] = mapped_column(Float)
    recommendation: Mapped[str] = mapped_column(String(16))
    confidence: Mapped[float] = mapped_column(Float)
    data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(36))
