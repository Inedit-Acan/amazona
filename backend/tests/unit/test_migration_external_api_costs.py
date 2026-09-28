"""Ejecuta la migración del libro de costes, en los dos sentidos."""

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.db.models.external_api_cost import ExternalApiCost

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "f3d7a02c9e51_external_api_costs.py"
)


def load_migration():
    spec = importlib.util.spec_from_file_location("m37costs", MIGRATION)
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


def tables(conn) -> set[str]:
    return set(sa.inspect(conn).get_table_names())


def columns(conn, table: str) -> set[str]:
    return {row[1] for row in conn.execute(sa.text(f"PRAGMA table_info({table})")).fetchall()}


def test_upgrade_creates_the_table(connection):
    run(connection, "upgrade")

    assert "external_api_costs" in tables(connection)


def test_the_migration_matches_the_model(connection):
    run(connection, "upgrade")

    expected = {column.name for column in ExternalApiCost.__table__.columns}
    assert expected == columns(connection, "external_api_costs")


def test_the_seven_fields_the_plan_asks_for_are_there(connection):
    """Plan maestro §25, literal."""
    run(connection, "upgrade")

    present = columns(connection, "external_api_costs")
    assert {
        "provider",
        "operation",
        "units",
        "estimated_cost",
        "actual_cost",
        "currency",
        "correlation_id",
    } <= present


def test_it_can_be_asked_what_a_provider_spent_today(connection):
    """El motivo de que esto vaya en filas y no en un contador agregado."""
    run(connection, "upgrade")

    names = {
        row[1] for row in connection.execute(sa.text("PRAGMA index_list(external_api_costs)"))
    }
    assert "ix_external_api_costs_provider_day" in names
    assert "ix_external_api_costs_correlation" in names


def test_a_denial_can_be_stored_with_its_reason(connection):
    run(connection, "upgrade")

    connection.execute(
        sa.text(
            "INSERT INTO external_api_costs (id, provider, operation, units, unit,"
            " estimated_cost, actual_cost, currency, outcome, denied_reason, correlation_id,"
            " observed_at, created_at) VALUES ('c-1', 'de-pago', 'search', 1, 'requests',"
            " 0.05, NULL, 'EUR', 'denied', 'sin límite autorizado', 'cid-1',"
            " '2026-09-28 00:00:00', '2026-09-28 00:00:00')"
        )
    )

    row = connection.execute(
        sa.text("SELECT outcome, denied_reason, actual_cost FROM external_api_costs")
    ).one()
    assert row.outcome == "denied"
    assert row.denied_reason == "sin límite autorizado"
    # Nulo no es cero.
    assert row.actual_cost is None


def test_downgrade_leaves_nothing_behind(connection):
    before = tables(connection)

    run(connection, "upgrade")
    run(connection, "downgrade")

    assert tables(connection) == before


def test_the_migration_follows_the_previous_head():
    module = load_migration()

    assert module.revision == "f3d7a02c9e51"
    assert module.down_revision == "e2c4a91b7d38"
