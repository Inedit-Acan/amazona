"""payments, payment events and refunds

Milestone 44 (ADR 0028). El dinero cobrado y devuelto, y la evidencia de lo que el proveedor contó.

- `payments`: un **intento de cobro** de un pedido. Un pedido tiene varios intentos. Como mucho un intento activo
  por pedido (un `UNKNOWN_OUTCOME` cuenta: bloquea nuevos intentos) y como mucho un `SUCCEEDED` por pedido: la
  defensa contra *nuestro* código. **No** impide guardar la evidencia de que el proveedor cobró dos veces: ese
  segundo cobro real se guarda como `DUPLICATE_CAPTURE`, y uno de un importe distinto, como `CAPTURE_MISMATCH`. Por
  eso no se exige `captured_amount <= amount`: el dinero que existió se registra tal cual. Sí se exige
  `refunded <= refund_committed <= captured`, que es lo que nuestro código no puede incumplir.
- `refunds`: una devolución. Entidad propia porque la iniciamos nosotros y porque `Σ reembolsos <= cobrado` exige
  contar los reembolsos en vuelo.
- `payment_events`: lo que un proveedor cuenta, verificado. Inmutable salvo su estado de proceso; único por
  `(provider, provider_event_id)`; **sin el cuerpo bruto** (solo su hash y una lista blanca de campos).

Los importes son `Numeric(18,4)`: nunca `float`. Ningún dato personal.

## RLS desde su propia migración

Se activa aquí, con el patrón de la ADR 0003: `ENABLE ROW LEVEL SECURITY` y, solo en Supabase, la política
`deny_all_anon_authenticated`. Sin `FORCE`: el backend es el dueño.

## Bajar

Es aditiva y no modifica datos existentes. Bajar elimina las tres tablas y lo que hubiera en ellas (el rastro de
los cobros, los reembolsos y los eventos): hay que exportarlas antes si importan.

Revision ID: a9d2e7b4c136
Revises: f6a1c8d3e925
Create Date: 2026-10-02

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a9d2e7b4c136"
down_revision: str | Sequence[str] | None = "f6a1c8d3e925"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("payments", "refunds", "payment_events")

_ACTIVE = "status IN ('REQUESTED', 'OPENING', 'UNKNOWN_OUTCOME', 'OPEN')"
_PAYMENT_STATUSES = (
    "status IN ('REQUESTED', 'OPENING', 'UNKNOWN_OUTCOME', 'OPEN', 'SUCCEEDED', 'FAILED', 'EXPIRED', "
    "'DUPLICATE_CAPTURE', 'CAPTURE_MISMATCH')"
)


def upgrade() -> None:
    op.create_table(
        "payments",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("order_id", sa.String(length=36), sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("amount", sa.Numeric(18, 4), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("provider_payment_ref", sa.String(length=128), nullable=True),
        sa.Column("captured_amount", sa.Numeric(18, 4), nullable=False, server_default=sa.text("0")),
        sa.Column("refund_committed_amount", sa.Numeric(18, 4), nullable=False, server_default=sa.text("0")),
        sa.Column("refunded_amount", sa.Numeric(18, 4), nullable=False, server_default=sa.text("0")),
        sa.Column("duplicate_of_payment_id", sa.String(length=36), sa.ForeignKey("payments.id"), nullable=True),
        sa.Column("last_failure_code", sa.String(length=64), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("succeeded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_event_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("correlation_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("order_id", "attempt_number", name="uq_payments_order_attempt"),
        sa.CheckConstraint(_PAYMENT_STATUSES, name="ck_payments_status"),
        sa.CheckConstraint("attempt_number >= 1", name="ck_payments_attempt_positive"),
        sa.CheckConstraint("amount > 0", name="ck_payments_amount_positive"),
        sa.CheckConstraint(
            "captured_amount >= 0 AND refund_committed_amount >= 0 AND refunded_amount >= 0",
            name="ck_payments_amounts_not_negative",
        ),
        sa.CheckConstraint(
            "refunded_amount <= refund_committed_amount AND refund_committed_amount <= captured_amount",
            name="ck_payments_refunds_within_captured",
        ),
        sa.CheckConstraint(
            "status IN ('SUCCEEDED', 'DUPLICATE_CAPTURE', 'CAPTURE_MISMATCH') OR captured_amount = 0",
            name="ck_payments_captured_only_when_captured",
        ),
        sa.CheckConstraint("status <> 'SUCCEEDED' OR captured_amount = amount", name="ck_payments_succeeded_is_exact"),
        sa.CheckConstraint(
            "(status = 'DUPLICATE_CAPTURE') = (duplicate_of_payment_id IS NOT NULL)",
            name="ck_payments_duplicate_names_the_original",
        ),
    )
    op.create_index("ix_payments_order_id", "payments", ["order_id"])
    op.create_index(
        "uq_payments_one_succeeded_per_order",
        "payments",
        ["order_id"],
        unique=True,
        postgresql_where=sa.text("status = 'SUCCEEDED'"),
        sqlite_where=sa.text("status = 'SUCCEEDED'"),
    )
    op.create_index(
        "uq_payments_one_active_attempt_per_order",
        "payments",
        ["order_id"],
        unique=True,
        postgresql_where=sa.text(_ACTIVE),
        sqlite_where=sa.text(_ACTIVE),
    )
    op.create_index(
        "uq_payments_provider_payment_ref",
        "payments",
        ["provider", "provider_payment_ref"],
        unique=True,
        postgresql_where=sa.text("provider_payment_ref IS NOT NULL"),
        sqlite_where=sa.text("provider_payment_ref IS NOT NULL"),
    )

    op.create_table(
        "refunds",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("payment_id", sa.String(length=36), sa.ForeignKey("payments.id"), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("origin", sa.String(length=12), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("amount", sa.Numeric(18, 4), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("reason", sa.String(length=32), nullable=False),
        sa.Column("provider_refund_ref", sa.String(length=128), nullable=True),
        sa.Column("requested_by", sa.String(length=255), nullable=True),
        sa.Column("failure_code", sa.String(length=64), nullable=True),
        sa.Column("correlation_id", sa.String(length=36), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("origin IN ('OPERATOR', 'PROVIDER')", name="ck_refunds_origin"),
        sa.CheckConstraint(
            "status IN ('REQUESTED', 'SENDING', 'UNKNOWN_OUTCOME', 'SUCCEEDED', 'FAILED')", name="ck_refunds_status"
        ),
        sa.CheckConstraint("amount > 0", name="ck_refunds_amount_positive"),
    )
    op.create_index("ix_refunds_payment_id", "refunds", ["payment_id"])
    op.create_index(
        "uq_refunds_provider_refund_ref",
        "refunds",
        ["provider", "provider_refund_ref"],
        unique=True,
        postgresql_where=sa.text("provider_refund_ref IS NOT NULL"),
        sqlite_where=sa.text("provider_refund_ref IS NOT NULL"),
    )

    op.create_table(
        "payment_events",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("provider_event_id", sa.String(length=128), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("payment_id", sa.String(length=36), sa.ForeignKey("payments.id"), nullable=True),
        sa.Column("refund_id", sa.String(length=36), sa.ForeignKey("refunds.id"), nullable=True),
        sa.Column("provider_payment_ref", sa.String(length=128), nullable=True),
        sa.Column("provider_refund_ref", sa.String(length=128), nullable=True),
        sa.Column("client_reference", sa.String(length=64), nullable=True),
        sa.Column("amount", sa.Numeric(18, 4), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("data", sa.JSON(), nullable=True),
        sa.Column("processing_status", sa.String(length=16), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.UniqueConstraint("provider", "provider_event_id", name="uq_payment_events_provider_event"),
        sa.CheckConstraint(
            "processing_status IN ('RECEIVED', 'APPLIED', 'STALE', 'CONFLICT', 'UNMATCHED', 'REJECTED')",
            name="ck_payment_events_processing_status",
        ),
        sa.CheckConstraint("(amount IS NULL) = (currency IS NULL)", name="ck_payment_events_amount_has_currency"),
    )
    op.create_index("ix_payment_events_payment_id", "payment_events", ["payment_id"])
    op.create_index(
        "ix_payment_events_received",
        "payment_events",
        ["received_at"],
        postgresql_where=sa.text("processing_status = 'RECEIVED'"),
        sqlite_where=sa.text("processing_status = 'RECEIVED'"),
    )
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
    op.drop_index("ix_payment_events_received", table_name="payment_events")
    op.drop_index("ix_payment_events_payment_id", table_name="payment_events")
    op.drop_table("payment_events")
    op.drop_index("uq_refunds_provider_refund_ref", table_name="refunds")
    op.drop_index("ix_refunds_payment_id", table_name="refunds")
    op.drop_table("refunds")
    op.drop_index("uq_payments_provider_payment_ref", table_name="payments")
    op.drop_index("uq_payments_one_active_attempt_per_order", table_name="payments")
    op.drop_index("uq_payments_one_succeeded_per_order", table_name="payments")
    op.drop_index("ix_payments_order_id", table_name="payments")
    op.drop_table("payments")
