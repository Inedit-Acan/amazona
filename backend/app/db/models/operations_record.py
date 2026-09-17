from sqlalchemy import JSON, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import IdMixin, TimestampMixin


class OperationsRecord(IdMixin, TimestampMixin, Base):
    __tablename__ = "operations_records"

    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), index=True)
    marketing_campaign_id: Mapped[str | None] = mapped_column(
        ForeignKey("marketing_campaigns.id"), nullable=True
    )
    market: Mapped[str] = mapped_column(String(16))
    operations_status: Mapped[str] = mapped_column(String(16))
    recommendation: Mapped[str] = mapped_column(String(16))
    confidence: Mapped[float] = mapped_column(Float)
    data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(36))
