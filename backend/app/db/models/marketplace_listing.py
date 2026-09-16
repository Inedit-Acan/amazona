from sqlalchemy import JSON, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import IdMixin, TimestampMixin


class MarketplaceListing(IdMixin, TimestampMixin, Base):
    __tablename__ = "marketplace_listings"

    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"))
    storefront_id: Mapped[str | None] = mapped_column(ForeignKey("storefronts.id"), nullable=True)
    market: Mapped[str] = mapped_column(String(16))
    platform: Mapped[str] = mapped_column(String(32), default="amazon")
    listing_status: Mapped[str] = mapped_column(String(16))
    recommendation: Mapped[str] = mapped_column(String(16))
    confidence: Mapped[float] = mapped_column(Float)
    data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(36))
