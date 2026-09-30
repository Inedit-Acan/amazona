import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import IdMixin


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


class NationalAnchor(IdMixin, Base):
    """Lo que el BOE dijo de una norma nacional en una comprobación concreta
    (Milestone 43, ADR 0021).

    Una comprobación nueva es una **fila nueva**: no se machaca la anterior. Las
    capas no se mezclan:

    - los **metadatos** y las **relaciones** se guardan como la fuente los entregó
      (fechas como cadena `AAAAMMDD`, banderas `S`/`N`): no se reinterpretan;
    - la **publicación oficial** es una comprobación auxiliar con su propio estado
      (`confirmed`, `absent_from_summary`, `check_failed`, `not_checked`): un fallo
      no es «no existe»;
    - `informational` es siempre verdadero y se guarda **explícito**, con el aviso y
      la atribución que exige la licencia: la legislación consolidada y su análisis
      no tienen valor oficial;
    - el **texto** de la norma no se guarda.
    """

    __tablename__ = "national_anchors"
    __table_args__ = (sa.Index("ix_national_anchors_id_verified", "national_id", "verified_at"),)

    national_id: Mapped[str] = mapped_column(sa.String(32))
    provider: Mapped[str] = mapped_column(sa.String(64))
    provenance: Mapped[str] = mapped_column(sa.String(32), default="third_party_verified")
    #: Cuándo preguntamos. Política nuestra: `recheck_after`, no un plazo jurídico.
    verified_at: Mapped[datetime.datetime] = mapped_column(sa.DateTime(timezone=True))
    recheck_after: Mapped[datetime.datetime] = mapped_column(sa.DateTime(timezone=True))
    #: `False`: la fuente no tiene la norma **consolidada**. No dice que no exista.
    consolidated: Mapped[bool] = mapped_column(sa.Boolean)
    #: Siempre `True`: la consolidación y el análisis son meramente informativos.
    informational: Mapped[bool] = mapped_column(sa.Boolean, default=True)
    notice: Mapped[str] = mapped_column(sa.Text)
    attribution: Mapped[str] = mapped_column(sa.String(255))
    #: Los metadatos de la fuente, verbatim. (`metadata` es un nombre reservado del
    #: declarativo de SQLAlchemy.)
    source_metadata: Mapped[dict | None] = mapped_column(sa.JSON, nullable=True)
    #: `fecha_actualizacion` de la fuente, tal cual, para mostrarla sin abrir el JSON.
    source_updated_at: Mapped[str | None] = mapped_column(sa.String(20), nullable=True)
    #: `{"previous": [...], "next": [...]}`, tal como el análisis las documenta.
    relations: Mapped[dict | None] = mapped_column(sa.JSON, nullable=True)
    publication_state: Mapped[str] = mapped_column(sa.String(24))
    publication_detail: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    publication_url: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    source_urls: Mapped[list | None] = mapped_column(sa.JSON, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(sa.DateTime(timezone=True), default=_utcnow)
