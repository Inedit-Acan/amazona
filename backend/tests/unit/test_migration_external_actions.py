"""La migración de las acciones externas (hardening pre-M44, ADR 0024), ejecutada de verdad.

Tres cosas que importan y que solo una migración ejecutada demuestra: que **crea lo mismo que declara el
modelo** (si no, los tests —que usan `create_all`— y la base real hablarían de tablas distintas), que las
garantías que respaldan la base de datos (clave única, una operación abierta por `reference`) existen de verdad,
y que RLS queda activado desde esta misma migración.
"""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.db.base import Base
from app.db.models import external_action  # noqa: F401 - registra la tabla en el metadata

MIGRATION = Path(__file__).resolve().parents[2] / "alembic" / "versions" / "c4e9a7d21f58_external_actions.py"
TABLE = "external_actions"


def load_migration():
    spec = importlib.util.spec_from_file_location("external_actions_migration", MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def connection():
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    with engine.connect() as conn:
        yield conn
    engine.dispose()


def run(conn, direction: str) -> None:
    module = load_migration()
    with Operations.context(MigrationContext.configure(conn)):
        getattr(module, direction)()


def columns(conn) -> dict[str, tuple[bool, str]]:
    inspector = sa.inspect(conn)
    return {c["name"]: (c["nullable"], type(c["type"]).__name__) for c in inspector.get_columns(TABLE)}


def insert(conn, **overrides) -> None:
    values = {
        "id": "a-1",
        "reference": "pipeline_step:run-1:marketing",
        "sequence": 1,
        "provider": "simulated",
        "operation": "activate_ads",
        "idempotency_key": "amz-key-1",
        "provider_idempotent": True,
        "request_fingerprint": "f" * 64,
        "amount": 100.0,
        "status": "PENDING",
        "correlation_id": "corr-1",
        "created_at": "2026-10-01 10:00:00",
        "updated_at": "2026-10-01 10:00:00",
    }
    values.update(overrides)
    names = ", ".join(values)
    marks = ", ".join(f":{name}" for name in values)
    conn.execute(sa.text(f"INSERT INTO {TABLE} ({names}) VALUES ({marks})"), values)


# --- La cadena ----------------------------------------------------------------------


def test_the_revision_chains_after_the_national_transpositions_migration():
    module = load_migration()

    assert module.revision == "c4e9a7d21f58"
    assert module.down_revision == "b6d2f8a41c93"


# --- Subir y bajar ------------------------------------------------------------------


def test_upgrade_creates_the_table_and_downgrade_removes_it(connection):
    run(connection, "upgrade")
    assert TABLE in sa.inspect(connection).get_table_names()

    run(connection, "downgrade")

    assert TABLE not in sa.inspect(connection).get_table_names()


def test_the_migration_can_be_applied_again_after_a_downgrade(connection):
    run(connection, "upgrade")
    run(connection, "downgrade")

    run(connection, "upgrade")

    assert TABLE in sa.inspect(connection).get_table_names()


def test_the_migration_creates_what_the_model_declares(connection):
    run(connection, "upgrade")
    migrated = sa.inspect(connection)
    model = Base.metadata.tables[TABLE]

    assert {c["name"] for c in migrated.get_columns(TABLE)} == {c.name for c in model.columns}
    model_nullable = {c.name: c.nullable for c in model.columns}
    assert {c["name"]: c["nullable"] for c in migrated.get_columns(TABLE)} == model_nullable
    migrated_indexes = {i["name"]: (bool(i["unique"]), tuple(i["column_names"])) for i in migrated.get_indexes(TABLE)}
    model_indexes = {i.name: (bool(i.unique), tuple(c.name for c in i.columns)) for i in model.indexes}
    assert migrated_indexes == model_indexes
    migrated_uniques = {u["name"]: tuple(u["column_names"]) for u in migrated.get_unique_constraints(TABLE)}
    model_uniques = {
        c.name: tuple(col.name for col in c.columns) for c in model.constraints if isinstance(c, sa.UniqueConstraint)
    }
    assert migrated_uniques == model_uniques


# --- Lo que garantiza la base de datos ------------------------------------------------


def test_the_provider_key_is_unique(connection):
    run(connection, "upgrade")
    insert(connection)

    with pytest.raises(sa.exc.IntegrityError):
        insert(connection, id="a-2", reference="pipeline_step:run-2:marketing", sequence=1)


def test_a_site_cannot_repeat_a_sequence(connection):
    run(connection, "upgrade")
    insert(connection, status="FAILED_CONFIRMED")

    with pytest.raises(sa.exc.IntegrityError):
        insert(connection, id="a-2", idempotency_key="amz-key-2", status="FAILED_CONFIRMED")


@pytest.mark.parametrize("status", ["PENDING", "CALLING", "UNKNOWN_OUTCOME"])
def test_a_site_cannot_have_two_open_operations(connection, status):
    run(connection, "upgrade")
    insert(connection, status=status)

    with pytest.raises(sa.exc.IntegrityError):
        insert(connection, id="a-2", sequence=2, idempotency_key="amz-key-2", status="PENDING")


@pytest.mark.parametrize("status", ["SUCCEEDED", "FAILED_CONFIRMED"])
def test_a_closed_operation_does_not_hold_the_site(connection, status):
    run(connection, "upgrade")
    insert(connection, status=status)

    insert(connection, id="a-2", sequence=2, idempotency_key="amz-key-2", status="PENDING")

    assert connection.execute(sa.text(f"SELECT count(*) FROM {TABLE}")).scalar_one() == 2


def test_different_sites_have_their_own_open_operation(connection):
    run(connection, "upgrade")
    insert(connection)

    insert(connection, id="a-2", reference="pipeline_step:run-2:marketing", idempotency_key="amz-key-2")

    assert connection.execute(sa.text(f"SELECT count(*) FROM {TABLE}")).scalar_one() == 2


def test_the_migration_does_not_touch_other_tables(connection):
    connection.execute(sa.text("CREATE TABLE bystander (id INTEGER PRIMARY KEY, note TEXT)"))
    connection.execute(sa.text("INSERT INTO bystander (id, note) VALUES (1, 'unchanged')"))

    run(connection, "upgrade")
    run(connection, "downgrade")

    assert connection.execute(sa.text("SELECT note FROM bystander")).scalar_one() == "unchanged"


# --- RLS desde su propia migración ----------------------------------------------------


class RecordingOp:
    """Un `op` de Alembic falso que anota el SQL y responde como un PostgreSQL con o sin los roles de Supabase."""

    def __init__(self, *, supabase_roles: bool) -> None:
        self.statements: list[str] = []
        self._roles = 2 if supabase_roles else 0

    def get_bind(self):
        roles = self._roles
        return SimpleNamespace(
            dialect=SimpleNamespace(name="postgresql"),
            execute=lambda *_a, **_k: SimpleNamespace(scalar=lambda: roles),
        )

    def execute(self, statement: str) -> None:
        self.statements.append(statement)

    def __getattr__(self, name: str):  # create_table, create_index, drop_*...: no interesan aquí
        return lambda *_a, **_k: None


def test_on_supabase_it_enables_rls_and_adds_the_deny_policy(monkeypatch):
    module = load_migration()
    fake = RecordingOp(supabase_roles=True)
    monkeypatch.setattr(module, "op", fake)

    module.upgrade()

    assert f"ALTER TABLE public.{TABLE} ENABLE ROW LEVEL SECURITY" in fake.statements
    assert any(
        s.startswith(f"CREATE POLICY deny_all_anon_authenticated ON public.{TABLE} ")
        and "TO anon, authenticated" in s
        and "USING (false) WITH CHECK (false)" in s
        for s in fake.statements
    )


def test_on_plain_postgresql_it_enables_rls_without_the_supabase_only_policy(monkeypatch):
    module = load_migration()
    fake = RecordingOp(supabase_roles=False)
    monkeypatch.setattr(module, "op", fake)

    module.upgrade()

    assert f"ALTER TABLE public.{TABLE} ENABLE ROW LEVEL SECURITY" in fake.statements
    assert not any("CREATE POLICY" in s for s in fake.statements)


def test_rls_is_never_forced_and_the_downgrade_drops_the_policy(monkeypatch):
    module = load_migration()
    fake = RecordingOp(supabase_roles=True)
    monkeypatch.setattr(module, "op", fake)

    module.upgrade()
    module.downgrade()

    assert not any("FORCE" in s for s in fake.statements)
    assert f"DROP POLICY IF EXISTS deny_all_anon_authenticated ON public.{TABLE}" in fake.statements
