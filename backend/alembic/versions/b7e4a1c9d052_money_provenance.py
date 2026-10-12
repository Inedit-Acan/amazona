"""structured money provenance

Milestone 46 (ADR 0031). El origen del dinero (`mock`, `sandbox`, `real`) pasa a ser una **propiedad persistida del
hecho**, no una inferencia: una columna `provider_kind` en `payments`, `payment_events` y `revenue_ledger_entries`.
**No** en `refunds` (decisión del propietario): un reembolso tiene `payment_id` obligatorio, y su origen es el de su
cobro.

## Qué hace, en este orden

1. **Guarda, antes de tocar nada.** Se niega a ejecutarse si existe un cobro o un evento cuyo `provider` no sea el del
   simulador. Esa comparación **no clasifica nada**: solo impide rellenar `mock` sobre datos que no se puede demostrar
   que lo sean.
2. Añade `provider_kind` con un `DEFAULT 'mock'` **temporal**. El relleno es verdad y no una suposición: el registro de
   proveedores de pagos solo admite `MOCK` (y una prueba lo demuestra), así que ninguna fila anterior pudo nacer de
   otro origen.
3. Quita el `DEFAULT`: **el esquema final no tiene ninguno** y una operación nueva debe declarar su origen.
4. `CHECK (provider_kind IN ('mock','sandbox','real'))` en las tres tablas.
5. `UNIQUE (id, provider_kind)` en `payments` y `payment_events` (el objetivo de las claves ajenas compuestas).
6. Identidades por origen (F12, B-parcial): `(provider, provider_kind, provider_payment_ref)` y
   `(provider, provider_kind, provider_event_id)`. **`refunds` no cambia.**
7. Claves ajenas compuestas: el evento asociado es del origen de su cobro (`UNMATCHED`, con `payment_id` nulo,
   conserva el
   suyo); la entrada del registro es del origen de su cobro **y** de su evento.
8. Disparadores que rechazan el `UPDATE` que **cambia** `provider_kind` en `payments` y `payment_events`.

## SQLite (solo pruebas)

SQLite no puede quitar un `DEFAULT` ni añadir restricciones sin recrear la tabla (`batch_alter_table`), y **recrear la
tabla
destruye sus disparadores**: se comprobó que el registro dejaba de ser *append-only* sin ningún error. Por eso esta rama
**vuelve a crear los disparadores del registro** al terminar, y una prueba comprueba que siguen rechazando `UPDATE` y
`DELETE`.

## RLS

No hay tablas nuevas: las columnas heredan la RLS de sus tablas. Las funciones y los disparadores no tocan la RLS.

## Bajar

Se **niega** si alguna de las tres tablas tiene un `provider_kind` distinto de `mock` (perdería información que no se
puede
reconstruir). Quita disparadores, claves, restricciones y columnas, y restaura las identidades anteriores. Solo se
prueba en
local; **no se aplica a Supabase**.

Revision ID: b7e4a1c9d052
Revises: e5a1d7c93b04
Create Date: 2026-10-12

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b7e4a1c9d052"
down_revision: str | Sequence[str] | None = "e5a1d7c93b04"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: El único proveedor de pagos que ha existido: el simulador. Solo se usa para **negarse** a rellenar, nunca para
#: clasificar.
SIMULATOR = "simulated-payments"
KINDS = "provider_kind IN ('mock', 'sandbox', 'real')"
TABLES = ("payments", "payment_events", "revenue_ledger_entries")
LEDGER = "revenue_ledger_entries"

PROVIDER_KIND_IMMUTABLE_FUNCTION_POSTGRESQL = """CREATE OR REPLACE FUNCTION provider_kind_immutable() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $$
BEGIN
    RAISE EXCEPTION USING ERRCODE = 'restrict_violation',
        MESSAGE = TG_TABLE_NAME || '.provider_kind is immutable - it is a historical fact';
END;
$$"""


def provider_kind_immutable_trigger_postgresql(table: str) -> str:
    return f"""CREATE TRIGGER {table}_provider_kind_immutable BEFORE UPDATE OF provider_kind ON {table}
FOR EACH ROW WHEN (OLD.provider_kind IS DISTINCT FROM NEW.provider_kind) EXECUTE FUNCTION provider_kind_immutable()"""


def provider_kind_immutable_trigger_sqlite(table: str) -> str:
    return f"""CREATE TRIGGER {table}_provider_kind_immutable BEFORE UPDATE OF provider_kind ON {table}
WHEN OLD.provider_kind IS NOT NEW.provider_kind
BEGIN
    SELECT RAISE(ABORT, '{table}.provider_kind is immutable - it is a historical fact');
END"""


#: El mismo texto que `c4e8b1d9a273` y que el modelo: SQLite los pierde al recrear la tabla y hay que volver a crearlos.
LEDGER_APPEND_ONLY_SQLITE = (
    """CREATE TRIGGER revenue_ledger_entries_no_update BEFORE UPDATE ON revenue_ledger_entries
