import datetime
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import IdMixin


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


class ExchangeRate(IdMixin, Base):
    """Un tipo de cambio que alguien declara (Milestone 40, ADR 0018).

    La ADR 0017 prohibió convertir entre monedas porque no había fuente. Esta es
    la fuente más barata que existe y la única que cuesta cero euros: una
    persona escribe el cambio que le aplicó el banco, con su fecha. Es el mismo
    argumento que sostuvo la entrada manual de proveedores del Milestone 39.

    **La dirección va en los nombres de las columnas**: `1 base_currency =
    rate quote_currency`. Sin eso, un 1,08 puede ser dólares por euro o euros
    por dólar, y entre las dos lecturas hay un 16 %.

    Una tasa nueva es una **fila nueva**. No se machaca ni se borra: el margen
    que se calculó en marzo se calculó con la de marzo, y esa fila es la única
    forma de reconstruirlo.
    """

    __tablename__ = "exchange_rates"
    __table_args__ = (
        # Por aquí se pregunta: «la tasa de este par para esta fecha».
        sa.Index("ix_exchange_rates_pair_date", "base_currency", "quote_currency", "effective_date"),
    )

    base_currency: Mapped[str] = mapped_column(sa.String(3))
    quote_currency: Mapped[str] = mapped_column(sa.String(3))
    #: `Numeric(18, 8)` y no `Float`: una tasa necesita más decimales que un
    #: importe, y es la cifra por la que se multiplica todo lo demás.
    rate: Mapped[Decimal] = mapped_column(sa.Numeric(18, 8))
    #: El día para el que vale. Una tasa es de un día, no de un instante: el
    #: cambio de una transferencia se conoce por su fecha valor.
    effective_date: Mapped[datetime.date] = mapped_column(sa.Date, index=True)

    #: De dónde salió: `manual:<usuario>`, o el emisor cuando lo haya.
    source: Mapped[str] = mapped_column(sa.String(255))
    #: `declared` cuando la escribe el operador, `third_party_verified` cuando
    #: la emite alguien con nombre. `unknown` no se guarda: una tasa que nadie
    #: sostiene es la suposición 1:1 dando un rodeo.
    provenance: Mapped[str] = mapped_column(sa.String(32), index=True)
    #: Obligatorio cuando la procedencia es `third_party_verified`.
    declared_by: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    #: Lo que no cabe en los campos: «el cambio de la transferencia del día 3».
    note: Mapped[str | None] = mapped_column(sa.Text, nullable=True)

    created_at: Mapped[datetime.datetime] = mapped_column(
        sa.DateTime(timezone=True), default=_utcnow
    )
