"""Apoyo compartido de las pruebas de las migraciones de M44 (ADR 0028).

Módulo auxiliar de tests, **no** un test. Ejecuta una migración de verdad sobre SQLite, comprueba que crea
**lo mismo que declara el modelo** (si no, los tests —que usan `create_all`— y la base real hablarían de tablas
distintas) y que activa RLS desde su propia migración con el patrón de la ADR 0003.
"""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

import app.db.models  # noqa: F401 - registra todas las tablas en el metadata
from app.db.base import Base

VERSIONS = Path(__file__).resolve().parents[2] / "alembic" / "versions"


def load_migration(filename: str):
    spec = importlib.util.spec_from_file_location(filename.removesuffix(".py"), VERSIONS / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def new_connection() -> sa.engine.Engine:
    return sa.create_engine("sqlite+pysqlite:///:memory:")


def run(conn, module, direction: str) -> None:
    with Operations.context(MigrationContext.configure(conn)):
        getattr(module, direction)()


def apply_prerequisites(conn, *tables: str) -> None:
    """Crea con el modelo las tablas a las que apuntan las claves ajenas de la migración (productos, proveedores…)."""
    Base.metadata.create_all(conn, tables=[Base.metadata.tables[name] for name in tables])


def assert_migration_matches_model(conn, tables: tuple[str, ...]) -> None:
    migrated = sa.inspect(conn)
    for table in tables:
        model = Base.metadata.tables[table]
        assert {c["name"] for c in migrated.get_columns(table)} == {c.name for c in model.columns}, table
        assert {c["name"]: c["nullable"] for c in migrated.get_columns(table)} == {
            c.name: c.nullable for c in model.columns
        }, table
        migrated_indexes = {
            i["name"]: (bool(i["unique"]), tuple(i["column_names"])) for i in migrated.get_indexes(table)
        }
        model_indexes = {i.name: (bool(i.unique), tuple(c.name for c in i.columns)) for i in model.indexes}
        assert migrated_indexes == model_indexes, table
        migrated_uniques = {u["name"]: tuple(u["column_names"]) for u in migrated.get_unique_constraints(table)}
        model_uniques = {
            c.name: tuple(col.name for col in c.columns)
            for c in model.constraints
            if isinstance(c, sa.UniqueConstraint)
        }
        assert migrated_uniques == model_uniques, table
        migrated_checks = {c["name"] for c in migrated.get_check_constraints(table)}
        model_checks = {c.name for c in model.constraints if isinstance(c, sa.CheckConstraint) and c.name}
        assert migrated_checks == model_checks, table


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

    def __getattr__(self, name: str):  # create_table, create_index, drop_*…: no interesan aquí
        return lambda *_a, **_k: None


def assert_rls_pattern(module, monkeypatch, tables: tuple[str, ...]) -> None:
    """RLS desde la propia migración: `ENABLE` siempre; la política `deny_all_anon_authenticated` solo en Supabase;
    nunca `FORCE`; y la bajada quita la política."""
    supabase = RecordingOp(supabase_roles=True)
    monkeypatch.setattr(module, "op", supabase)
    module.upgrade()
    module.downgrade()
    for table in tables:
        assert f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY" in supabase.statements, table
        assert any(
            s.startswith(f"CREATE POLICY deny_all_anon_authenticated ON public.{table} ")
            and "TO anon, authenticated" in s
            and "USING (false) WITH CHECK (false)" in s
            for s in supabase.statements
        ), table
        assert f"DROP POLICY IF EXISTS deny_all_anon_authenticated ON public.{table}" in supabase.statements, table
    assert not any("FORCE" in s for s in supabase.statements), "the backend owns the tables: RLS is never forced"

    plain = RecordingOp(supabase_roles=False)
    monkeypatch.setattr(module, "op", plain)
    module.upgrade()
    assert all(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY" in plain.statements for table in tables)
    assert not any("CREATE POLICY" in s for s in plain.statements), "the policy needs the Supabase-only roles"
