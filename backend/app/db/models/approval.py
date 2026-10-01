import datetime

from sqlalchemy import DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import IdMixin, TimestampMixin


class Approval(IdMixin, TimestampMixin, Base):
    """La autorización humana de una **decisión del CEO** (ADR 0027): decide si un proyecto sigue adelante y, si
    lleva dinero, cuánto. Lo crea el CEO con el importe **ya reservado** en el libro (`approval:{id}`); resolverla lo
    compromete (aprobar) o lo libera (rechazar o caducar), una sola vez, con compare-and-set. Caduca (`expires_at`).

    **No es** la autorización de un paso del pipeline: eso es `PipelineReview`. Ninguno de los dos lados importa al
    otro, y aprobar una de las dos no desbloquea nada de la otra (`tests/unit/test_approval_boundary.py`).
    """

    __tablename__ = "approvals"

    decision_id: Mapped[str] = mapped_column(ForeignKey("decisions.id"))
    action: Mapped[str] = mapped_column(String(255))
    amount: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="PENDING")
    requested_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.UTC)
    )
    expires_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(36))
