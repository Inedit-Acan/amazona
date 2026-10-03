"""verified revenue ledger

Milestone 45 (ADR 0030). El registro de ingresos verificados: una lista **inmutable** de hechos monetarios operativos
verificados, proyección determinista de los hechos de pago que `PaymentService` aplica. **No es el libro contable ni
fiscal de KOVA** y no es una segunda fuente de verdad: cada entrada nombra el `PaymentEvent` que la causó, el cobro, el
pedido y, si es un reembolso, el reembolso y la captura que revierte.

- `UNIQUE (payment_event_id)`; una `CAPTURE` por cobro y una entrada por reembolso (índices únicos
  parciales).
- Un `REFUND` hereda clasificación, moneda y cobro de su captura: clave ajena **compuesta** a la propia tabla.
- **Append-only**: un trigger rechaza `UPDATE` y `DELETE` (y `TRUNCATE` en PostgreSQL). Es el primer trigger del
  repositorio: PostgreSQL con función y dos triggers; SQLite con un trigger por operación. El texto es el mismo que el
  del modelo (`app/db/models/revenue.py`), y una prueba comprueba que no se separan.
- RLS con el patrón de la ADR 0003: `ENABLE ROW LEVEL SECURITY` y, solo en Supabase, `deny_all_anon_authenticated`.
  Sin `FORCE`: el backend es el dueño.

Los importes son `Numeric(18,4)`: nunca `float`. Ningún dato personal. **No hay retrorrelleno**: un cobro anterior a
esta migración queda como `outside_ledger` (ADR 0030 §13).

## Bajar

Quita el trigger, la función y la tabla. Es seguro porque el registro es una **proyección**: los hechos siguen en
`payment_events`, `payments` y `refunds`. Solo se prueba en local; **no se aplica a Supabase**.

Revision ID: c4e8b1d9a273
Revises: d7e2a9c4f1b8
Create Date: 2026-10-03

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c4e8b1d9a273"
down_revision: str | Sequence[str] | None = "d7e2a9c4f1b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "revenue_ledger_entries"

APPEND_ONLY_POSTGRESQL = (
    """CREATE OR REPLACE FUNCTION revenue_ledger_entries_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION USING ERRCODE = 'restrict_violation',
        MESSAGE = 'revenue_ledger_entries is append-only - ' || TG_OP || ' is rejected';
END;
$$""",
    """CREATE TRIGGER revenue_ledger_entries_append_only_row BEFORE UPDATE OR DELETE ON revenue_ledger_entries
FOR EACH ROW EXECUTE FUNCTION revenue_ledger_entries_append_only()""",
    """CREATE TRIGGER revenue_ledger_entries_append_only_truncate BEFORE TRUNCATE ON revenue_ledger_entries
FOR EACH STATEMENT EXECUTE FUNCTION revenue_ledger_entries_append_only()""",
)

APPEND_ONLY_SQLITE = (
    """CREATE TRIGGER revenue_ledger_entries_no_update BEFORE UPDATE ON revenue_ledger_entries
BEGIN
    SELECT RAISE(ABORT, 'revenue_ledger_entries is append-only - UPDATE is rejected');
END""",
    """CREATE TRIGGER revenue_ledger_entries_no_delete BEFORE DELETE ON revenue_ledger_entries
BEGIN
    SELECT RAISE(ABORT, 'revenue_ledger_entries is append-only - DELETE is rejected');
