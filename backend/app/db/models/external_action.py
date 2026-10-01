import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import IdMixin


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


class ExternalAction(IdMixin, Base):
    """Una **operación** con efecto fuera del sistema —publicar, activar publicidad, gastar—
    y en qué punto de su vida está (hardening pre-M44, ADR 0024).

    Es el mínimo que hace falta para responder, tras una caída o un timeout, a la pregunta
    que decide si se puede liberar un presupuesto o volver a intentar: **¿llegó a salir la
    petición hacia el proveedor?**

    - `PENDING`: existe y tiene su reserva, pero la petición **todavía no ha salido**. Si el
      proceso muere aquí, no se ejecutó nada y se puede liberar.
    - `CALLING`: se confirmó (commit) que la petición está a punto de salir o ha salido. Si el
      proceso muere aquí, **no se sabe** qué hizo el proveedor.
    - `SUCCEEDED` / `FAILED_CONFIRMED`: el proveedor lo confirmó (o no llegó a ser alcanzado).
    - `UNKNOWN_OUTCOME`: pudo ejecutarse y no conocemos la respuesta. No se reintenta a ciegas, no
      se libera el presupuesto y no se declara éxito: hay que reconciliarlo.

    `reference` identifica el «sitio» de la operación (`pipeline_step:{correlation}:{step}`) y
    `sequence` la operación concreta en ese sitio: rehacer el paso a propósito es **otra**
    operación (otra secuencia, otra clave hacia el proveedor); reintentar la misma, no. La
    `idempotency_key` que se manda al proveedor sale de `(reference, sequence)`, así que es
    estable entre reintentos y reinicios. La reserva del libro usa `action:{id}`: una reserva
    por operación.
    """

    __tablename__ = "external_actions"

    reference: Mapped[str] = mapped_column(sa.String(255), index=True)
    sequence: Mapped[int] = mapped_column(sa.Integer)
    provider: Mapped[str] = mapped_column(sa.String(64))
    operation: Mapped[str] = mapped_column(sa.String(64))
    #: La clave que se manda al proveedor. Opaca y estable: no lleva ningún dato de nadie.
    idempotency_key: Mapped[str] = mapped_column(sa.String(80))
    #: Si el adaptador garantiza que repetir la misma clave no repite el efecto. Se registra
    #: en la operación porque de ello depende qué reconciliaciones son seguras.
    provider_idempotent: Mapped[bool] = mapped_column(sa.Boolean)
    request_fingerprint: Mapped[str] = mapped_column(sa.String(64))
    amount: Mapped[float | None] = mapped_column(sa.Numeric(12, 2), nullable=True)
    status: Mapped[str] = mapped_column(sa.String(24), default="PENDING")
    correlation_id: Mapped[str] = mapped_column(sa.String(36))
    error: Mapped[str | None] = mapped_column(sa.String(2000), nullable=True)
    call_started_at: Mapped[datetime.datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime.datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    #: Cuándo el paso **registró localmente** este resultado. Una operación `SUCCEEDED` sin `applied_at` es un
    #: efecto que ya ocurrió y cuyo registro local no se completó: reintentar el paso solo debe completar ese
    #: registro, **no repetir el efecto**.
    applied_at: Mapped[datetime.datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    #: Quién cerró un resultado que no llegó solo (una persona o el reconciliador).
    resolved_by: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    resolved_at: Mapped[datetime.datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(sa.DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime.datetime] = mapped_column(sa.DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    @property
    def reservation_reference(self) -> str:
        """La referencia con la que esta operación reserva, compromete o libera en el libro."""
        return f"action:{self.id}"

    __table_args__ = (
        sa.UniqueConstraint("idempotency_key", name="uq_external_actions_idempotency_key"),
        sa.UniqueConstraint("reference", "sequence", name="uq_external_actions_reference_sequence"),
        # A lo sumo una operación abierta por «sitio»: dos ejecutores no pueden tener entre manos
        # la misma acción a la vez, ni abrirse otra mientras una sigue sin resolver.
        sa.Index(
            "uq_external_actions_one_open_per_reference",
            "reference",
            unique=True,
            postgresql_where=sa.text("status IN ('PENDING', 'CALLING', 'UNKNOWN_OUTCOME')"),
            sqlite_where=sa.text("status IN ('PENDING', 'CALLING', 'UNKNOWN_OUTCOME')"),
        ),
    )
