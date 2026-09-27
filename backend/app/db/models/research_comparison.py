import datetime

from sqlalchemy import JSON, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import IdMixin


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


class ResearchComparison(IdMixin, Base):
    """Qué dice cada proveedor sobre la misma pregunta (Milestone 35, ADR 0013).

    El plan maestro §32 pide para este milestone «comparar resultados contra
    mock». Esto es ese informe: para una categoría y un mercado, qué produjo
    cada proveedor, en qué se solapan —hoy, en nada— y qué sabe medir cada uno.

    El resumen va en JSON a propósito, al contrario que los pasos del pipeline o
    las observaciones: **un informe se lee entero**. Nadie va a preguntar «dame
    todas las comparaciones cuya cobertura de competencia sea menor que X»; se
    abre uno y se mira. Cuando esa pregunta exista, tendrá su tabla.
    """

    __tablename__ = "research_comparisons"

    category: Mapped[str] = mapped_column(String(64), index=True)
    market: Mapped[str] = mapped_column(String(16))
    #: Los dos proveedores contrastados, por su nombre estable.
    baseline_provider: Mapped[str] = mapped_column(String(64))
    candidate_provider: Mapped[str] = mapped_column(String(64))
    #: El informe: recuentos, solapamiento, cobertura por tipo de señal,
    #: confianza, disponibilidad de score y el veredicto en una línea.
    summary: Mapped[dict] = mapped_column(JSON)
    correlation_id: Mapped[str] = mapped_column(String(36), index=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
