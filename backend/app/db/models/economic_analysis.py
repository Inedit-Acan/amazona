from decimal import Decimal

from sqlalchemy import JSON, Float, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import IdMixin, TimestampMixin


class EconomicAnalysis(IdMixin, TimestampMixin, Base):
    """Un análisis económico, con canal y moneda (Milestone 40, ADR 0018).

    Hasta aquí tenía un precio de venta, unos costes fijos y un margen, y
    ninguno de los tres decía **en qué moneda** ni **dónde se vende**. El margen
    se calculaba restando un coste en dólares de un precio en euros, con un
    aviso en la lista de riesgos y el número mal.

    Las columnas monetarias nuevas son `Numeric(12, 4)` y no `Float`: dinero en
    coma flotante pierde céntimos, y cuatro decimales porque un coste unitario
    de 0,0042 € existe. Las que ya estaban se quedan en `Float` — migrar treinta
    revisiones es un milestone propio, y la frontera está escrita en
    `app/money/serialization.py`.
    """

    __tablename__ = "economic_analyses"

    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), index=True)
    supplier_quote_id: Mapped[str] = mapped_column(ForeignKey("supplier_quotes.id"))
    analysis_type: Mapped[str] = mapped_column(String(32), default="economic_risk")
    sale_price: Mapped[float] = mapped_column(Float)
    monthly_fixed_costs: Mapped[float] = mapped_column(Float)
    #: **Nulable desde el Milestone 40**: un análisis que no se ha podido
    #: evaluar no tiene margen, y un 0,0 diría que el margen es cero.
    margin_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    recommendation: Mapped[str] = mapped_column(String(16))
    confidence: Mapped[float] = mapped_column(Float)

    #: Dónde se vende. Una clave del catálogo del Milestone 38. Nulo en las
    #: filas anteriores al Milestone 40 y eso significa **que nadie lo declaró**,
    #: no «vale para todos los canales».
    channel: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    #: La moneda de **todo** el análisis. Nula en las filas antiguas: nadie dijo
    #: en qué estaban, y suponerlo ahora sería inventar.
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)

    #: Cuántas unidades lleva un pedido. Nulo = **no declarado**, y entonces no
    #: hay margen por pedido ni techo de CAC. Un 1 que nadie ha declarado no
    #: vale: hasta el Milestone 40, unidad y pedido eran la misma cifra con dos
    #: nombres, y el techo de CAC salía de esa confusión.
    units_per_order: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: Quién sostiene ese número: `declared` si lo escribió una persona,
    #: `simulated` si viene de un fixture.
    units_per_order_provenance: Mapped[str | None] = mapped_column(String(32), nullable=True)

    #: Si el margen se pudo calcular. **No es un resultado económico**: un
    #: margen negativo se sabe y es malo; `not_evaluable` es que no se sabe.
    margin_evaluability: Mapped[str] = mapped_column(String(24), default="evaluable")
    #: Si el techo de CAC se pudo calcular. Va aparte porque se puede tener un
    #: margen firme y no tener con qué repartir los costes fijos.
    cac_evaluability: Mapped[str] = mapped_column(String(24), default="evaluable")
    #: Qué faltó, por su nombre. Es la lista que hay que rellenar para que el
    #: resultado exista, y por eso se guarda con él y no en un log.
    missing_inputs: Mapped[list | None] = mapped_column(JSON, nullable=True)

    #: Precio de venta menos los costes variables **conocidos**.
    contribution_margin_per_unit: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 4), nullable=True
    )
    #: El anterior por las unidades que lleva un pedido. Es lo que financia una
    #: adquisición, y por eso el CAC se mide contra esto y no contra la unidad.
    contribution_margin_per_order: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 4), nullable=True
    )
    allocated_fixed_cost_per_order: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 4), nullable=True
    )
    #: Lo que **podríamos permitirnos** pagar por una adquisición. No dice lo
    #: que costará: eso es CAC medido y necesita campañas reales.
    max_breakeven_cac: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)

    #: Las conversiones aplicadas, cada una con sus diez campos, cuando la
    #: cotización estaba en otra moneda. **Una lista y no una sola**: el precio
    #: y el coste logístico se convierten por separado, y guardar solo la última
    #: dejaría la otra sin rastro — que es justo lo contrario de lo que esta
    #: columna existe para hacer. Nula cuando no hizo falta convertir.
    fx_conversions: Mapped[list | None] = mapped_column(JSON, nullable=True)

    data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(36))
