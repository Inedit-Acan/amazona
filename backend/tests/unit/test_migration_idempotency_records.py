"""La migración de los registros de idempotencia (hardening pre-M44, ADR 0025), ejecutada de verdad.

Que cree lo mismo que declara el modelo (los tests usan `create_all`), que la clave única exista de verdad en la base y
que RLS quede activado desde esta misma migración.
"""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.db.base import Base
from app.db.models import idempotency_record  # noqa: F401 - registra la tabla en el metadata

MIGRATION = Path(__file__).resolve().parents[2] / "alembic" / "versions" / "d7a3c5e91b24_idempotency_records.py"
TABLE = "idempotency_records"


def load_migration():
    spec = importlib.util.spec_from_file_location("idempotency_records_migration", MIGRATION)
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


def insert(conn, **overrides) -> None:
    values = {
        "id": "i-1",
        "scope": "research.run",
        "actor_hash": "a" * 16,
        "key": "k-1",
        "request_hash": "f" * 64,
        "status": "IN_PROGRESS",
        "created_at": "2026-10-01 10:00:00",
    }
    values.update(overrides)
    names = ", ".join(values)
    marks = ", ".join(f":{name}" for name in values)
    conn.execute(sa.text(f"INSERT INTO {TABLE} ({names}) VALUES ({marks})"), values)


def test_the_revision_chains_after_the_external_actions_migration():
    module = load_migration()

    assert module.revision == "d7a3c5e91b24"
    assert module.down_revision == "c4e9a7d21f58"


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

    assert {c["name"]: c["nullable"] for c in migrated.get_columns(TABLE)} == {
        c.name: c.nullable for c in model.columns
    }
    migrated_uniques = {u["name"]: tuple(u["column_names"]) for u in migrated.get_unique_constraints(TABLE)}
    model_uniques = {
        c.name: tuple(col.name for col in c.columns) for c in model.constraints if isinstance(c, sa.UniqueConstraint)
    }
    assert migrated_uniques == model_uniques


def test_the_same_key_cannot_be_claimed_twice_in_the_same_scope_by_the_same_person(connection):
    run(connection, "upgrade")
    insert(connection)

    with pytest.raises(sa.exc.IntegrityError):
        insert(connection, id="i-2", request_hash="e" * 64)


@pytest.mark.parametrize(
    "different",
    [{"scope": "legal.run"}, {"actor_hash": "b" * 16}, {"key": "k-2"}],
    ids=["another operation", "another person", "another key"],
)
def test_a_different_scope_person_or_key_does_not_collide(connection, different):
    run(connection, "upgrade")
    insert(connection)

    insert(connection, id="i-2", **different)

    assert connection.execute(sa.text(f"SELECT count(*) FROM {TABLE}")).scalar_one() == 2


class RecordingOp:
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

    def __getattr__(self, name: str):
        return lambda *_a, **_k: None


def test_on_supabase_it_enables_rls_and_adds_the_deny_policy(monkeypatch):
    module = load_migration()
    fake = RecordingOp(supabase_roles=True)
    monkeypatch.setattr(module, "op", fake)

    module.upgrade()

    assert f"ALTER TABLE public.{TABLE} ENABLE ROW LEVEL SECURITY" in fake.statements
    assert any(
        s.startswith(f"CREATE POLICY deny_all_anon_authenticated ON public.{TABLE} ")
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
