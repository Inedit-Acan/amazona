import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.mixins import IdMixin, TimestampMixin

_STATUSES = (
    "status IN ('READY', 'PURCHASING', 'PURCHASED', 'SHIPPING', 'SHIPPED', 'COMPLETED', 'FAILED', 'CANCELLED', "
    "'UNKNOWN_OUTCOME')"
)


class Fulfillment(IdMixin, TimestampMixin, Base):
    """Una compra al proveedor y su envío para **un subconjunto de líneas** de un pedido (Milestone 44, ADR 0028 §6).

    Un pedido puede tener varios: el esquema no asume que todas las líneas se compran al mismo proveedor ni que se
    envían juntas. M44 no hace sourcing multi-proveedor; solo no lo hace imposible.

    El estado solo lo escriben `FulfilmentService` (decisiones de una persona) y el observador de las acciones
    `fulfillment.purchase` y `fulfillment.ship` (`app/orders/fulfilment_projection.py`), que reflejan lo que pasó
    fuera. Nada lo acepta de un cliente.

    - `READY` y `PURCHASED` son «nada enviado» (antes de comprar, antes de enviar); `PURCHASING` y `SHIPPING`, «pudo
      salir»; `UNKNOWN_OUTCOME` (con `unknown_phase`), «no se sabe».
    - **Una unidad comprada no vuelve al pool.** `CANCELLED` y `FAILED` solo se alcanzan desde `READY` sin compra
      (`purchased_at IS NULL`) y sin resultado desconocido, y un `CHECK` impide que un fulfillment con compra termine
      en ellos. La asignación (`order_items.allocated_quantity`) solo se libera con `release_allocation()`.
    - Un fallo de **envío** después de comprar no es un `FAILED`: el fulfillment vuelve a `PURCHASED` con
      `failed_attempts + 1`, las unidades siguen asignadas y alguien tiene que mirarlo."""

    __tablename__ = "fulfillments"
    __table_args__ = (
        CheckConstraint(_STATUSES, name="ck_fulfillments_status"),
        CheckConstraint("unknown_phase IS NULL OR unknown_phase IN ('purchase', 'ship')", name="ck_fulfillments_phase"),
        CheckConstraint(
            "(status = 'UNKNOWN_OUTCOME') = (unknown_phase IS NOT NULL)", name="ck_fulfillments_unknown_has_its_phase"
        ),
        CheckConstraint("failed_attempts >= 0", name="ck_fulfillments_failed_attempts_not_negative"),
        CheckConstraint(
            "status NOT IN ('PURCHASED', 'SHIPPING', 'SHIPPED', 'COMPLETED') OR purchased_at IS NOT NULL",
            name="ck_fulfillments_bought_has_purchased_at",
        ),
        CheckConstraint(
            "status NOT IN ('SHIPPED', 'COMPLETED') OR shipped_at IS NOT NULL",
            name="ck_fulfillments_sent_has_shipped_at",
        ),
        CheckConstraint(
            "status <> 'COMPLETED' OR (completed_at IS NOT NULL AND completed_by IS NOT NULL)",
            name="ck_fulfillments_completed_has_actor",
        ),
        CheckConstraint(
            "status NOT IN ('FAILED', 'CANCELLED') OR purchased_at IS NULL",
            name="ck_fulfillments_a_purchased_unit_never_returns_to_the_pool",
        ),
        Index(
            "uq_fulfillments_provider_purchase_ref",
            "provider",
            "purchase_reference",
            unique=True,
            postgresql_where=text("purchase_reference IS NOT NULL"),
            sqlite_where=text("purchase_reference IS NOT NULL"),
        ),
        Index("ix_fulfillments_order_status", "order_id", "status"),
    )

    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"))
    provider: Mapped[str] = mapped_column(String(64))
    #: A quién se le compra, si se sabe. Todas las líneas de un fulfillment comparten proveedor.
    supplier_id: Mapped[str | None] = mapped_column(ForeignKey("suppliers.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="READY")
    #: Solo con `UNKNOWN_OUTCOME`: qué operación quedó sin saberse (`purchase` o `ship`).
    unknown_phase: Mapped[str | None] = mapped_column(String(12), nullable=True)
    purchase_reference: Mapped[str | None] = mapped_column(String(128), nullable=True)
    tracking_reference: Mapped[str | None] = mapped_column(String(128), nullable=True)
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_by: Mapped[str] = mapped_column(String(255))
    completed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(36))
    purchased_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    shipped_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    items: Mapped[list["FulfillmentItem"]] = relationship(
        back_populates="fulfillment", cascade="all, delete-orphan", order_by="FulfillmentItem.created_at"
    )


class FulfillmentItem(IdMixin, TimestampMixin, Base):
    """Cuántas unidades de una línea del pedido cubre un fulfillment. La misma línea puede repartirse entre varios
    fulfillments mientras la suma no pase de su cantidad (`order_items.allocated_quantity`, con aritmética de base de
    datos)."""

    __tablename__ = "fulfillment_items"
    __table_args__ = (
        UniqueConstraint("fulfillment_id", "order_item_id", name="uq_fulfillment_items_fulfillment_line"),
        CheckConstraint("quantity > 0", name="ck_fulfillment_items_quantity_positive"),
    )

    fulfillment_id: Mapped[str] = mapped_column(ForeignKey("fulfillments.id"), index=True)
    order_item_id: Mapped[str] = mapped_column(ForeignKey("order_items.id"), index=True)
    quantity: Mapped[int] = mapped_column(Integer)

    fulfillment: Mapped[Fulfillment] = relationship(back_populates="items")
