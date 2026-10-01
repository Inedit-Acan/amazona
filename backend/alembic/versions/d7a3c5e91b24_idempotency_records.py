"""idempotency records

Hardening pre-M44 (ADR 0025). Una fila por petición con efecto que llega con `Idempotency-Key`:
qué petición era (huella de su contenido), en qué punto está y, si terminó, lo que se devolvió.

- `(scope, actor_hash, key)` única: de N peticiones iguales a la vez, la base de datos deja pasar a
  una; las demás reciben la respuesta guardada o un 409. Dos operaciones distintas, o dos personas, no
  chocan aunque elijan la misma clave.
- No hay caducidad: una clave sin terminar no vuelve a estar disponible con el tiempo (ADR 0025).

## RLS desde su propia migración

Se activa aquí, con el patrón de la ADR 0003: `ENABLE ROW LEVEL SECURITY` y, solo en Supabase, la
política `deny_all_anon_authenticated`. Sin `FORCE`: el backend es el dueño.

## Bajar

Es aditiva y no modifica datos existentes. Bajar elimina la tabla y con ella el registro de las
peticiones ya atendidas: tras bajar, una clave usada antes se trataría como nueva.

Revision ID: d7a3c5e91b24
Revises: c4e9a7d21f58
Create Date: 2026-10-01

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d7a3c5e91b24"
down_revision: str | Sequence[str] | None = "c4e9a7d21f58"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "idempotency_records",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("scope", sa.String(length=64), nullable=False),
        sa.Column("actor_hash", sa.String(length=32), nullable=False),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("response_body", sa.JSON(), nullable=True),
        sa.Column("error", sa.String(length=2000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("scope", "actor_hash", "key", name="uq_idempotency_records_scope_actor_key"),
    )
    _enable_rls()


def _enable_rls() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    with_policy = (
        bind.execute(sa.text("SELECT count(*) FROM pg_roles WHERE rolname IN ('anon', 'authenticated')")).scalar() == 2
    )
    op.execute("ALTER TABLE public.idempotency_records ENABLE ROW LEVEL SECURITY")
    if with_policy:
        op.execute(
            "CREATE POLICY deny_all_anon_authenticated ON public.idempotency_records "
            "AS PERMISSIVE FOR ALL TO anon, authenticated USING (false) WITH CHECK (false)"
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP POLICY IF EXISTS deny_all_anon_authenticated ON public.idempotency_records")
    op.drop_table("idempotency_records")
