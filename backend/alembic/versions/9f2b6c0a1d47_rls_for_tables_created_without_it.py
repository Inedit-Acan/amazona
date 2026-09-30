"""rls for tables created without it

Migración de seguridad correctiva. Enmienda las migraciones publicadas del
Milestone 39, 40 y 41 **sin modificarlas**: cada una creó tablas en el esquema
`public` sin activar Row Level Security, contra la ADR 0003.

- `supplier_capabilities` (M39)
- `exchange_rates` (M40)
- `regulatory_requirements`, `regulatory_anchors` y `compliance_evidence` (M41)

## Por qué importa

En Supabase, `anon` y `authenticated` reciben por defecto todos los privilegios
sobre las tablas nuevas de `public` (`pg_default_acl`), y PostgREST las expone con
la clave `anon`. Una tabla sin RLS es legible y escribible por cualquiera que tenga
esa clave. CI no lo detecta: en un PostgreSQL vacío no hay ningún rol `anon`.

## Qué hace

El mismo patrón de la ADR 0003 y de `10de07bea94d`:

- `ENABLE ROW LEVEL SECURITY`, que ya deniega a cualquier rol que no sea el dueño;
- y, solo si existen los roles `anon` y `authenticated` (es decir, en Supabase), la
  política explícita `deny_all_anon_authenticated`.

**No** se aplica `FORCE ROW LEVEL SECURITY`: el backend conecta como `postgres`, dueño
de las tablas, y no debe verse afectado (ADR 0003). No se define ningún modelo de
acceso: el efecto es cerrar el acceso público por completo. **Ningún flujo actual
depende de acceso directo a estas tablas**: el Control Center solo usa Supabase para
autenticación (`supabase.auth.*`), y el backend solo para las claves de firma de los
tokens.

En una base que no es PostgreSQL (los tests con SQLite) no hace nada.

## Bajar

`DROP POLICY IF EXISTS` y `DISABLE ROW LEVEL SECURITY`: vuelve al estado anterior, que
es el defectuoso. Es reversible y no toca datos.

Revision ID: 9f2b6c0a1d47
Revises: e5f8a2c1b7d4
Create Date: 2026-09-30

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "9f2b6c0a1d47"
down_revision: str | Sequence[str] | None = "e5f8a2c1b7d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Las tablas que las migraciones publicadas crearon sin RLS. Son cinco y son las que
#: hay que cerrar; toda tabla creada por una migración posterior debe activar su RLS en
#: esa misma migración (lo comprueba `tests/unit/test_migration_rls_gap.py`).
_TABLES = (
    "supplier_capabilities",
    "exchange_rates",
    "regulatory_requirements",
    "regulatory_anchors",
    "compliance_evidence",
)
_POLICY_NAME = "deny_all_anon_authenticated"


def _supabase_roles_exist(bind: sa.engine.Connection) -> bool:
    found = bind.execute(
        sa.text("SELECT count(*) FROM pg_roles WHERE rolname IN ('anon', 'authenticated')")
    ).scalar()
    return found == 2


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    with_policy = _supabase_roles_exist(bind)
    for table in _TABLES:
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
        if with_policy:
            op.execute(f"DROP POLICY IF EXISTS {_POLICY_NAME} ON public.{table}")
            op.execute(
                f"CREATE POLICY {_POLICY_NAME} ON public.{table} "
                "AS PERMISSIVE FOR ALL TO anon, authenticated USING (false) WITH CHECK (false)"
            )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for table in reversed(_TABLES):
        op.execute(f"DROP POLICY IF EXISTS {_POLICY_NAME} ON public.{table}")
        op.execute(f"ALTER TABLE public.{table} DISABLE ROW LEVEL SECURITY")
