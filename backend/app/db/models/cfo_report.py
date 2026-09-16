from sqlalchemy import JSON, Float, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import IdMixin, TimestampMixin


class CFOReport(IdMixin, TimestampMixin, Base):
    """Catalog-wide financial-health report — unlike every other Fase 3
    agent's record, this has no product/market FK: it aggregates across all
    products/campaigns/budgets in one run. Traceability comes from
    `data.included_economic_analysis_ids`/`data.included_marketing_campaign_ids`
    instead of a foreign key."""

    __tablename__ = "cfo_reports"

    financial_health_status: Mapped[str] = mapped_column(String(16))
    recommendation: Mapped[str] = mapped_column(String(16))
    confidence: Mapped[float] = mapped_column(Float)
    data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(36))
