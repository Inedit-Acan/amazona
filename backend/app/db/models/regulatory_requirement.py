import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import IdMixin


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


class RegulatoryRequirement(IdMixin, Base):
    """Una norma que una persona **declara aplicable** a un alcance de producto
    (Milestone 41, ADR 0019).

    Esto es la **aplicabilidad**, y es lo único que ninguna fuente pública da. Se
    guarda lo que la persona afirmó, quién lo afirmó y con qué procedencia. La
    existencia y vigencia de la norma viven aparte (`regulatory_anchors`) y la
    evidencia de cumplimiento también (`compliance_evidence`): son tres
    cuestiones distintas y ninguna rellena a otra.

    Una fila no se modifica: **se sustituye** por otra (`superseded_by_id`) o se
    retira (`withdrawn_at`). Lo que Legal concluyó en marzo se concluyó con la
    declaración de marzo, y esa fila es la única forma de reconstruirlo.
    """

    __tablename__ = "regulatory_requirements"
    __table_args__ = (sa.Index("ix_regulatory_requirements_scope", "scope_key", "jurisdiction"),)

    #: El alcance tal como lo escribió quien lo declaró.
    product_scope: Mapped[str] = mapped_column(sa.String(128))
    #: La clave de emparejamiento: `fold(product_scope)`. Determinista, sin
    #: similitud: dos alcances son el mismo o no lo son.
    scope_key: Mapped[str] = mapped_column(sa.String(128))
    jurisdiction: Mapped[str] = mapped_column(sa.String(16))
    celex: Mapped[str] = mapped_column(sa.String(16), index=True)
    #: Cómo la llama quien la declara. No viene de la fuente.
    regulation: Mapped[str] = mapped_column(sa.String(255))
    reference: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    requirement: Mapped[str] = mapped_column(sa.Text)
    kind: Mapped[str] = mapped_column(sa.String(16))

    applicability_provenance: Mapped[str] = mapped_column(sa.String(32))
    applicability_source: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    declared_by: Mapped[str] = mapped_column(sa.String(255))

    transposition_reference: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    transposition_provenance: Mapped[str | None] = mapped_column(sa.String(32), nullable=True)
    transposition_source: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)

    note: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    superseded_by_id: Mapped[str | None] = mapped_column(sa.String(36), nullable=True)
    withdrawn_at: Mapped[datetime.datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime.datetime] = mapped_column(sa.DateTime(timezone=True), default=_utcnow)
