"""La migración de las garantías de identidad (hardening pre-M44, ADR 0026), ejecutada de verdad y con datos dentro.

Lo que más importa de esta migración es lo que **no** hace: no borra, no fusiona y no arregla filas. Con duplicados ya
presentes, se niega a continuar antes de cambiar nada y dice cuáles son. El esquema de partida está escrito a mano y
**congelado** (el que tenían estas cinco tablas antes): comparar contra los modelos vivos caducaría con el siguiente
cambio.
"""

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.db.base import Base
from app.db.models import budget, pipeline_kill_switch, pipeline_review  # noqa: F401 - registran las tablas

MIGRATION = Path(__file__).resolve().parents[2] / "alembic" / "versions" / "e1b8d4a62f37_database_identity_guards.py"

SCHEMA_BEFORE = (
    "CREATE TABLE budgets (id VARCHAR(36) PRIMARY KEY, name VARCHAR(255) NOT NULL, hard_limit NUMERIC(12,2) NOT NULL)",
    "CREATE TABLE budget_allocations (id VARCHAR(36) PRIMARY KEY, budget_id VARCHAR(36) NOT NULL)",
    "CREATE TABLE pipeline_kill_switch (id VARCHAR(36) PRIMARY KEY, name VARCHAR(64) NOT NULL, "
    "enabled BOOLEAN NOT NULL)",
    "CREATE TABLE financial_events (id VARCHAR(36) PRIMARY KEY, type VARCHAR(32) NOT NULL, "
    "amount NUMERIC(12,2) NOT NULL, reference VARCHAR(255))",
    "CREATE TABLE pipeline_reviews (id VARCHAR(36) PRIMARY KEY, pipeline_run_id VARCHAR(36) NOT NULL, "
    "kind VARCHAR(16) NOT NULL, step VARCHAR(32), status VARCHAR(16) NOT NULL)",
)
GUARDED_TABLES = ("budgets", "budget_allocations", "pipeline_kill_switch", "financial_events", "pipeline_reviews")

#: Lo legítimo, que tiene que sobrevivir a la migración tal cual.
GOOD_DATA = (
    "INSERT INTO budgets VALUES ('b-1', 'main', 1000)",
    "INSERT INTO budget_allocations VALUES ('a-1', 'b-1')",
    "INSERT INTO pipeline_kill_switch VALUES ('k-1', 'pipeline', 1)",
    "INSERT INTO financial_events VALUES ('e-1', 'RESERVE', 10, 'ref-1')",
    "INSERT INTO financial_events VALUES ('e-2', 'COMMIT', 10, 'ref-1')",
    "INSERT INTO financial_events VALUES ('e-3', 'RESERVE', 10, NULL)",
    "INSERT INTO financial_events VALUES ('e-4', 'RESERVE', 10, NULL)",
    "INSERT INTO pipeline_reviews VALUES ('r-1', 'run-1', 'ACTION_GATE', 'ecommerce', 'CONSUMED')",
    "INSERT INTO pipeline_reviews VALUES ('r-2', 'run-1', 'ACTION_GATE', 'ecommerce', 'PENDING')",
    "INSERT INTO pipeline_reviews VALUES ('r-3', 'run-1', 'POST_HOC', NULL, 'PENDING')",
)

#: Un duplicado por cada garantía: qué filas lo provocan y qué tiene que decir el error.
DUPLICATES = {
    "budgets.name": ("INSERT INTO budgets VALUES ('b-2', 'main', 5)",),
    "budget_allocations.budget_id": ("INSERT INTO budget_allocations VALUES ('a-2', 'b-1')",),
    "pipeline_kill_switch.name": ("INSERT INTO pipeline_kill_switch VALUES ('k-2', 'pipeline', 0)",),
    "one RESERVE per reference": ("INSERT INTO financial_events VALUES ('e-9', 'RESERVE', 10, 'ref-1')",),
    "one COMMIT or RELEASE per reference": ("INSERT INTO financial_events VALUES ('e-9', 'RELEASE', 10, 'ref-1')",),
    "one pending ACTION_GATE per step": (
        "INSERT INTO pipeline_reviews VALUES ('r-9', 'run-1', 'ACTION_GATE', 'ecommerce', 'PENDING')",
    ),
    "one pending POST_HOC per run": (
        "INSERT INTO pipeline_reviews VALUES ('r-9', 'run-1', 'POST_HOC', NULL, 'PENDING')",
    ),
}


