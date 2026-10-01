"""external actions

Hardening pre-M44 (ADR 0024). Una fila por **operación** con efecto fuera del sistema
(publicar, activar publicidad, gastar) y el punto de su vida en que está. Es lo mínimo que
permite responder, tras una caída o un timeout, si la petición llegó a salir hacia el
proveedor: de eso depende si se puede liberar un presupuesto o volver a intentar.

- `PENDING`: la petición todavía no ha salido (si el proceso muere aquí no se ejecutó nada).
- `CALLING`: se confirmó que está a punto de salir o ha salido (si muere aquí, no se sabe).
- `SUCCEEDED` / `FAILED_CONFIRMED`: el proveedor lo confirmó (o no llegó a ser alcanzado).
- `UNKNOWN_OUTCOME`: pudo ejecutarse y no se conoce la respuesta.

Tres garantías, respaldadas por la base de datos y no solo por el código:

- `idempotency_key` única: la clave estable que se manda al proveedor identifica una sola
  operación;
- `(reference, sequence)` única: una operación concreta en un «sitio»;
- **a lo sumo una operación abierta por `reference`** (índice único parcial): dos ejecutores no
  pueden tener la misma acción entre manos, ni abrirse otra mientras una sigue sin resolver.

## RLS desde su propia migración

Se activa aquí, con el patrón de la ADR 0003: `ENABLE ROW LEVEL SECURITY` y, solo en Supabase, la
política `deny_all_anon_authenticated`. Sin `FORCE`: el backend es el dueño.

## Bajar

Es aditiva y no modifica datos existentes. Bajar elimina la tabla y lo que hubiera en ella (el
rastro de las operaciones externas): hay que exportarla antes si importa.

Revision ID: c4e9a7d21f58
Revises: b6d2f8a41c93
Create Date: 2026-10-01

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c4e9a7d21f58"
down_revision: str | Sequence[str] | None = "b6d2f8a41c93"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OPEN = "status IN ('PENDING', 'CALLING', 'UNKNOWN_OUTCOME')"


def upgrade() -> None:
    op.create_table(
        "external_actions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("reference", sa.String(length=255), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("operation", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=80), nullable=False),
        sa.Column("provider_idempotent", sa.Boolean(), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("correlation_id", sa.String(length=36), nullable=False),
        sa.Column("error", sa.String(length=2000), nullable=True),
        sa.Column("call_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", sa.String(length=255), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("idempotency_key", name="uq_external_actions_idempotency_key"),
        sa.UniqueConstraint("reference", "sequence", name="uq_external_actions_reference_sequence"),
    )
    op.create_index("ix_external_actions_reference", "external_actions", ["reference"])
    op.create_index(
        "uq_external_actions_one_open_per_reference",
        "external_actions",
        ["reference"],
        unique=True,
        postgresql_where=sa.text(_OPEN),
        sqlite_where=sa.text(_OPEN),
    )
    _enable_rls()


def _enable_rls() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    with_policy = (
        bind.execute(sa.text("SELECT count(*) FROM pg_roles WHERE rolname IN ('anon', 'authenticated')")).scalar() == 2
    )
    op.execute("ALTER TABLE public.external_actions ENABLE ROW LEVEL SECURITY")
    if with_policy:
        op.execute(
            "CREATE POLICY deny_all_anon_authenticated ON public.external_actions "
            "AS PERMISSIVE FOR ALL TO anon, authenticated USING (false) WITH CHECK (false)"
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP POLICY IF EXISTS deny_all_anon_authenticated ON public.external_actions")
    op.drop_index("uq_external_actions_one_open_per_reference", table_name="external_actions")
    op.drop_index("ix_external_actions_reference", table_name="external_actions")
    op.drop_table("external_actions")
