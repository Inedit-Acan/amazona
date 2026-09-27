import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import IdMixin


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


class ProductSignalObservation(IdMixin, Base):
    """Una medida suelta de las que componen una señal (Milestone 35, ADR 0013).

    La señal dice «0,7483 de demanda». Esto dice de qué está hecho: 41.000
    visitas en marzo, 38.000 en abril, 45.000 en mayo. Es la evidencia, y sin
    ella el número agregado solo se puede creer o no creer.

    Va en filas y no en un JSON por el mismo motivo que los pasos del pipeline
    en el Milestone 32: es consultable —«¿cómo se movió el interés de estos
    candidatos el último trimestre?»— y meterlo en un blob lo escondería.

    Solo existe para señales que vienen de una serie. Una señal sin
    observaciones no es una señal con cero observaciones: es una señal que no se
    midió así.
    """

    __tablename__ = "product_signal_observations"
    __table_args__ = (Index("ix_signal_observations_signal_period", "signal_id", "period"),)

    signal_id: Mapped[str] = mapped_column(ForeignKey("product_signals.id"), index=True)
    #: La etiqueta del tramo tal y como la fuente lo expresa: `2026-08` un mes.
    period: Mapped[str] = mapped_column(String(16))
    #: El valor crudo de la fuente, sin normalizar. La normalización a 0-1 vive
    #: en la señal; aquí está lo que de verdad contestó la API.
    value: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