def load_migration():
    spec = importlib.util.spec_from_file_location("identity_guards_migration", MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def connection():
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    with engine.connect() as conn:
        for statement in SCHEMA_BEFORE:
            conn.execute(sa.text(statement))
        for statement in GOOD_DATA:
            conn.execute(sa.text(statement))
        conn.commit()
        yield conn
    engine.dispose()


def run(conn, direction: str) -> None:
    module = load_migration()
    with Operations.context(MigrationContext.configure(conn)):
        getattr(module, direction)()


def guards(conn) -> set[str]:
    inspector = sa.inspect(conn)
    found: set[str] = set()
    for table in GUARDED_TABLES:
        found |= {u["name"] for u in inspector.get_unique_constraints(table) if u["name"]}
        found |= {i["name"] for i in inspector.get_indexes(table) if i["unique"]}
    return found


def rows(conn, table: str) -> list[tuple]:
    return sorted(tuple(r) for r in conn.execute(sa.text(f"SELECT * FROM {table}")))


def test_the_revision_chains_after_the_idempotency_records_migration():
    module = load_migration()

    assert module.revision == "e1b8d4a62f37"
    assert module.down_revision == "d7a3c5e91b24"


def test_upgrade_adds_every_guard_and_touches_no_row(connection):
    before = {table: rows(connection, table) for table in GUARDED_TABLES}

    run(connection, "upgrade")

    assert guards(connection) == {
        "uq_budgets_name",
        "uq_budget_allocations_budget_id",
        "uq_pipeline_kill_switch_name",
        "uq_financial_events_one_reserve_per_reference",
        "uq_financial_events_one_settlement_per_reference",
        "uq_pipeline_reviews_one_pending_gate_per_step",
        "uq_pipeline_reviews_one_pending_post_hoc_per_run",
    }
    assert {table: rows(connection, table) for table in GUARDED_TABLES} == before


@pytest.mark.parametrize("what", list(DUPLICATES))
def test_after_upgrading_the_database_refuses_each_duplicate(connection, what):
    run(connection, "upgrade")
    connection.commit()
    # Los datos «malos» no pueden entrar ya: se prueba con la fila legítima y una repetida.
    with pytest.raises(sa.exc.IntegrityError):
        for statement in DUPLICATES[what]:
            connection.execute(sa.text(statement))
    connection.rollback()


@pytest.mark.parametrize("what", list(DUPLICATES))
def test_with_duplicates_already_there_it_refuses_changes_nothing_and_says_which(connection, what):
    for statement in DUPLICATES[what]:
        connection.execute(sa.text(statement))
    connection.commit()
    before = {table: rows(connection, table) for table in GUARDED_TABLES}

    with pytest.raises(RuntimeError, match="never deletes or merges rows") as error:
        run(connection, "upgrade")

    assert what in str(error.value)
    assert guards(connection) == set()  # no se creó ninguna garantía a medias
    assert {table: rows(connection, table) for table in GUARDED_TABLES} == before  # y ninguna fila cambió


def test_downgrade_removes_the_guards_and_the_database_admits_duplicates_again(connection):
    run(connection, "upgrade")

    run(connection, "downgrade")

    assert guards(connection) == set()
    connection.execute(sa.text(DUPLICATES["budgets.name"][0]))  # ya no hay nada que lo impida
    connection.execute(sa.text(DUPLICATES["one RESERVE per reference"][0]))


def test_the_migration_can_be_applied_again_after_a_downgrade(connection):
    run(connection, "upgrade")
    run(connection, "downgrade")

    run(connection, "upgrade")

    assert len(guards(connection)) == 7


def test_the_migration_creates_what_the_models_declare(connection):
    run(connection, "upgrade")
    inspector = sa.inspect(connection)

    for name in GUARDED_TABLES:
        model = Base.metadata.tables[name]
        model_uniques = {c.name for c in model.constraints if isinstance(c, sa.UniqueConstraint)}
        model_indexes = {i.name for i in model.indexes if i.unique}
        migrated_uniques = {u["name"] for u in inspector.get_unique_constraints(name)}
        migrated_indexes = {i["name"] for i in inspector.get_indexes(name) if i["unique"]}
        assert migrated_uniques == model_uniques, name
        assert migrated_indexes == model_indexes, name
