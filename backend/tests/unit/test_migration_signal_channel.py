"""Ejecuta la migración del canal de verdad, en los dos sentidos y con datos.

Lo que se comprueba además de subir y bajar: que **no se rellena** nada. Las filas
existentes se quedan en `NULL`, que significa agnóstica del canal — atribuirles un
canal sería afirmar que se midió allí.
"""

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.db.models.product_signal import ProductSignal

MIGRATION = (
    Path(__file__).resolve().parents[2] / "alembic" / "versions" / "a4b8e1f60c37_signal_channel.py"
)


def load_migration():
    spec = importlib.util.spec_from_file_location("m38", MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def connection():
    """La tabla tal y como la dejó el Milestone 37: con `basis` y sin `channel`."""
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    with engine.connect() as conn:
        conn.execute(
            sa.text(
                "CREATE TABLE product_signals ("
                " id VARCHAR(36) NOT NULL PRIMARY KEY, product_id VARCHAR(36),"
                " kind VARCHAR(32), value FLOAT, confidence FLOAT, provider VARCHAR(64),"
                " source VARCHAR(255), query VARCHAR(255), market VARCHAR(16),"
                " observed_at DATETIME, method TEXT, raw_reference VARCHAR(500),"
                " basis VARCHAR(16) NOT NULL DEFAULT 'measured', correlation_id VARCHAR(36),"
                " created_at DATETIME)"
            )
        )
        yield conn
    engine.dispose()


def run(conn, direction: str) -> None:
    module = load_migration()
    with Operations.context(MigrationContext.configure(conn)):
        getattr(module, direction)()


def add_signal(conn, signal_id: str, kind: str, provider: str, basis: str) -> None:
    conn.execute(
        sa.text(
            "INSERT INTO product_signals (id, product_id, kind, value, confidence, provider,"
            " source, query, market, observed_at, method, raw_reference, basis,"
            " correlation_id, created_at) VALUES (:id, 'p-1', :kind, 0.7, 0.5, :provider,"
            " 'somewhere', 'Air fryer', 'us', '2026-09-01 00:00:00', 'método', NULL, :basis,"
            " 'cid-1', '2026-09-01 00:00:00')"
        ),
        {"id": signal_id, "kind": kind, "provider": provider, "basis": basis},
    )


def columns(conn) -> set[str]:
    return {row[1] for row in conn.execute(sa.text("PRAGMA table_info(product_signals)"))}


def test_upgrade_adds_the_column(connection):
    run(connection, "upgrade")

    assert "channel" in columns(connection)


def test_the_migration_matches_the_model(connection):
    run(connection, "upgrade")

    assert {c.name for c in ProductSignal.__table__.columns} == columns(connection)


def test_existing_rows_are_left_agnostic_not_assigned_a_channel(connection):
    """Las señales guardadas hoy vienen de Wikimedia —interés, que no depende del
    canal— y de fixtures, que no miden en ningún sitio. Atribuirles un canal sería
    afirmar que se midió allí."""
    add_signal(connection, "s-interes", "demand", "wikimedia-pageviews", "measured")
    add_signal(connection, "s-fixture", "competition", "fixtures", "simulated")

    run(connection, "upgrade")

    channels = dict(connection.execute(sa.text("SELECT id, channel FROM product_signals")).all())
    assert channels == {"s-interes": None, "s-fixture": None}


def test_there_is_no_default_channel(connection):
    """Un `own_web` por defecto convertiría cada señal antigua en una afirmación
    sobre el canal prioritario."""
    run(connection, "upgrade")
    add_signal(connection, "s-nueva", "demand", "wikimedia-pageviews", "measured")

    channel = connection.execute(
        sa.text("SELECT channel FROM product_signals WHERE id = 's-nueva'")
    ).scalar()
    assert channel is None


def test_the_channel_can_be_asked_for(connection):
    run(connection, "upgrade")

    names = {row[1] for row in connection.execute(sa.text("PRAGMA index_list(product_signals)"))}
    assert "ix_product_signals_channel" in names


def test_a_channel_round_trips(connection):
    run(connection, "upgrade")
    add_signal(connection, "s-ebay", "competition", "ebay-browse", "measured")
    connection.execute(
        sa.text("UPDATE product_signals SET channel = 'marketplace:ebay' WHERE id = 's-ebay'")
    )

    channel = connection.execute(
        sa.text("SELECT channel FROM product_signals WHERE id = 's-ebay'")
    ).scalar()
    assert channel == "marketplace:ebay"


def test_downgrade_leaves_the_table_as_it_was(connection):
    add_signal(connection, "s-1", "demand", "wikimedia-pageviews", "measured")
    before = columns(connection)

    run(connection, "upgrade")
    run(connection, "downgrade")

    assert columns(connection) == before
    assert connection.execute(sa.text("SELECT COUNT(*) FROM product_signals")).scalar() == 1


def test_the_migration_follows_the_previous_head():
    module = load_migration()

    assert module.revision == "a4b8e1f60c37"
    assert module.down_revision == "f3d7a02c9e51"
