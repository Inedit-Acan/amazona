import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import IdMixin, TimestampMixin


class Task(IdMixin, TimestampMixin, Base):
    __tablename__ = "tasks"

    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"))
    name: Mapped[str] = mapped_column(String(255))
    capability: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(32), default="PENDING")
    #: La asignación VIGENTE: qué agente debe ejecutar la tarea (M48, Commit 7). No es quién la ejecutó: eso es
    #: `agent_execution_log`, y lo que pasó antes está en la auditoría (`task.assigned` / `task.reassigned`). Es el id
    #: del REGISTRO de agentes (en el código), no de la tabla `agents`, que el sistema no puebla: por eso no es una
    #: clave ajena. Que el agente exista lo exige `TaskAssignmentService` al escribir y lo vuelve a comprobar cada
    #: lectura. `NULL` = sin asignar (o de un agente del orquestador, ver `app/tasks/assignment.py`).
    assigned_agent_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    input: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    output: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TaskDependency(IdMixin, Base):
    __tablename__ = "task_dependencies"

    parent_task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"))
    child_task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"))
