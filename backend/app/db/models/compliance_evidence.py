import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import IdMixin


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


class ComplianceEvidence(IdMixin, Base):
    """Evidencia de que **este producto** cumple **este requisito** (Milestone 41,
    ADR 0019). Tercera cuestión, separada de la aplicabilidad y de la vigencia.

    Un certificado emitido por un organismo es `third_party_verified` y **exige
    emisor**; el «tenemos el certificado» de una persona es `declared`. Una
    evidencia con `valid_until` pasado deja de contar, pero la fila se conserva.
    Está ligada a una fila concreta de requisito: si el requisito se sustituye,
    la evidencia del anterior no se traslada sola — quien lo modificó decide si
    sigue valiendo.
    """

    __tablename__ = "compliance_evidence"

    product_id: Mapped[str] = mapped_column(sa.ForeignKey("products.id"), index=True)
    requirement_id: Mapped[str] = mapped_column(
        sa.ForeignKey("regulatory_requirements.id"), index=True
    )
    provenance: Mapped[str] = mapped_column(sa.String(32))
    #: El emisor cuando la procedencia es `third_party_verified`.
    source: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    reference: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    valid_until: Mapped[datetime.date | None] = mapped_column(sa.Date, nullable=True)
    declared_by: Mapped[str] = mapped_column(sa.String(255))
    note: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(sa.DateTime(timezone=True), default=_utcnow)
