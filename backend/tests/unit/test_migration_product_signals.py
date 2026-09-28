"""Ejecuta la migración del Milestone 34 de verdad, en los dos sentidos.

Una tabla nueva, ninguna existente tocada: lo que hay que comprobar es que las
columnas son las del modelo —el desajuste clásico— y que los índices por los que
se va a preguntar existen, porque «¿qué señales son reales?» se va a consultar a
menudo.
"""

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.db.models.product_signal import ProductSignal

MIGRATION = (
    Path(__file__).resolve().parents[2] / "alembic" / "versions" / "c93af2e5107b_product_signals.py"
)


def load_migration():
    spec = importlib.util.spec_from_file_location("m34", MIGRATION)
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
                "CREATE TABLE products (id VARCHAR(36) NOT NULL PRIMARY KEY, name VARCHAR(255),"
                " category VARCHAR(64))"
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


def test_upgrade_creates_the_table(connection):
    run(connection, "upgrade")

    assert "product_signals" in tables(connection)


#: Las columnas que **esta** migración crea. Se escriben aquí en vez de leerse
#: del modelo vivo porque el modelo ha seguido cambiando: el Milestone 37
#: sustituyó `simulated` por `basis` en su propia migración. Comparar una
#: migración antigua contra el modelo de hoy solo funciona hasta que alguien toca
#: la tabla, y entonces falla por el motivo equivocado.
M34_COLUMNS = {
    "id",
    "product_id",
    "kind",
    "value",
    "confidence",
    "provider",
    "source",
    "query",
    "market",
    "observed_at",
    "method",
    "raw_reference",
    "simulated",
    "correlation_id",
    "created_at",
}


def test_the_migration_creates_the_columns_of_its_own_milestone(connection):
    run(connection, "upgrade")

    assert M34_COLUMNS == columns(connection, "product_signals")


def test_the_live_model_has_moved_on_from_this_migration(connection):
    """Deja constancia de en qué se diferencia hoy, para que la diferencia sea
    una decisión escrita y no una sorpresa."""
    live = {column.name for column in ProductSignal.__table__.columns}

    assert live - M34_COLUMNS == {"basis"}
    assert M34_COLUMNS - live == {"simulated"}


def test_the_indexes_the_questions_need_exist(connection):
    """«¿Qué señales son reales?», «¿qué se midió de este producto?» y «¿qué
    salió de esta ejecución?»."""
    run(connection, "upgrade")

    indexes = {row[1] for row in connection.execute(sa.text("PRAGMA index_list(product_signals)"))}
    assert {
        "ix_product_signals_simulated",
        "ix_product_signals_product_kind",
        "ix_product_signals_correlation",
        "ix_product_signals_provider",
    } <= indexes


def test_a_signal_survives_a_round_trip_with_all_its_provenance(connection):
    run(connection, "upgrade")
    connection.execute(
        sa.text(
            "INSERT INTO product_signals (id, product_id, kind, value, confidence, provider, source,"
            " query, market, observed_at, method, raw_reference, simulated, correlation_id, created_at)"
            " VALUES ('sig-1', 'prod-1', 'demand', 0.62, 0.55, 'wikimedia-pageviews',"
            " 'wikimedia.org/api/rest_v1/metrics/pageviews', 'Air fryer', 'us', '2026-09-01 00:00:00',"
            " 'monthly pageviews — PROXY FOR INTEREST, not purchase demand', 'https://example/raw',"
            " 0, 'cid-1', '2026-09-26 00:00:00')"
        )
    )

    row = connection.execute(
        sa.text("SELECT provider, query, method, simulated FROM product_signals WHERE id = 'sig-1'")
    ).one()

    assert row.provider == "wikimedia-pageviews"
    assert row.query == "Air fryer"
    assert "PROXY FOR INTEREST" in row.method
    assert row.simulated == 0


def test_the_method_is_long_text_because_it_has_to_explain_itself(connection):
    """El `method` es donde se dice qué es y qué no es el número; un VARCHAR
    corto obligaría a resumirlo hasta perder el matiz."""
    run(connection, "upgrade")
    long_method = "x" * 2000

    connection.execute(
        sa.text(
            "INSERT INTO product_signals (id, product_id, kind, value, confidence, provider, source,"
            " query, market, observed_at, method, simulated, correlation_id, created_at)"
            " VALUES ('sig-2', 'prod-1', 'demand', 0.1, 0.1, 'p', 's', 'q', 'us',"
            " '2026-09-01 00:00:00', :method, 0, 'cid-1', '2026-09-26 00:00:00')"
        ),
        {"method": long_method},
    )

    stored = connection.execute(sa.text("SELECT method FROM product_signals WHERE id = 'sig-2'")).scalar()
    assert stored == long_method


def test_downgrade_leaves_nothing_behind(connection):
    before = tables(connection)

    run(connection, "upgrade")
    run(connection, "downgrade")

    assert tables(connection) == before


def test_the_migration_follows_the_previous_head():
    module = load_migration()

    assert module.revision == "c93af2e5107b"
    assert module.down_revision == "b7e3d5c81f24"
