from sqlalchemy import Boolean, Float, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import IdMixin, TimestampMixin


class AgentExecutionLog(IdMixin, TimestampMixin, Base):
    __tablename__ = "agent_execution_log"

    agent_id: Mapped[str] = mapped_column(String(36))
    capability: Mapped[str] = mapped_column(String(100))
    duration_ms: Mapped[float] = mapped_column(Float)
    success: Mapped[bool] = mapped_column(Boolean)
    correlation_id: Mapped[str] = mapped_column(String(36))
