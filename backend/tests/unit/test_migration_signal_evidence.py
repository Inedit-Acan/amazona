"""Ejecuta la migración del Milestone 35 de verdad, en los dos sentidos."""

import importlib.util
import json
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.db.models.product_signal_observation import ProductSignalObservation
from app.db.models.research_comparison import ResearchComparison

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "a5f1c62d87e4_signal_evidence_and_comparisons.py"
)


def load_migration():
    spec = importlib.util.spec_from_file_location("m35", MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def connection():
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    with engine.connect() as conn:
        conn.execute(
            sa.text(
                "CREATE TABLE product_signals (id VARCHAR(36) NOT NULL PRIMARY KEY,"
                " product_id VARCHAR(36), kind VARCHAR(32))"
            )
        )
        yield conn
    engine.dispose()


def run(conn, direction: str) -> None:
    module = load_migration()
    with Operations.context(MigrationContext.configure(conn)):
        getattr(module, direction)()


def tables(conn) -> set[str]:
    return set(sa.inspect(conn).get_table_names())


def columns(conn, table: str) -> set[str]:
    return {row[1] for row in conn.execute(sa.text(f"PRAGMA table_info({table})")).fetchall()}


def test_upgrade_creates_both_tables(connection):
    run(connection, "upgrade")

    assert {"product_signal_observations", "research_comparisons"} <= tables(connection)


@pytest.mark.parametrize("model", [ProductSignalObservation, ResearchComparison])
def test_the_migration_matches_the_model(connection, model):
    run(connection, "upgrade")

    expected = {column.name for column in model.__table__.columns}
    assert expected == columns(connection, model.__tablename__)


def test_the_evidence_is_queryable_by_signal_and_period(connection):
    """En filas y no en un blob justamente para poder preguntar esto."""
    run(connection, "upgrade")

    indexes = {
        row[1] for row in connection.execute(sa.text("PRAGMA index_list(product_signal_observations)"))
    }
    assert "ix_signal_observations_signal_period" in indexes


def test_an_observation_keeps_the_raw_value_of_the_source(connection):
    run(connection, "upgrade")
    connection.execute(
        sa.text(
            "INSERT INTO product_signal_observations (id, signal_id, period, value, created_at)"
            " VALUES ('obs-1', 'sig-1', '2026-08', 45000.0, '2026-09-27 00:00:00')"
        )
    )

    row = connection.execute(
        sa.text("SELECT period, value FROM product_signal_observations WHERE id = 'obs-1'")
    ).one()

    assert row.period == "2026-08"
    assert row.value == 45000.0


def test_a_comparison_stores_its_whole_report(connection):
    run(connection, "upgrade")
    summary = {"verdict": "Ningún candidato en común", "baseline": {"candidates": 4}}

    connection.execute(
        sa.text(
            "INSERT INTO research_comparisons (id, category, market, baseline_provider,"
            " candidate_provider, summary, correlation_id, created_at)"
            " VALUES ('cmp-1', 'home', 'us', 'fixtures', 'wikimedia-pageviews', :summary,"
            " 'cid-1', '2026-09-27 00:00:00')"
        ).bindparams(sa.bindparam("summary", value=summary, type_=sa.JSON())),
    )

    stored = connection.execute(
        sa.text("SELECT summary FROM research_comparisons WHERE id = 'cmp-1'")
    ).scalar()
    parsed = json.loads(stored) if isinstance(stored, str) else stored
    assert parsed["verdict"] == "Ningún candidato en común"


def test_downgrade_leaves_nothing_behind(connection):
    before = tables(connection)

    run(connection, "upgrade")
    run(connection, "downgrade")

    assert tables(connection) == before


def test_the_migration_follows_the_previous_head():
    module = load_migration()

    assert module.revision == "a5f1c62d87e4"
    assert module.down_revision == "c93af2e5107b"
