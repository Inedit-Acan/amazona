import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.mixins import IdMixin, TimestampMixin


class Order(IdMixin, TimestampMixin, Base):
    """Una venta (Milestone 44, ADR 0028): lo que un cliente ha pedido y por cuánto.

    **No lleva datos personales.** El cliente es `customer_ref`, una referencia opaca; ni nombre, ni email, ni
    teléfono, ni dirección, ni datos fiscales. En una simulación empieza por `sim_` y fuera de ella no puede
    hacerlo (lo garantiza un `CHECK`): un pedido de prueba no se confunde con uno real.

    `amount_due` es la suma de las líneas: **sin envío, sin impuestos y sin descuentos**, porque esos importes no
    existen todavía y un importe desconocido no es cero.

    A `PAID` solo se llega desde `AWAITING_PAYMENT` y solo lo escribe `PaymentService`, tras un evento de pago
    verificado. Ninguna ruta acepta un campo «pagado»."""

    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint("status IN ('AWAITING_PAYMENT', 'PAID', 'COMPLETED', 'CANCELLED')", name="ck_orders_status"),
        CheckConstraint("amount_due > 0", name="ck_orders_amount_due_positive"),
        # Sin `LIKE '%…%'`: el signo de porcentaje en un DDL es una trampa del controlador; `replace` es portable.
        CheckConstraint("replace(customer_ref, '@', '') = customer_ref", name="ck_orders_customer_ref_not_an_email"),
        CheckConstraint(
            "(is_simulated AND substr(customer_ref, 1, 4) = 'sim_') "
            "OR ((NOT is_simulated) AND substr(customer_ref, 1, 4) <> 'sim_')",
            name="ck_orders_simulation_prefix",
        ),
        Index("ix_orders_status_created_at", "status", "created_at"),
    )

    #: Referencia opaca del cliente, de 1 a 64 caracteres de `[A-Za-z0-9._:-]`. Nunca un dato personal.
    customer_ref: Mapped[str] = mapped_column(String(64))
    market: Mapped[str] = mapped_column(String(16))
    currency: Mapped[str] = mapped_column(String(3))
    amount_due: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    status: Mapped[str] = mapped_column(String(20), default="AWAITING_PAYMENT")
    #: Si se creó en una simulación (todos los proveedores `MOCK`). Se fija al crear y no cambia.
    is_simulated: Mapped[bool] = mapped_column(Boolean)
    correlation_id: Mapped[str] = mapped_column(String(36))
    paid_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    items: Mapped[list["OrderItem"]] = relationship(
        back_populates="order", order_by="OrderItem.line_number", cascade="all, delete-orphan"
    )


class OrderItem(IdMixin, TimestampMixin, Base):
    """Una línea de un pedido, con identidad propia.

    La identidad es el `id` y el orden estable es `line_number`: **no** el producto. Un mismo producto puede estar
    en varias líneas (variante, proveedor, cotización, precio, lote, división logística, promoción), y el esquema
    no puede impedirlo (ADR 0028 §6).

    `allocated_quantity` cuenta las unidades ya asignadas a algún fulfillment. Solo sube y baja con aritmética de
    base de datos (`UPDATE … WHERE quantity - allocated_quantity >= :q`): ninguna línea se asigna de más, ni con
    peticiones simultáneas. Una unidad ya comprada no vuelve al pool.

    `unit_cost` es el coste de proveedor **si se conoce**; `NULL` es desconocido y nunca es cero. Sale de la
    cotización (solo si está en la moneda del pedido) o lo declara quien crea el pedido, y lleva su procedencia."""

    __tablename__ = "order_items"
    __table_args__ = (
        UniqueConstraint("order_id", "line_number", name="uq_order_items_order_line"),
        CheckConstraint("line_number >= 1", name="ck_order_items_line_number_positive"),
        CheckConstraint("quantity > 0", name="ck_order_items_quantity_positive"),
        CheckConstraint(
            "allocated_quantity >= 0 AND allocated_quantity <= quantity",
            name="ck_order_items_allocation_within_quantity",
        ),
        CheckConstraint("unit_price > 0 AND line_total > 0", name="ck_order_items_prices_positive"),
        CheckConstraint("unit_cost IS NULL OR unit_cost >= 0", name="ck_order_items_cost_not_negative"),
        CheckConstraint(
            "(unit_cost IS NULL) = (cost_provenance IS NULL)", name="ck_order_items_cost_has_its_provenance"
        ),
    )

    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), index=True)
    line_number: Mapped[int] = mapped_column(Integer)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), index=True)
    #: A quién se le compraría esta línea, si se sabe (sale de la cotización). `NULL` = no se sabe.
    supplier_id: Mapped[str | None] = mapped_column(ForeignKey("suppliers.id"), nullable=True)
    supplier_quote_id: Mapped[str | None] = mapped_column(ForeignKey("supplier_quotes.id"), nullable=True)
    quantity: Mapped[int] = mapped_column(Integer)
    allocated_quantity: Mapped[int] = mapped_column(Integer, default=0)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    line_total: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    unit_cost: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    cost_provenance: Mapped[str | None] = mapped_column(String(32), nullable=True)
    cost_source: Mapped[str | None] = mapped_column(String(255), nullable=True)

    order: Mapped[Order] = relationship(back_populates="items")
