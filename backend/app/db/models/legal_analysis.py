from sqlalchemy import JSON, Boolean, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import IdMixin, TimestampMixin


class LegalAnalysis(IdMixin, TimestampMixin, Base):
    __tablename__ = "legal_analyses"

    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), index=True)
    supplier_quote_id: Mapped[str | None] = mapped_column(ForeignKey("supplier_quotes.id"), nullable=True)
    market: Mapped[str] = mapped_column(String(16))
    analysis_type: Mapped[str] = mapped_column(String(32), default="legal_compliance")
    restricted: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    recommendation: Mapped[str] = mapped_column(String(16))
    confidence: Mapped[float] = mapped_column(Float)
    data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(36))