BEGIN
    SELECT RAISE(ABORT, 'revenue_ledger_entries is append-only - UPDATE is rejected');
END""",
    """CREATE TRIGGER revenue_ledger_entries_no_delete BEFORE DELETE ON revenue_ledger_entries
BEGIN
    SELECT RAISE(ABORT, 'revenue_ledger_entries is append-only - DELETE is rejected');
END""",
)
LEDGER_TRIGGER_NAMES_SQLITE = ("revenue_ledger_entries_no_update", "revenue_ledger_entries_no_delete")


def _dialect() -> str:
    return op.get_bind().dialect.name


def _refuse_to_backfill() -> None:
    """Antes de tocar nada: si hay un cobro o un evento que no es del simulador, no se puede afirmar que sea `mock`."""
    if _dialect() == "postgresql":
        op.execute(
            f"""DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM payments WHERE provider <> '{SIMULATOR}')
     OR EXISTS (SELECT 1 FROM payment_events WHERE provider <> '{SIMULATOR}') THEN
    RAISE EXCEPTION 'refusing to backfill mock: a payment or event has a provider other than the simulator';
  END IF;
END $$"""
        )
        return
    bind = op.get_bind()
    for table in ("payments", "payment_events"):
        foreign = bind.execute(
            sa.text(f"SELECT count(*) FROM {table} WHERE provider <> :simulator"), {"simulator": SIMULATOR}
        )
        if foreign.scalar():
            raise RuntimeError("refusing to backfill mock: a payment or event has a provider other than the simulator")


def _refuse_to_go_down() -> None:
    bind = op.get_bind()
    for table in TABLES:
        if bind.execute(sa.text(f"SELECT count(*) FROM {table} WHERE provider_kind <> 'mock'")).scalar():
            raise RuntimeError(
                f"refusing to downgrade: {table} has rows whose provider_kind is not mock; dropping the column would "
                "lose information that cannot be rebuilt"
            )


def _payments_identity(*, with_kind: bool) -> None:
    columns = (
        ["provider", "provider_kind", "provider_payment_ref"] if with_kind else ["provider", "provider_payment_ref"]
    )
    op.drop_index("uq_payments_provider_payment_ref", table_name="payments")
    op.create_index(
        "uq_payments_provider_payment_ref",
        "payments",
        columns,
        unique=True,
        postgresql_where=sa.text("provider_payment_ref IS NOT NULL"),
        sqlite_where=sa.text("provider_payment_ref IS NOT NULL"),
    )


def upgrade() -> None:
    _refuse_to_backfill()
    for table in TABLES:
        op.add_column(table, sa.Column("provider_kind", sa.String(length=10), nullable=False, server_default="mock"))
    if _dialect() == "postgresql":
        _upgrade_postgresql()
    else:
        _upgrade_batch()


def _upgrade_postgresql() -> None:
    for table in TABLES:
        op.alter_column(table, "provider_kind", server_default=None)
    op.create_check_constraint("ck_payments_provider_kind", "payments", KINDS)
    op.create_check_constraint("ck_payment_events_provider_kind", "payment_events", KINDS)
    op.create_check_constraint("ck_revenue_entries_provider_kind", LEDGER, KINDS)
    op.create_unique_constraint("uq_payments_id_provider_kind", "payments", ["id", "provider_kind"])
    op.create_unique_constraint("uq_payment_events_id_provider_kind", "payment_events", ["id", "provider_kind"])
    _payments_identity(with_kind=True)
    op.drop_constraint("uq_payment_events_provider_event", "payment_events", type_="unique")
    op.create_unique_constraint(
        "uq_payment_events_provider_event", "payment_events", ["provider", "provider_kind", "provider_event_id"]
    )
    op.create_foreign_key(
        "fk_payment_events_payment_kind",
        "payment_events",
        "payments",
        ["payment_id", "provider_kind"],
        ["id", "provider_kind"],
    )
    op.create_foreign_key(
        "fk_revenue_entries_payment_kind", LEDGER, "payments", ["payment_id", "provider_kind"], ["id", "provider_kind"]
    )
    op.create_foreign_key(
        "fk_revenue_entries_event_kind",
        LEDGER,
        "payment_events",
        ["payment_event_id", "provider_kind"],
        ["id", "provider_kind"],
    )
    op.execute(PROVIDER_KIND_IMMUTABLE_FUNCTION_POSTGRESQL)
    for table in ("payments", "payment_events"):
        op.execute(provider_kind_immutable_trigger_postgresql(table))


def _upgrade_batch() -> None:
    """SQLite: recrear la tabla es lo único posible, y destruye sus disparadores: se vuelven a crear al final."""
    with op.batch_alter_table("payments", recreate="always") as batch:
        batch.alter_column(
            "provider_kind", existing_type=sa.String(length=10), server_default=None, existing_nullable=False
        )
        batch.create_check_constraint("ck_payments_provider_kind", KINDS)
        batch.create_unique_constraint("uq_payments_id_provider_kind", ["id", "provider_kind"])
    _payments_identity(with_kind=True)
    with op.batch_alter_table("payment_events", recreate="always") as batch:
        batch.alter_column(
            "provider_kind", existing_type=sa.String(length=10), server_default=None, existing_nullable=False
        )
        batch.create_check_constraint("ck_payment_events_provider_kind", KINDS)
        batch.create_unique_constraint("uq_payment_events_id_provider_kind", ["id", "provider_kind"])
        batch.drop_constraint("uq_payment_events_provider_event", type_="unique")
        batch.create_unique_constraint(
            "uq_payment_events_provider_event", ["provider", "provider_kind", "provider_event_id"]
        )
        batch.create_foreign_key(
            "fk_payment_events_payment_kind", "payments", ["payment_id", "provider_kind"], ["id", "provider_kind"]
        )
    with op.batch_alter_table(LEDGER, recreate="always") as batch:
        batch.alter_column(
            "provider_kind", existing_type=sa.String(length=10), server_default=None, existing_nullable=False
        )
        batch.create_check_constraint("ck_revenue_entries_provider_kind", KINDS)
        batch.create_foreign_key(
            "fk_revenue_entries_payment_kind", "payments", ["payment_id", "provider_kind"], ["id", "provider_kind"]
        )
        batch.create_foreign_key(
            "fk_revenue_entries_event_kind",
            "payment_events",
            ["payment_event_id", "provider_kind"],
            ["id", "provider_kind"],
        )
    _recreate_sqlite_triggers()


def _recreate_sqlite_triggers() -> None:
    for name in LEDGER_TRIGGER_NAMES_SQLITE:
        op.execute(f"DROP TRIGGER IF EXISTS {name}")
    for statement in LEDGER_APPEND_ONLY_SQLITE:
        op.execute(statement)
    for table in ("payments", "payment_events"):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_provider_kind_immutable")
        op.execute(provider_kind_immutable_trigger_sqlite(table))


def downgrade() -> None:
    _refuse_to_go_down()
    if _dialect() == "postgresql":
        _downgrade_postgresql()
    else:
        _downgrade_batch()


def _downgrade_postgresql() -> None:
    for table in ("payments", "payment_events"):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_provider_kind_immutable ON {table}")
    op.execute("DROP FUNCTION IF EXISTS provider_kind_immutable()")
    op.drop_constraint("fk_revenue_entries_event_kind", LEDGER, type_="foreignkey")
    op.drop_constraint("fk_revenue_entries_payment_kind", LEDGER, type_="foreignkey")
    op.drop_constraint("fk_payment_events_payment_kind", "payment_events", type_="foreignkey")
    op.drop_constraint("uq_payment_events_provider_event", "payment_events", type_="unique")
    op.create_unique_constraint("uq_payment_events_provider_event", "payment_events", ["provider", "provider_event_id"])
    _payments_identity(with_kind=False)
    op.drop_constraint("uq_payment_events_id_provider_kind", "payment_events", type_="unique")
    op.drop_constraint("uq_payments_id_provider_kind", "payments", type_="unique")
    op.drop_constraint("ck_revenue_entries_provider_kind", LEDGER, type_="check")
    op.drop_constraint("ck_payment_events_provider_kind", "payment_events", type_="check")
    op.drop_constraint("ck_payments_provider_kind", "payments", type_="check")
    for table in TABLES:
        op.drop_column(table, "provider_kind")


def _downgrade_batch() -> None:
    for table in ("payments", "payment_events"):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_provider_kind_immutable")
    with op.batch_alter_table(LEDGER, recreate="always") as batch:
        batch.drop_constraint("fk_revenue_entries_event_kind", type_="foreignkey")
        batch.drop_constraint("fk_revenue_entries_payment_kind", type_="foreignkey")
        batch.drop_constraint("ck_revenue_entries_provider_kind", type_="check")
        batch.drop_column("provider_kind")
    with op.batch_alter_table("payment_events", recreate="always") as batch:
        batch.drop_constraint("fk_payment_events_payment_kind", type_="foreignkey")
        batch.drop_constraint("uq_payment_events_provider_event", type_="unique")
        batch.create_unique_constraint("uq_payment_events_provider_event", ["provider", "provider_event_id"])
        batch.drop_constraint("uq_payment_events_id_provider_kind", type_="unique")
        batch.drop_constraint("ck_payment_events_provider_kind", type_="check")
        batch.drop_column("provider_kind")
    _payments_identity(with_kind=False)
    with op.batch_alter_table("payments", recreate="always") as batch:
        batch.drop_constraint("uq_payments_id_provider_kind", type_="unique")
        batch.drop_constraint("ck_payments_provider_kind", type_="check")
        batch.drop_column("provider_kind")
    for name in LEDGER_TRIGGER_NAMES_SQLITE:
        op.execute(f"DROP TRIGGER IF EXISTS {name}")
    for statement in LEDGER_APPEND_ONLY_SQLITE:
        op.execute(statement)
