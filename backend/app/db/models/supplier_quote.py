import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import IdMixin, TimestampMixin


class SupplierQuote(IdMixin, TimestampMixin, Base):
    """Lo que un proveedor pide por un producto (Milestone 39, ADR 0017).

    Antes de este milestone una cotización era un precio, un MOQ, un plazo y dos
    costes calculados. Sin moneda, sin Incoterm, sin condiciones de pago, sin
    destino y sin caducidad. Eso no es una cotización: «4,20» puede ser EXW
    Shenzhen en dólares —sin transporte ni aduana— o DDP Valencia en euros, y
    entre las dos está la diferencia entre ganar dinero y perderlo.

    Todo lo que se añade aquí es **nulable**, y eso es la mitad del punto: lo que
    el proveedor no ha dicho se queda sin decir. Un Incoterm por defecto sería
    una condición pactada que nadie pactó, y un coste logístico cero sería un
    transporte gratis.
    """

    __tablename__ = "supplier_quotes"

    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), index=True)
    supplier_id: Mapped[str] = mapped_column(ForeignKey("suppliers.id"))
    analysis_type: Mapped[str] = mapped_column(String(32), default="sourcing")

    #: Precio de **una** unidad, en `currency`. Nulo cuando no consta: un precio
    #: desconocido no es un precio de cero.
    unit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    #: Código ISO 4217, validado contra el catálogo de `app.sourcing.trade_terms`.
    #: Nulo significa que nadie dijo en qué moneda está — y entonces el precio
    #: **no se compara** con otro, porque suponer que coinciden es inventar un
    #: tipo de cambio de 1,00.
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    #: Qué es una unidad para este proveedor: `piece`, `pair`, `kg`, `m`. Sin
    #: esto, dos precios por «unidad» pueden ser por pieza y por caja de diez.
    quoted_unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    #: En qué bloque cotiza el proveedor, cuando no cotiza de una en una. Es
    #: distinto del MOQ: el MOQ es lo mínimo que te dejan pedir, esto es cómo
    #: agrupa su oferta.
    quoted_quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)

    #: Mínimo que acepta servir. Nulo = no lo ha dicho, que no es «uno».
    moq: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: Días de **preparación**: lo que tarda en tener la mercancía lista. No
    #: incluye el transporte, que es `transit_days`. Estaban juntos en un solo
    #: número y por eso un plazo de 25 días no se podía atribuir a nada.
    lead_time_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: Días estimados de transporte hasta `destination_market`.
    transit_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: Cómo viaja: `air`, `sea`, `road`, `rail`, `courier`. Texto corto y sin
    #: catálogo cerrado a propósito: aquí un valor nuevo no rompe ninguna
    #: consulta, al contrario que un canal o un Incoterm.
    transport_mode: Mapped[str | None] = mapped_column(String(32), nullable=True)

    #: Término de entrega (Incoterms 2020). Dice hasta dónde llega el precio:
    #: si incluye el transporte principal y si incluye los derechos de
    #: importación. Sin él, sumar un coste logístico puede estar contándolo dos
    #: veces.
    incoterm: Mapped[str | None] = mapped_column(String(3), nullable=True)
    #: Condiciones de pago, tal y como las escribe el proveedor: «30 % anticipo,
    #: 70 % contra BL». Se guarda y **no se interpreta**: un analizador de
    #: condiciones de pago sería un modelo con opiniones donde hace falta un
    #: hecho.
    payment_terms: Mapped[str | None] = mapped_column(String(255), nullable=True)

    #: Para qué mercado vale esta oferta. Hasta aquí el destino era un parámetro
    #: de la ejecución y no se guardaba en ningún sitio, así que el coste de
    #: aterrizaje era un número sin destino: no se podía saber si «2,46» era
    #: hasta Valencia o hasta Monterrey.
    destination_market: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)

    #: Vigencia declarada. Una oferta caducada sigue siendo un hecho histórico
    #: —por eso no se borra— y deja de ser una oferta.
    valid_from: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    valid_until: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    #: Quién sostiene **esta oferta**: normalmente `supplier_claim`. Es un hecho
    #: distinto de la verificación de la empresa (`suppliers.verification`): que
    #: una empresa esté verificada no verifica su tarifa, y un precio sacado de
    #: un catálogo público no es lo mismo que uno dicho por WhatsApp.
    provenance: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    #: De dónde salió: `manual:<usuario>`, `fixtures:mock-supplier-directory`,
    #: una URL. Obligatorio cuando la procedencia es `third_party_verified`.
    source: Mapped[str | None] = mapped_column(String(500), nullable=True)

    #: Coste logístico por unidad hasta `destination_market`. Nulo = no se ha
    #: calculado ni lo ha dicho nadie.
    logistics_cost_per_unit: Mapped[float | None] = mapped_column(Float, nullable=True)
    #: Quién sostiene el coste logístico. Es casi siempre `amazona_estimate`,
    #: porque lo calcula un estimador nuestro con factores inventados, y va
    #: aparte del precio a propósito: el precio puede venir del proveedor y el
    #: transporte de un modelo nuestro, y presentarlos con la misma procedencia
    #: mentiría sobre la mitad de la suma.
    logistics_provenance: Mapped[str | None] = mapped_column(String(32), nullable=True)
    #: Precio + logística. Nulo cuando falta cualquiera de los dos: un coste de
    #: aterrizaje incompleto que se presenta como completo es la cifra sobre la
    #: que se calculan el margen y el techo de CAC.
    total_landed_cost_per_unit: Mapped[float | None] = mapped_column(Float, nullable=True)

    data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(36))
