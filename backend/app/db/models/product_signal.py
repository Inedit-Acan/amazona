import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import IdMixin


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


class ProductSignal(IdMixin, Base):
    """Una medición sobre un producto candidato, con su procedencia completa
    (Milestone 34, ADR 0012; plan maestro §8).

    Existe por una frase del plan maestro: «nunca almacenar solo un número final
    sin procedencia». Hasta ahora un 0,82 de demanda inventado por un fixture y
    un 0,82 medido contra una fuente real eran indistinguibles una vez escritos
    en `product_analyses.data`. Aquí cada número lleva quién lo produjo, de qué
    fuente, preguntando qué, en qué mercado, cuándo, con qué método, con cuánta
    confianza y cómo volver al dato crudo — y si es simulado.

    Es aditivo: `product_analyses` sigue guardando el análisis y su score. Esta
    tabla guarda de qué está hecho, que es lo que permitirá al Milestone 35
    comparar lo real contra el mock en vez de escarbar JSON.
    """

    __tablename__ = "product_signals"
    __table_args__ = (
        # Por aquí se pregunta: las señales de un producto, y las de una
        # ejecución de investigación concreta.
        Index("ix_product_signals_product_kind", "product_id", "kind"),
        Index("ix_product_signals_correlation", "correlation_id"),
    )

    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), index=True)
    #: Qué se midió: demand, competition, future_outlook, regulatory_risk,
    #: scalability.
    kind: Mapped[str] = mapped_column(String(32), index=True)
    #: Normalizado a 0-1, para que fuentes distintas sean comparables.
    value: Mapped[float] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float)

    #: Quién lo produjo (`wikimedia-pageviews`, `fixtures`) y de dónde salió.
    provider: Mapped[str] = mapped_column(String(64), index=True)
    source: Mapped[str] = mapped_column(String(255))
    #: Qué se preguntó exactamente, y en qué mercado.
    query: Mapped[str] = mapped_column(String(255))
    market: Mapped[str] = mapped_column(String(16))
    observed_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True))
    #: Cómo se calculó y qué significa de verdad. Texto largo a propósito: aquí
    #: es donde se dice que unas visitas a una enciclopedia son un proxy de
    #: interés y no demanda de compra.
    method: Mapped[str] = mapped_column(Text)
    #: Cómo volver al dato crudo: una URL, una clave de fixture. **Una
    #: referencia, no el cuerpo de la respuesta**: guardar el payload entero
    #: metería identidades de vendedores —datos personales, con deberes de
    #: borrado— en una tabla de métricas (Milestone 37, ADR 0015).
    raw_reference: Mapped[str | None] = mapped_column(String(500), nullable=True)
    #: `measured`, `estimated` o `simulated` (Milestone 37, ADR 0015).
    #:
    #: Sustituye al booleano `simulated`, que juntaba dos cosas distintas: un
    #: número que una fuente **observó** y uno que una fuente **modeló**. Las dos
    #: vienen del mundo y no valen lo mismo, y presentar una estimación como una
    #: medición es la misma clase de mentira que presentar un fixture como dato.
    basis: Mapped[str] = mapped_column(String(16), default="measured", index=True)

    correlation_id: Mapped[str] = mapped_column(String(36))
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
