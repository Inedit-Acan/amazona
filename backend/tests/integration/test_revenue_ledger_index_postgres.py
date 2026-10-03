"""El índice de las lecturas del registro sobre un PostgreSQL de verdad (Milestone 45, ADR 0030).

Lo que solo PostgreSQL demuestra: que la migración crea el índice con su `INCLUDE`, que lo quita y lo vuelve a
poner, y que el planificador **puede usarlo** para las dos consultas que lo justifican: la página por cursor con
comparación de filas (`(occurred_at, id) < (…)`, orden descendente) y el resumen de un periodo. Se fuerza
`enable_seqscan = off` porque, con unas pocas filas, el planificador elegiría un barrido aunque el índice sirva; lo
que se comprueba es que **sirve**.
"""

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from pg_test_support import ephemeral_postgres
from sqlalchemy import text

VERSIONS = Path(__file__).resolve().parents[2] / "alembic" / "versions"
FILE = "e5a1d7c93b04_revenue_ledger_occurred_at_index.py"
INDEX = "ix_revenue_entries_occurred_at"

PAGE = (
    "SELECT * FROM revenue_ledger_entries WHERE (occurred_at, id) < (now() - interval '1 day', 'x') "
    "ORDER BY occurred_at DESC, id DESC LIMIT 101"
)
FIRST_PAGE = "SELECT * FROM revenue_ledger_entries ORDER BY occurred_at DESC, id DESC LIMIT 101"
SUMMARY = (
    "SELECT currency, classification, kind, count(*), sum(amount) FROM revenue_ledger_entries "
    "WHERE occurred_at >= now() - interval '30 days' AND occurred_at < now() GROUP BY 1, 2, 3"
)


def migration():
    spec = importlib.util.spec_from_file_location("revenue_index_migration", VERSIONS / FILE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(engine, direction: str) -> None:
    with engine.connect() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            getattr(migration(), direction)()
        conn.commit()


def definition(engine) -> str | None:
    with engine.connect() as conn:
        return conn.execute(text(f"SELECT indexdef FROM pg_indexes WHERE indexname = '{INDEX}'")).scalar()


def plan(engine, sql: str) -> str:
    with engine.connect() as conn:
        conn.execute(text("SET enable_seqscan = off"))
        return "\n".join(row[0] for row in conn.execute(text("EXPLAIN " + sql)))


@pytest.fixture()
def engine():
    """La base del modelo, **sin** el índice: lo que habría antes de esta migración."""
    with ephemeral_postgres() as built:
        with built.connect() as conn:
            assert conn.execute(text(f"SELECT count(*) FROM pg_indexes WHERE indexname = '{INDEX}'")).scalar() == 1
            conn.execute(text(f"DROP INDEX {INDEX}"))
            conn.commit()
        yield built


def test_upgrade_creates_the_index_with_the_columns_the_aggregates_sum(engine):
    assert definition(engine) is None

    run(engine, "upgrade")

    created = definition(engine)
    assert created is not None and "(occurred_at, id)" in created
    assert "INCLUDE (currency, classification, kind, amount)" in created


def test_the_model_creates_the_same_index_as_the_migration(engine):
    run(engine, "upgrade")
    migrated = definition(engine)
    with engine.connect() as conn:
        conn.execute(text(f"DROP INDEX {INDEX}"))
        from sqlalchemy.schema import CreateIndex

        from app.db.models.revenue import RevenueLedgerEntry

        model_index = next(i for i in RevenueLedgerEntry.__table__.indexes if i.name == INDEX)
        conn.execute(CreateIndex(model_index))
        conn.commit()

    assert definition(engine) == migrated


def test_the_planner_can_use_it_for_the_cursor_page_and_for_the_period_summary(engine):
    run(engine, "upgrade")

    assert INDEX in plan(engine, FIRST_PAGE)
    assert INDEX in plan(engine, PAGE), "the row comparison is resolved by one scan of the index"
    assert INDEX in plan(engine, SUMMARY)


def test_without_the_index_the_same_queries_cannot_avoid_a_sequential_scan(engine):
    assert INDEX not in plan(engine, PAGE)


def test_downgrade_removes_the_index_and_it_can_be_applied_again(engine):
    run(engine, "upgrade")

    run(engine, "downgrade")
    assert definition(engine) is None
    run(engine, "upgrade")

    assert definition(engine) is not None
