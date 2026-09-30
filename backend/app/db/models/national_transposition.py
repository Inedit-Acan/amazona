import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import IdMixin


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


class NationalTransposition(IdMixin, Base):
    """Una norma nacional que una persona **declara** como transposición de la
    directiva de un requisito (Milestone 43, ADR 0021).

    Es la primera capa —la **norma declarada**— y la única que ninguna fuente da: el
    sistema no infiere qué ley española traspone una directiva. Se guarda quién lo
    afirmó. La verificación contra el BOE vive aparte (`national_anchors`), igual que
    en M41 la vigencia vive aparte de la aplicabilidad.

    Está ligada a una fila concreta de requisito: si el requisito se sustituye, la
    transposición **no** se traslada sola —quien lo modificó decide si sigue
    valiendo—, igual que la evidencia de cumplimiento. Una fila no se modifica: se
    retira (`withdrawn_at`).
    """

    __tablename__ = "national_transpositions"

    requirement_id: Mapped[str] = mapped_column(
        sa.ForeignKey("regulatory_requirements.id"), index=True
    )
    #: El identificador de la norma en la fuente (`BOE-A-2011-14252`).
    national_id: Mapped[str] = mapped_column(sa.String(32), index=True)
    #: Siempre `declared`: la relación la sostiene quien la declara.
    provenance: Mapped[str] = mapped_column(sa.String(32), default="declared")
    declared_by: Mapped[str] = mapped_column(sa.String(255))
    note: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    withdrawn_at: Mapped[datetime.datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime.datetime] = mapped_column(sa.DateTime(timezone=True), default=_utcnow)
