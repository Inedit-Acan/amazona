from sqlalchemy import JSON, Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import IdMixin, TimestampMixin


class PipelineRun(IdMixin, TimestampMixin, Base):
    """One PipelineOrchestrator invocation (Milestone 12, ADR 0005): the
    9 Fase 3 steps (research through CFO) chained automatically instead
    of a human clicking through 9 Control Center pages. This table's own
    correlation_id is an additional grouping level, not a replacement
    for each step's individual audit trail.

    Desde el Milestone 32 (ADR 0010) la ejecución ocurre **fuera de la petición
    HTTP**: esta fila nace en QUEUED junto con sus nueve `pipeline_steps` y un
    trabajo (`job_id`) que un worker reclama después. Cada paso se persiste al
    ejecutarse, así que un fallo a mitad deja la ejecución reanudable en vez de
    huérfana. Por eso también se guarda `request`: sin los parámetros de negocio
    originales no se puede continuar lo que alguien empezó."""

    __tablename__ = "pipeline_runs"

    product_id: Mapped[str | None] = mapped_column(ForeignKey("products.id"), nullable=True, index=True)
    category: Mapped[str] = mapped_column(String(64))
    market: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16))
    failed_step: Mapped[str | None] = mapped_column(String(32), nullable=True)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    correlation_id: Mapped[str] = mapped_column(String(36))

    #: El trabajo que la ejecuta. Reanudar es volver a encolar **este** trabajo,
    #: así que sus intentos y su bitácora son la historia completa de la
    #: ejecución en un solo sitio (ADR 0010).
    job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id"), nullable=True, index=True)

    #: Los parámetros con los que se pidió (precio de venta, región de destino,
    #: plataformas, presupuesto…). Hacen falta para reanudar: un paso que no se
    #: ejecutó necesita los mismos datos que habría usado la primera vez.
    #:
    #: Nulo solo en ejecuciones anteriores al Milestone 32, que nunca los
    #: guardaron: la migración rellena lo que se puede deducir (categoría y
    #: mercado) y reanudar una de ellas se rechaza diciendo por qué, en vez de
    #: inventar un precio de venta.
    request: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=dict)
