import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import IdMixin, TimestampMixin


class SupplierCapability(IdMixin, TimestampMixin, Base):
    """Qué dice alguien que un proveedor sabe hacer (Milestone 39, ADR 0017).

    Las ocho capacidades del plan maestro §16 —envío directo, dropshipping,
    envío ciego, embalaje propio, seguimiento, devoluciones, dirección de retorno
    en la UE y SLA— no existían en el backend. La pantalla de Proveedores las
    enseñaba desde `lib/demo/sourcing.ts`, generadas con una semilla: ocho
    afirmaciones sobre el mundo salidas de un número pseudoaleatorio.

    Una fila aquí es una **declaración**, no un hecho: dice quién lo sostiene y
    desde cuándo. Y la ausencia de fila significa **no declarado**, que es
    distinto de «no lo soporta». Por eso no hay ocho columnas booleanas en
    `suppliers`: un booleano no puede decir «nadie lo ha preguntado».
    """

    __tablename__ = "supplier_capabilities"
    __table_args__ = (
        # Por aquí se pregunta: las capacidades de un proveedor, y las de un
        # proveedor para un producto concreto.
        Index("ix_supplier_capabilities_supplier_capability", "supplier_id", "capability"),
    )

    supplier_id: Mapped[str] = mapped_column(ForeignKey("suppliers.id"), index=True)
    #: `None` = vale para todo lo de ese proveedor. Con producto, solo para él:
    #: §16 dice «cada proveedor/producto debe declarar», y un fabricante puede
    #: enviar directo un artículo pequeño y no uno voluminoso.
    product_id: Mapped[str | None] = mapped_column(
        ForeignKey("products.id"), nullable=True, index=True
    )

    #: Una de `app.sourcing.capabilities.SupplyCapability`. Conjunto cerrado.
    capability: Mapped[str] = mapped_column(String(32))
    #: Si la soporta. Nunca nulo: una fila existe porque **alguien dijo algo**.
    #: Lo que no se sabe no tiene fila.
    supported: Mapped[bool] = mapped_column(Boolean)

    #: Quién lo dice. `unknown` no se guarda: una fila que dice «no se sabe»
    #: afirma lo mismo que no tener fila y además es indistinguible de un error
    #: de carga.
    provenance: Mapped[str] = mapped_column(String(32), index=True)
    #: De dónde salió. Obligatorio para `third_party_verified`.
    source: Mapped[str | None] = mapped_column(String(500), nullable=True)
    #: Lo que no cabe en un booleano: «solo para pedidos de más de 20», «con
    #: recargo de 0,80 €». Se guarda y no se interpreta.
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Cuándo se supo. Una capacidad declarada hace dos años y una de ayer no
    #: valen lo mismo.
    observed_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
