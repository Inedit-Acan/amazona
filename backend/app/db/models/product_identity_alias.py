import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import IdMixin


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


class ProductIdentityAlias(IdMixin, Base):
    """Otro nombre con el que llegó un producto que ya existía (Milestone 36,
    ADR 0014).

    Fusionar dos candidatos en uno es una decisión, y una decisión sin motivo
    escrito es indistinguible de un error. Esta tabla contesta «¿por qué estos
    dos son uno?» meses después: con qué nombre llegó, a qué identidad se
    resolvió, por qué vía —`normalised` o `alias:<versión>`— y en qué ejecución
    pasó.

    En filas y no en un JSON por el mismo motivo que los pasos del pipeline en el
    Milestone 32 y las observaciones en el 35: es consultable —«¿de qué nombres
    viene este producto?»— y en un blob estaría escondido.

    Aquí solo se anota lo que **difiere**. Un candidato que llega con el nombre
    canónico no genera fila: no hubo nada que resolver, y una fila por cada
    coincidencia trivial escondería las que importan.
    """

    __tablename__ = "product_identity_aliases"
    __table_args__ = (
        # Por aquí se pregunta: de qué nombres viene un producto, y a qué
        # producto llevó un nombre que alguien vio por ahí.
        Index("ix_product_identity_aliases_product_alias", "product_id", "alias"),
        Index("ix_product_identity_aliases_key", "identity_key"),
    )

    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), index=True)
    #: El nombre tal y como llegó, sin tocar. Es la evidencia de la fusión.
    alias: Mapped[str] = mapped_column(String(255))
    #: La clave a la que se resolvió, la misma que lleva el producto.
    identity_key: Mapped[str] = mapped_column(String(255))
    #: Cómo se resolvió: `normalised` si bastó la transformación determinista,
    #: `alias:<versión>` si hizo falta el catálogo escrito a mano. Nunca por
    #: parecido: eso no existe (ADR 0014).
    method: Mapped[str] = mapped_column(String(32))
    correlation_id: Mapped[str] = mapped_column(String(36))
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
