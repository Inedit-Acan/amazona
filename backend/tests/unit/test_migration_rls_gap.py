"""La migración de seguridad que cierra el hueco de RLS de M39–M41, y la guarda que
impide que vuelva a abrirse.

Las migraciones publicadas de M39, M40 y M41 crearon cinco tablas de `public` sin
Row Level Security, contra la ADR 0003. En Supabase, `anon` y `authenticated` reciben
todos los privilegios por defecto sobre las tablas nuevas, así que una tabla sin RLS
queda expuesta por PostgREST. CI no lo veía: en un PostgreSQL vacío no hay rol `anon`.
"""

import importlib.util
import re
from pathlib import Path
from types import SimpleNamespace

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

VERSIONS = Path(__file__).resolve().parents[2] / "alembic" / "versions"
RLS_MIGRATION = VERSIONS / "9f2b6c0a1d47_rls_for_tables_created_without_it.py"

FIVE_TABLES = [
    "supplier_capabilities",
    "exchange_rates",
    "regulatory_requirements",
    "regulatory_anchors",
    "compliance_evidence",
]


def load(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RecordingOp:
    """Un `op` de Alembic falso que anota el SQL y responde como si hubiera un
    PostgreSQL de Supabase (con o sin los roles `anon` y `authenticated`)."""

    def __init__(self, *, dialect: str = "postgresql", supabase_roles: bool = True) -> None:
        self.statements: list[str] = []
        self._dialect = dialect
        self._roles = 2 if supabase_roles else 0

    def get_bind(self):
        roles = self._roles
        return SimpleNamespace(
            dialect=SimpleNamespace(name=self._dialect),
            execute=lambda *_a, **_k: SimpleNamespace(scalar=lambda: roles),
        )

    def execute(self, statement: str) -> None:
        self.statements.append(statement)


# --- La cadena ----------------------------------------------------------------


def test_the_security_revision_chains_directly_after_m41():
    security = load(RLS_MIGRATION)

    assert security.revision == "9f2b6c0a1d47"
    assert security.down_revision == "e5f8a2c1b7d4"


def test_it_covers_exactly_the_five_tables_the_published_migrations_left_open():
    assert list(load(RLS_MIGRATION)._TABLES) == FIVE_TABLES


# --- Lo que hace en PostgreSQL ---------------------------------------------------


def test_on_supabase_it_enables_rls_and_adds_the_deny_policy_on_each_table(monkeypatch):
    module = load(RLS_MIGRATION)
    fake = RecordingOp()
    monkeypatch.setattr(module, "op", fake)

    module.upgrade()

    for table in FIVE_TABLES:
        assert f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY" in fake.statements
        assert any(
            s.startswith(f"CREATE POLICY deny_all_anon_authenticated ON public.{table} ")
            and "TO anon, authenticated" in s
            and "USING (false) WITH CHECK (false)" in s
            for s in fake.statements
        )


def test_it_never_forces_rls_because_the_backend_owns_the_tables(monkeypatch):
    module = load(RLS_MIGRATION)
    fake = RecordingOp()
    monkeypatch.setattr(module, "op", fake)

    module.upgrade()
    module.downgrade()

    assert not any("FORCE" in s for s in fake.statements)


def test_on_plain_postgresql_it_enables_rls_and_skips_the_policy_that_needs_supabase_roles(monkeypatch):
    module = load(RLS_MIGRATION)
    fake = RecordingOp(supabase_roles=False)
    monkeypatch.setattr(module, "op", fake)

    module.upgrade()

    assert len([s for s in fake.statements if "ENABLE ROW LEVEL SECURITY" in s]) == 5
    assert not any("CREATE POLICY" in s for s in fake.statements)


def test_the_downgrade_drops_the_policy_and_disables_rls(monkeypatch):
    module = load(RLS_MIGRATION)
    fake = RecordingOp()
    monkeypatch.setattr(module, "op", fake)

    module.downgrade()

    for table in FIVE_TABLES:
        assert f"DROP POLICY IF EXISTS deny_all_anon_authenticated ON public.{table}" in fake.statements
        assert f"ALTER TABLE public.{table} DISABLE ROW LEVEL SECURITY" in fake.statements


def test_on_sqlite_it_does_nothing_in_either_direction():
    module = load(RLS_MIGRATION)
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    with engine.connect() as connection, Operations.context(MigrationContext.configure(connection)):
        module.upgrade()
        module.downgrade()


# --- La guarda: ninguna tabla nueva sin RLS -------------------------------------------


def _created_tables_and_rls_mentions() -> tuple[dict[str, str], set[str]]:
    created: dict[str, str] = {}
    quoted: set[str] = set()
    for path in sorted(VERSIONS.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r"create_table\(\s*[\"']([a-z_]+)[\"']", text):
            created[match.group(1)] = path.name
        if re.search(r"ROW LEVEL SECURITY", text, re.IGNORECASE):
            quoted |= set(re.findall(r"[\"']([a-z_]+)[\"']", text))
    return created, quoted


def test_every_table_any_migration_creates_gets_row_level_security_somewhere():
    """Regresión del hueco de M39–M41: una migración que crea una tabla debe
    activar RLS en ella —en la misma o en una posterior—, y el nombre de la tabla
    tiene que aparecer en un fichero que active RLS."""
    created, quoted = _created_tables_and_rls_mentions()

    without_rls = sorted(table for table in created if table not in quoted)

    assert without_rls == [], (
        f"tables created without Row Level Security anywhere in the chain: {without_rls}"
    )
