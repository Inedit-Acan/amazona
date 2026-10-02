"""fulfillments and fulfillment items

Milestone 44 (ADR 0028 §6). La compra al proveedor y el envío de un pedido pagado.

- `fulfillments`: **un pedido puede tener varios**, cada uno con un subconjunto de líneas. No hay `UNIQUE(order_id)`:
  el esquema no asume un solo proveedor ni un solo envío. El estado lo escriben el servicio de fulfillment y el
  observador de las acciones de comprar y enviar. Los `CHECK` hacen cumplir en la base de datos lo que el código no
  debe romper: un resultado desconocido nombra su fase; un fulfillment comprado tiene `purchased_at`; y **un fulfillment
  con compra jamás termina `CANCELLED` ni `FAILED`**, es decir, una unidad comprada no vuelve al pool (evita comprar
  dos veces).
- `fulfillment_items`: cuántas unidades de una línea cubre cada fulfillment. La suma por línea la limita
  `order_items.allocated_quantity` (que ya tiene su `CHECK 0 <= allocated <= quantity`).

Ningún dato personal: ni dirección ni destinatario (no hay envíos reales todavía).

## RLS desde su propia migración

Se activa aquí, con el patrón de la ADR 0003: `ENABLE ROW LEVEL SECURITY` y, solo en Supabase, la política
`deny_all_anon_authenticated`. Sin `FORCE`: el backend es el dueño.

## Bajar

Es aditiva y no modifica datos existentes. Bajar elimina las dos tablas y lo que hubiera en ellas. **Atención:** las
unidades asignadas de `order_items.allocated_quantity` quedarían sin fulfillment que las respalde; hay que exportar
y reajustar antes de bajar un entorno con fulfillments.

Revision ID: b3c8f1a5d742
Revises: a9d2e7b4c136
Create Date: 2026-10-02

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b3c8f1a5d742"
down_revision: str | Sequence[str] | None = "a9d2e7b4c136"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("fulfillments", "fulfillment_items")

_STATUSES = (
    "status IN ('READY', 'PURCHASING', 'PURCHASED', 'SHIPPING', 'SHIPPED', 'COMPLETED', 'FAILED', 'CANCELLED', "
    "'UNKNOWN_OUTCOME')"
)


def upgrade() -> None:
    op.create_table(
        "fulfillments",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("order_id", sa.String(length=36), sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("supplier_id", sa.String(length=36), sa.ForeignKey("suppliers.id"), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("unknown_phase", sa.String(length=12), nullable=True),
        sa.Column("purchase_reference", sa.String(length=128), nullable=True),
        sa.Column("tracking_reference", sa.String(length=128), nullable=True),
        sa.Column("failed_attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_failure_code", sa.String(length=64), nullable=True),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("completed_by", sa.String(length=255), nullable=True),
        sa.Column("correlation_id", sa.String(length=36), nullable=False),
        sa.Column("purchased_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("shipped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(_STATUSES, name="ck_fulfillments_status"),
        sa.CheckConstraint(
            "unknown_phase IS NULL OR unknown_phase IN ('purchase', 'ship')", name="ck_fulfillments_phase"
        ),
        sa.CheckConstraint(
            "(status = 'UNKNOWN_OUTCOME') = (unknown_phase IS NOT NULL)", name="ck_fulfillments_unknown_has_its_phase"
        ),
        sa.CheckConstraint("failed_attempts >= 0", name="ck_fulfillments_failed_attempts_not_negative"),
        sa.CheckConstraint(
            "status NOT IN ('PURCHASED', 'SHIPPING', 'SHIPPED', 'COMPLETED') OR purchased_at IS NOT NULL",
            name="ck_fulfillments_bought_has_purchased_at",
        ),
        sa.CheckConstraint(
            "status NOT IN ('SHIPPED', 'COMPLETED') OR shipped_at IS NOT NULL",
            name="ck_fulfillments_sent_has_shipped_at",
        ),
        sa.CheckConstraint(
            "status <> 'COMPLETED' OR (completed_at IS NOT NULL AND completed_by IS NOT NULL)",
            name="ck_fulfillments_completed_has_actor",
        ),
        sa.CheckConstraint(
            "status NOT IN ('FAILED', 'CANCELLED') OR purchased_at IS NULL",
            name="ck_fulfillments_a_purchased_unit_never_returns_to_the_pool",
        ),
    )
    op.create_index("ix_fulfillments_order_status", "fulfillments", ["order_id", "status"])
    op.create_index(
        "uq_fulfillments_provider_purchase_ref",
        "fulfillments",
        ["provider", "purchase_reference"],
        unique=True,
        postgresql_where=sa.text("purchase_reference IS NOT NULL"),
        sqlite_where=sa.text("purchase_reference IS NOT NULL"),
    )

    op.create_table(
        "fulfillment_items",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("fulfillment_id", sa.String(length=36), sa.ForeignKey("fulfillments.id"), nullable=False),
        sa.Column("order_item_id", sa.String(length=36), sa.ForeignKey("order_items.id"), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("fulfillment_id", "order_item_id", name="uq_fulfillment_items_fulfillment_line"),
        sa.CheckConstraint("quantity > 0", name="ck_fulfillment_items_quantity_positive"),
    )
    op.create_index("ix_fulfillment_items_fulfillment_id", "fulfillment_items", ["fulfillment_id"])
    op.create_index("ix_fulfillment_items_order_item_id", "fulfillment_items", ["order_item_id"])
    _enable_rls()


def _enable_rls() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    with_policy = (
        bind.execute(sa.text("SELECT count(*) FROM pg_roles WHERE rolname IN ('anon', 'authenticated')")).scalar() == 2
    )
    for table in TABLES:
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
        if with_policy:
            op.execute(
                f"CREATE POLICY deny_all_anon_authenticated ON public.{table} "
                "AS PERMISSIVE FOR ALL TO anon, authenticated USING (false) WITH CHECK (false)"
            )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        for table in TABLES:
            op.execute(f"DROP POLICY IF EXISTS deny_all_anon_authenticated ON public.{table}")
    op.drop_index("ix_fulfillment_items_order_item_id", table_name="fulfillment_items")
    op.drop_index("ix_fulfillment_items_fulfillment_id", table_name="fulfillment_items")
    op.drop_table("fulfillment_items")
    op.drop_index("uq_fulfillments_provider_purchase_ref", table_name="fulfillments")
    op.drop_index("ix_fulfillments_order_status", table_name="fulfillments")
    op.drop_table("fulfillments")