END""",
)


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("classification", sa.String(length=20), nullable=False),
        sa.Column("payment_event_id", sa.String(length=36), sa.ForeignKey("payment_events.id"), nullable=False),
        sa.Column("payment_id", sa.String(length=36), sa.ForeignKey("payments.id"), nullable=False),
        sa.Column("order_id", sa.String(length=36), sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("refund_id", sa.String(length=36), sa.ForeignKey("refunds.id"), nullable=True),
        sa.Column("capture_entry_id", sa.String(length=36), nullable=True),
        sa.Column("amount", sa.Numeric(18, 4), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("payment_event_id", name="uq_revenue_entries_payment_event"),
        sa.UniqueConstraint(
            "id", "classification", "currency", "payment_id", name="uq_revenue_entries_inheritance_target"
        ),
        sa.ForeignKeyConstraint(
            ["capture_entry_id", "classification", "currency", "payment_id"],
            [
                "revenue_ledger_entries.id",
                "revenue_ledger_entries.classification",
                "revenue_ledger_entries.currency",
                "revenue_ledger_entries.payment_id",
            ],
            name="fk_revenue_entries_refund_inherits_capture",
        ),
        sa.CheckConstraint("kind IN ('CAPTURE', 'REFUND')", name="ck_revenue_entries_kind"),
        sa.CheckConstraint(
            "classification IN ('ORDER_PAYMENT', 'DUPLICATE_RECEIPT', 'MISMATCH_RECEIPT')",
            name="ck_revenue_entries_classification",
        ),
        sa.CheckConstraint("amount > 0", name="ck_revenue_entries_amount_positive"),
        sa.CheckConstraint("length(currency) = 3", name="ck_revenue_entries_currency_shape"),
        sa.CheckConstraint(
            "(kind = 'REFUND') = (refund_id IS NOT NULL)", name="ck_revenue_entries_refund_names_refund"
        ),
        sa.CheckConstraint(
            "(kind = 'REFUND') = (capture_entry_id IS NOT NULL)", name="ck_revenue_entries_refund_names_capture"
        ),
    )
    op.create_index(
        "uq_revenue_entries_one_capture_per_payment",
        TABLE,
        ["payment_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'CAPTURE'"),
        sqlite_where=sa.text("kind = 'CAPTURE'"),
    )
    op.create_index(
        "uq_revenue_entries_one_entry_per_refund",
        TABLE,
        ["refund_id"],
        unique=True,
        postgresql_where=sa.text("refund_id IS NOT NULL"),
        sqlite_where=sa.text("refund_id IS NOT NULL"),
    )
    op.create_index("ix_revenue_ledger_entries_payment_id", TABLE, ["payment_id"])
    op.create_index("ix_revenue_ledger_entries_order_id", TABLE, ["order_id"])
    op.create_index("ix_revenue_ledger_entries_capture_entry_id", TABLE, ["capture_entry_id"])
    _append_only()
    _enable_rls()


def _append_only() -> None:
    dialect = op.get_bind().dialect.name
    statements = {"postgresql": APPEND_ONLY_POSTGRESQL, "sqlite": APPEND_ONLY_SQLITE}.get(dialect, ())
    for statement in statements:
        op.execute(statement)


def _enable_rls() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    with_policy = (
        bind.execute(sa.text("SELECT count(*) FROM pg_roles WHERE rolname IN ('anon', 'authenticated')")).scalar() == 2
    )
    op.execute(f"ALTER TABLE public.{TABLE} ENABLE ROW LEVEL SECURITY")
    if with_policy:
        op.execute(
            f"CREATE POLICY deny_all_anon_authenticated ON public.{TABLE} "
            "AS PERMISSIVE FOR ALL TO anon, authenticated USING (false) WITH CHECK (false)"
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(f"DROP POLICY IF EXISTS deny_all_anon_authenticated ON public.{TABLE}")
    op.drop_index("ix_revenue_ledger_entries_capture_entry_id", table_name=TABLE)
    op.drop_index("ix_revenue_ledger_entries_order_id", table_name=TABLE)
    op.drop_index("ix_revenue_ledger_entries_payment_id", table_name=TABLE)
    op.drop_index("uq_revenue_entries_one_entry_per_refund", table_name=TABLE)
    op.drop_index("uq_revenue_entries_one_capture_per_payment", table_name=TABLE)
    op.drop_table(TABLE)
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP FUNCTION IF EXISTS revenue_ledger_entries_append_only()")
