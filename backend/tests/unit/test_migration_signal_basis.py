"""Ejecuta la migración del Milestone 37 de verdad, en los dos sentidos.

Es la primera migración **destructiva** del proyecto: elimina una columna. Así
que se prueba con filas dentro y se comprueba que ninguna pierde su procedencia
al subir, y que al bajar se reconstruye lo que el esquema viejo sabe expresar.
"""

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.db.models.product_signal import ProductSignal

MIGRATION = (
    Path(__file__).resolve().parents[2] / "alembic" / "versions" / "e2c4a91b7d38_signal_basis.py"
)


def load_migration():
    spec = importlib.util.spec_from_file_location("m37", MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def connection():
    """La tabla tal y como la dejó el Milestone 34: con `simulated`."""
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    with engine.connect() as conn:
        conn.execute(
            sa.text(
                "CREATE TABLE product_signals ("
                " id VARCHAR(36) NOT NULL PRIMARY KEY, product_id VARCHAR(36),"
                " kind VARCHAR(32), value FLOAT, confidence FLOAT, provider VARCHAR(64),"
                " source VARCHAR(255), query VARCHAR(255), market VARCHAR(16),"
                " observed_at DATETIME, method TEXT, raw_reference VARCHAR(500),"
                " simulated BOOLEAN NOT NULL, correlation_id VARCHAR(36), created_at DATETIME)"
            )
        )
        conn.execute(sa.text("CREATE INDEX ix_product_signals_simulated ON product_signals (simulated)"))
        yield conn
    engine.dispose()


def run(conn, direction: str) -> None:
    module = load_migration()
    with Operations.context(MigrationContext.configure(conn)):
        getattr(module, direction)()


def add_signal(conn, signal_id: str, provider: str, simulated: bool) -> None:
    conn.execute(
        sa.text(
            "INSERT INTO product_signals (id, product_id, kind, value, confidence, provider,"
            " source, query, market, observed_at, method, raw_reference, simulated,"
            " correlation_id, created_at) VALUES (:id, 'p-1', 'demand', 0.7, 0.5, :provider,"
            " 'somewhere', 'Air fryer', 'us', '2026-09-01 00:00:00', 'método', NULL,"
            " :simulated, 'cid-1', '2026-09-01 00:00:00')"
        ),
        {"id": signal_id, "provider": provider, "simulated": simulated},
    )


def columns(conn) -> set[str]:
    return {row[1] for row in conn.execute(sa.text("PRAGMA table_info(product_signals)")).fetchall()}


def indexes(conn) -> set[str]:
    return {row[1] for row in conn.execute(sa.text("PRAGMA index_list(product_signals)"))}


def test_upgrade_swaps_the_column(connection):
    run(connection, "upgrade")

    assert "basis" in columns(connection)
    assert "simulated" not in columns(connection)


def test_the_migration_matches_the_model(connection):
    run(connection, "upgrade")

    assert {c.name for c in ProductSignal.__table__.columns} == columns(connection)


def test_nothing_loses_its_provenance_going_up(connection):
    add_signal(connection, "s-real", "wikimedia-pageviews", simulated=False)
    add_signal(connection, "s-fixture", "fixtures", simulated=True)

    run(connection, "upgrade")

    rows = dict(connection.execute(sa.text("SELECT id, basis FROM product_signals")).all())
    assert rows["s-real"] == "measured"
    assert rows["s-fixture"] == "simulated"


def test_no_existing_row_is_relabelled_as_an_estimate(connection):
    """Marcar como estimación algo que nadie modeló sería inventar procedencia."""
    add_signal(connection, "s-real", "wikimedia-pageviews", simulated=False)
    add_signal(connection, "s-fixture", "fixtures", simulated=True)

    run(connection, "upgrade")

    bases = {row[0] for row in connection.execute(sa.text("SELECT DISTINCT basis FROM product_signals"))}
    assert "estimated" not in bases


def test_the_index_follows_the_column(connection):
    run(connection, "upgrade")

    names = indexes(connection)
    assert "ix_product_signals_basis" in names
    assert "ix_product_signals_simulated" not in names


def test_downgrade_rebuilds_what_the_old_schema_can_express(connection):
    add_signal(connection, "s-real", "wikimedia-pageviews", simulated=False)
    add_signal(connection, "s-fixture", "fixtures", simulated=True)
    before = columns(connection)

    run(connection, "upgrade")
    connection.execute(sa.text("UPDATE product_signals SET basis = 'estimated' WHERE id = 's-real'"))
    run(connection, "downgrade")

    assert columns(connection) == before
    rows = dict(connection.execute(sa.text("SELECT id, simulated FROM product_signals")).all())
    # Una estimación no es un fixture, así que al bajar queda como «no simulada».
    # Que la distinción se pierda es el motivo del milestone, no un fallo de esta
    # migración: en el esquema viejo no cabe.
    assert not rows["s-real"]
    assert rows["s-fixture"]


def test_no_row_is_lost_in_either_direction(connection):
    add_signal(connection, "s-1", "wikimedia-pageviews", simulated=False)
    add_signal(connection, "s-2", "fixtures", simulated=True)

    run(connection, "upgrade")
    run(connection, "downgrade")

    assert connection.execute(sa.text("SELECT COUNT(*) FROM product_signals")).scalar() == 2


def test_the_migration_follows_the_previous_head():
    module = load_migration()

    assert module.revision == "e2c4a91b7d38"
    assert module.down_revision == "d1e8b4a7c206"
