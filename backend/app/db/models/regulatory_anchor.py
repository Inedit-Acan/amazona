import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import IdMixin


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


class RegulatoryAnchor(IdMixin, Base):
    """Lo que una fuente dijo de una norma en una comprobación concreta (Milestone
    41, ADR 0019). La **existencia y vigencia**, con su fecha.

    Una comprobación nueva es una **fila nueva**: no se machaca la anterior. Tres
    fechas distintas que no se confunden:

    - `verified_at`: cuándo preguntamos (el `retrieved_at` del §12).
    - `source_effective_from` / `source_effective_to`: las fechas **que la fuente
      entrega**, sin interpretar. Pueden ser varias, y el fin de validez puede ser
      un valor que la fuente no documenta.
    - `recheck_after`: **política operativa nuestra**. Superarlo pide una nueva
      comprobación; no significa que la norma haya dejado de estar en vigor.
    """

    __tablename__ = "regulatory_anchors"
    __table_args__ = (sa.Index("ix_regulatory_anchors_celex_verified", "celex", "verified_at"),)

    celex: Mapped[str] = mapped_column(sa.String(16))
    provider: Mapped[str] = mapped_column(sa.String(64))
    #: Procedencia del ancla: siempre `third_party_verified`, con `provider` como
    #: emisor. Se guarda explícita para que no dependa de una convención.
    provenance: Mapped[str] = mapped_column(sa.String(32), default="third_party_verified")
    verified_at: Mapped[datetime.datetime] = mapped_column(sa.DateTime(timezone=True))
    recheck_after: Mapped[datetime.datetime] = mapped_column(sa.DateTime(timezone=True))
    #: `False`: la fuente respondió y no conoce esa norma.
    found: Mapped[bool] = mapped_column(sa.Boolean)
    in_force: Mapped[bool | None] = mapped_column(sa.Boolean, nullable=True)
    act_type: Mapped[str] = mapped_column(sa.String(16))
    act_type_code: Mapped[str | None] = mapped_column(sa.String(32), nullable=True)
    eli: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    document_date: Mapped[str | None] = mapped_column(sa.String(10), nullable=True)
    source_effective_from: Mapped[list | None] = mapped_column(sa.JSON, nullable=True)
    #: Tal como la fuente lo entrega, como cadena.
    source_effective_to: Mapped[str | None] = mapped_column(sa.String(10), nullable=True)
    source_url: Mapped[str] = mapped_column(sa.Text)
    #: Todo lo que la fuente devolvió, sin interpretar.
    evidence: Mapped[dict | None] = mapped_column(sa.JSON, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(sa.DateTime(timezone=True), default=_utcnow)
