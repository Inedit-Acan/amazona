from sqlalchemy import JSON, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import IdMixin, TimestampMixin


class Agent(IdMixin, TimestampMixin, Base):
    __tablename__ = "agents"

    name: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(100))
    version: Mapped[str] = mapped_column(String(50), default="1.0.0")
    status: Mapped[str] = mapped_column(String(32), default="AVAILABLE")
    reliability_score: Mapped[float] = mapped_column(Float, default=1.0)
    cost_profile: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    latency_profile: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    regions: Mapped[list | None] = mapped_column(JSON, nullable=True)


class AgentCapability(IdMixin, Base):
    __tablename__ = "agent_capabilities"

    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"))
    capability: Mapped[str] = mapped_column(String(100))
