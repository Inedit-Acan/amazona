import datetime

from sqlalchemy import JSON, DateTime, Float, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import IdMixin, TimestampMixin


class Supplier(IdMixin, TimestampMixin, Base):
    """Una empresa que puede fabricar o suministrar algo (Milestone 39, ADR 0017).

    Hasta aquí tenía un `verified: bool` y un `reliability_score: float = 0.0`.
    Los dos decían menos de lo que parecía: el primero no explicaba verificado
    por quién ni contra qué —lo que el plan maestro §10 prohíbe expresamente—, y
    el segundo hacía indistinguible «no sabemos si es fiable» de «no es nada
    fiable», que es el cero inventado aplicado a una empresa.

    Ahora cada hecho dice quién lo sostiene, y lo que nadie ha dicho se queda sin
    decir: nulo, no cero.
    """

    __tablename__ = "suppliers"
    __table_args__ = (
        # Por aquí se pregunta desde el Milestone 39: «¿ya tengo a esta empresa?»,
        # cuando llega de otra fuente o cuando alguien la teclea a mano.
        Index("ix_suppliers_identity_key", "identity_key"),
    )

    name: Mapped[str] = mapped_column(String(255))

    #: La clave de identidad: nombre normalizado más dónde está
    #: (`app.sourcing.identity`). Es lo que permite que la misma empresa llegue
    #: del mock, de una fuente real y de la mano de una persona y siga siendo
    #: una, en vez de tres filas que compiten entre sí en la misma pantalla.
    identity_key: Mapped[str | None] = mapped_column(String(320), nullable=True)
    #: `normalised` o `alias:<versión>`: **cómo** se resolvió. La respuesta a
    #: «¿por qué estas dos fichas son una?», contestable meses después.
    identity_method: Mapped[str | None] = mapped_column(String(32), nullable=True)

    #: Dónde está. `region` es lo grueso (`china`, `eu`) y es lo único que daba
    #: el mock; `country` y `city` son lo que pide el plan §10 y solo se llenan
    #: cuando alguien los sabe.
    region: Mapped[str | None] = mapped_column(String(100), nullable=True)
    country: Mapped[str | None] = mapped_column(String(100), nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    #: De dónde salió esta ficha: la web del proveedor, el directorio, el correo.
    website: Mapped[str | None] = mapped_column(String(500), nullable=True)

    contact_info: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    #: Quién sostiene que esta empresa es quien dice ser: `third_party_verified`,
    #: `supplier_claim`, `amazona_estimate` o `simulated`. Nulo es **desconocido**
    #: y es una respuesta legítima; lo que ya no existe es un «sí» sin autor.
    verification: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    #: Quién verificó, cuando alguien verificó. Obligatorio para
    #: `third_party_verified`: un «verificado» sin emisor no explica nada, y el
    #: dominio lo rechaza al construirlo (`app.sourcing.provenance`).
    verified_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    verified_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    #: Lo que alguien dice de su fiabilidad, 0-1. **Nulo, no cero**, cuando nadie
    #: lo ha dicho. No es el riesgo del proveedor: el riesgo vive por dimensiones
    #: en `app.sourcing.risk` y §11 prohíbe expresamente reducirlo a un número.
    reliability_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    reliability_provenance: Mapped[str | None] = mapped_column(String(32), nullable=True)

    #: Cuándo se comprobó por última vez que esta ficha sigue siendo cierta
    #: (plan §10, «last checked»). Un precio de hace dos años y uno de ayer no
    #: valen lo mismo, y la diferencia solo es visible si consta la fecha.
    last_checked_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
