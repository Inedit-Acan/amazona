import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String
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
    #: La tarea que se ejecutó (M48, Commit 7): un vínculo EXPLÍCITO, no una correlación por capacidad o por
    #: `correlation_id`. `NULL` en lo anterior a este commit y en cualquier ejecución que no sea de una tarea; nunca
    #: se rellena a posteriori por coincidencia.
    task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id"), nullable=True, index=True)
    #: La FOTO de la asignación vigente en el momento de ejecutar. Si es distinta de `agent_id` (o es `NULL`), esa
    #: ejecución fue de otro agente del asignado y queda a la vista. Una reasignación posterior no la cambia.
    assigned_agent_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    #: El intento de la tarea (1 = el primero). Un reintento es OTRA fila: nunca se sobrescribe la anterior.
    attempt: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
