"""orders and order items

Milestone 44 (ADR 0028). Un pedido y sus líneas.

- `orders`: lo que un cliente ha pedido y por cuánto. **Sin datos personales**: el cliente es una referencia
  opaca (`customer_ref`), y un `CHECK` impide que lleve un `@`. En una simulación empieza por `sim_` y fuera de
  ella no puede hacerlo (otro `CHECK`): un pedido de prueba no se confunde con uno real.
- `order_items`: una línea con identidad propia (`id`) y orden estable (`line_number`, único por pedido). **No
  hay unicidad por producto**: un mismo producto puede estar en varias líneas (variante, proveedor, cotización,
  precio, lote). `allocated_quantity` cuenta las unidades ya asignadas a un fulfillment y no puede superar a
  `quantity`.

Los importes son `Numeric(18,4)`: nunca `float`. Un coste de proveedor desconocido es `NULL`, nunca cero.

## RLS desde su propia migración

Se activa aquí, con el patrón de la ADR 0003: `ENABLE ROW LEVEL SECURITY` y, solo en Supabase, la política
`deny_all_anon_authenticated`. Sin `FORCE`: el backend es el dueño.

## Bajar

Es aditiva y no modifica datos existentes. Bajar elimina las dos tablas y lo que hubiera en ellas: hay que
exportarlas antes si importan.

Revision ID: f6a1c8d3e925
Revises: e1b8d4a62f37
Create Date: 2026-10-02

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f6a1c8d3e925"
down_revision: str | Sequence[str] | None = "e1b8d4a62f37"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("orders", "order_items")


def upgrade() -> None:
    op.create_table(
        "orders",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("customer_ref", sa.String(length=64), nullable=False),
        sa.Column("market", sa.String(length=16), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("amount_due", sa.Numeric(18, 4), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("is_simulated", sa.Boolean(), nullable=False),
        sa.Column("correlation_id", sa.String(length=36), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('AWAITING_PAYMENT', 'PAID', 'COMPLETED', 'CANCELLED')", name="ck_orders_status"),
        sa.CheckConstraint("amount_due > 0", name="ck_orders_amount_due_positive"),
        sa.CheckConstraint("replace(customer_ref, '@', '') = customer_ref", name="ck_orders_customer_ref_not_an_email"),
        sa.CheckConstraint(
            "(is_simulated AND substr(customer_ref, 1, 4) = 'sim_') "
            "OR ((NOT is_simulated) AND substr(customer_ref, 1, 4) <> 'sim_')",
            name="ck_orders_simulation_prefix",
        ),
    )
    op.create_index("ix_orders_status_created_at", "orders", ["status", "created_at"])

    op.create_table(
        "order_items",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("order_id", sa.String(length=36), sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.String(length=36), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("supplier_id", sa.String(length=36), sa.ForeignKey("suppliers.id"), nullable=True),
        sa.Column("supplier_quote_id", sa.String(length=36), sa.ForeignKey("supplier_quotes.id"), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("allocated_quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price", sa.Numeric(18, 4), nullable=False),
        sa.Column("line_total", sa.Numeric(18, 4), nullable=False),
        sa.Column("unit_cost", sa.Numeric(18, 4), nullable=True),
        sa.Column("cost_provenance", sa.String(length=32), nullable=True),
        sa.Column("cost_source", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("order_id", "line_number", name="uq_order_items_order_line"),
        sa.CheckConstraint("line_number >= 1", name="ck_order_items_line_number_positive"),
        sa.CheckConstraint("quantity > 0", name="ck_order_items_quantity_positive"),
        sa.CheckConstraint(
            "allocated_quantity >= 0 AND allocated_quantity <= quantity",
            name="ck_order_items_allocation_within_quantity",
        ),
        sa.CheckConstraint("unit_price > 0 AND line_total > 0", name="ck_order_items_prices_positive"),
        sa.CheckConstraint("unit_cost IS NULL OR unit_cost >= 0", name="ck_order_items_cost_not_negative"),
        sa.CheckConstraint(
            "(unit_cost IS NULL) = (cost_provenance IS NULL)", name="ck_order_items_cost_has_its_provenance"
        ),
    )
    op.create_index("ix_order_items_order_id", "order_items", ["order_id"])
    op.create_index("ix_order_items_product_id", "order_items", ["product_id"])
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
        for table in reversed(TABLES):
            op.execute(f"DROP POLICY IF EXISTS deny_all_anon_authenticated ON public.{table}")
    op.drop_index("ix_order_items_product_id", table_name="order_items")
    op.drop_index("ix_order_items_order_id", table_name="order_items")
    op.drop_table("order_items")
    op.drop_index("ix_orders_status_created_at", table_name="orders")
    op.drop_table("orders")
