import datetime

from sqlalchemy import DateTime, Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import IdMixin


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


class ExternalApiCost(IdMixin, Base):
    """Una llamada a una API externa, con lo que consumió (Milestone 37, plan §25).

    El plan maestro §25 pide, literalmente y **antes** de introducir LLM o APIs
    comerciales: `provider, operation, units, estimated_cost, actual_cost,
    currency, correlation_id`. Están los siete, más tres que hacen falta para que
    los siete signifiquen algo:

    - `unit`: qué se cuenta. «8 unidades» sin decir de qué no es un dato.
    - `outcome`: si la llamada se hizo o se denegó. **Una denegación también se
      anota**: es la fila que explica por qué una investigación no trajo señales,
      y sin ella el sistema parecería roto en vez de prudente.
    - `denied_reason`: cuál de los límites la paró.

    `actual_cost` es nulable y nulo **no es cero**: es que el proveedor todavía no
    ha dicho lo que cobró. Es la misma distinción que sostiene todo lo demás desde
    el Milestone 34 — una ausencia no se rellena con el número que conviene.

    En filas y no en un contador agregado por el mismo motivo que los pasos del
    pipeline y las observaciones de las señales: se puede preguntar «¿qué gastó
    esta ejecución?» y «¿cuánto llevamos hoy con este proveedor?».
    """

    __tablename__ = "external_api_costs"
    __table_args__ = (
        # Por aquí se pregunta: lo consumido hoy con un proveedor, y lo que gastó
        # una ejecución concreta.
        Index("ix_external_api_costs_provider_day", "provider", "observed_at"),
        Index("ix_external_api_costs_correlation", "correlation_id"),
    )

    #: El mismo nombre que la señal persiste en `provider`.
    provider: Mapped[str] = mapped_column(String(64), index=True)
    #: Qué se pidió: `item_summary/search`, `pageviews/per-article`.
    operation: Mapped[str] = mapped_column(String(64))
    #: Cuántas unidades consumió, y de qué.
    units: Mapped[int] = mapped_column(Integer)
    unit: Mapped[str] = mapped_column(String(16))
    #: Lo que se esperaba pagar por ellas.
    estimated_cost: Mapped[float] = mapped_column(Float)
    #: Lo que se pagó de verdad, cuando el proveedor lo dice. **Nulo no es cero.**
    actual_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    currency: Mapped[str] = mapped_column(String(3))
    #: `allowed` o `denied`.
    outcome: Mapped[str] = mapped_column(String(16), index=True)
    #: Qué límite la paró, cuando se denegó.
    denied_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(36))
    observed_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
