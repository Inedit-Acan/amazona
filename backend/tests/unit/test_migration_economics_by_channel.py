"""Ejecuta la migración del Milestone 40 de verdad, en los dos sentidos y con
datos dentro.

El esquema de partida está escrito a mano y **congelado**: es el que dejó el
Milestone 39. Un test de migración que compara contra los modelos vivos caduca
en cuanto otro milestone toca la tabla, y ya ha pasado dos veces aquí.
"""

import importlib.util
from decimal import Decimal
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "d8b4c1e70a29_economics_by_channel_and_currency.py"
)


def load_migration():
    spec = importlib.util.spec_from_file_location("m40", MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


#: `economic_analyses` tal y como estaba al cerrar el Milestone 39.
SCHEMA_BEFORE_M40 = (
    "CREATE TABLE economic_analyses ("
    " id VARCHAR(36) NOT NULL PRIMARY KEY, product_id VARCHAR(36),"
    " supplier_quote_id VARCHAR(36), analysis_type VARCHAR(32) DEFAULT 'economic_risk',"
    " sale_price FLOAT NOT NULL, monthly_fixed_costs FLOAT NOT NULL,"
    " margin_percent FLOAT NOT NULL, recommendation VARCHAR(16) NOT NULL,"
    " confidence FLOAT NOT NULL, data JSON, correlation_id VARCHAR(36),"
    " created_at DATETIME, updated_at DATETIME)",
)


@pytest.fixture()
def connection():
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    with engine.connect() as conn:
        for statement in SCHEMA_BEFORE_M40:
            conn.execute(sa.text(statement))
        yield conn
    engine.dispose()


def run(conn, direction: str) -> None:
    module = load_migration()
    with Operations.context(MigrationContext.configure(conn)):
        getattr(module, direction)()


def add_analysis(conn, analysis_id: str, margin: float = 0.7) -> None:
    conn.execute(
        sa.text(
            "INSERT INTO economic_analyses (id, product_id, supplier_quote_id, sale_price,"
            " monthly_fixed_costs, margin_percent, recommendation, confidence, correlation_id)"
            " VALUES (:id, 'p-1', 'q-1', 20.0, 500.0, :margin, 'GO', 0.85, 'corr-1')"
        ),
        {"id": analysis_id, "margin": margin},
    )


def columns(conn, table) -> set[str]:
    return {row[1] for row in conn.execute(sa.text(f"PRAGMA table_info({table})")).fetchall()}


def one(conn, sql, **params):
    return conn.execute(sa.text(sql), params).fetchone()


# --- Subida ------------------------------------------------------------------


def test_upgrade_creates_the_exchange_rate_table(connection):
    run(connection, "upgrade")

    assert {
        "base_currency",
        "quote_currency",
        "rate",
        "effective_date",
        "source",
        "provenance",
        "declared_by",
        "note",
    } <= columns(connection, "exchange_rates")


def test_a_rate_keeps_its_precision_on_the_way_back(connection):
    """`Numeric(18, 8)`: una tasa necesita más decimales que un importe, y es la
    cifra por la que se multiplica todo lo demás."""
    run(connection, "upgrade")
    connection.execute(
        sa.text(
            "INSERT INTO exchange_rates (id, base_currency, quote_currency, rate,"
            " effective_date, source, provenance)"
            " VALUES ('r-1', 'VND', 'EUR', 0.00003500, '2026-09-01', 'manual:owner', 'declared')"
        )
    )

    stored = one(connection, "SELECT rate FROM exchange_rates WHERE id = 'r-1'")[0]
    assert Decimal(str(stored)) == Decimal("0.000035")


def test_upgrade_adds_the_channel_currency_and_evaluability_columns(connection):
    run(connection, "upgrade")

    assert {
        "channel",
        "currency",
        "units_per_order",
        "units_per_order_provenance",
        "margin_evaluability",
        "cac_evaluability",
        "missing_inputs",
        "contribution_margin_per_unit",
        "contribution_margin_per_order",
        "allocated_fixed_cost_per_order",
        "max_breakeven_cac",
        "fx_conversions",
    } <= columns(connection, "economic_analyses")


def test_existing_rows_are_declared_evaluable(connection):
    """Lo eran con lo que se sabía entonces. Decir lo contrario sería reescribir
    el pasado."""
    add_analysis(connection, "a-1")

    run(connection, "upgrade")

    assert one(
        connection,
        "SELECT margin_evaluability, cac_evaluability FROM economic_analyses WHERE id = 'a-1'",
    ) == ("evaluable", "evaluable")


def test_channel_currency_and_units_are_not_filled_in(connection):
    """Las filas anteriores se calcularon sin saber dónde se vendía ni en qué
    moneda estaba el coste —de hecho, mezclándolas—. Ponerles ahora `own_web` y
    `EUR` sería afirmar dos cosas que nadie afirmó, y un 1 en las unidades por
    pedido sería justo la suposición que este milestone quita."""
    add_analysis(connection, "a-1")

    run(connection, "upgrade")

    assert one(
        connection,
        "SELECT channel, currency, units_per_order FROM economic_analyses WHERE id = 'a-1'",
    ) == (None, None, None)


def test_a_margin_can_now_be_absent(connection):
    run(connection, "upgrade")

    connection.execute(
        sa.text(
            "INSERT INTO economic_analyses (id, product_id, supplier_quote_id, sale_price,"
            " monthly_fixed_costs, recommendation, confidence, correlation_id,"
            " margin_evaluability, cac_evaluability)"
            " VALUES ('a-blank', 'p-1', 'q-1', 20.0, 500.0, 'REVIEW', 0.3, 'c',"
            " 'not_evaluable', 'not_evaluable')"
        )
    )

    assert one(
        connection, "SELECT margin_percent FROM economic_analyses WHERE id = 'a-blank'"
    )[0] is None


# --- Bajada ------------------------------------------------------------------


def test_downgrade_restores_the_previous_shape(connection):
    add_analysis(connection, "a-1")

    run(connection, "upgrade")
    run(connection, "downgrade")

    assert "channel" not in columns(connection, "economic_analyses")
    assert "currency" not in columns(connection, "economic_analyses")
    assert connection.execute(
        sa.text("SELECT COUNT(*) FROM sqlite_master WHERE name = 'exchange_rates'")
    ).scalar() == 0


def test_downgrading_keeps_the_rows_and_their_numbers(connection):
    add_analysis(connection, "a-1", margin=0.6975)

    run(connection, "upgrade")
    run(connection, "downgrade")

    assert one(
        connection,
        "SELECT sale_price, monthly_fixed_costs, margin_percent FROM economic_analyses"
        " WHERE id = 'a-1'",
    ) == (20.0, 500.0, 0.6975)


def test_downgrading_turns_not_evaluated_into_zero_margin(connection):
    """Bajar cuesta información, y conviene decirlo: el esquema anterior no sabe
    representar «no se pudo evaluar», así que un análisis sin evaluar pasa a
    parecer un producto con margen cero."""
    run(connection, "upgrade")
    connection.execute(
        sa.text(
            "INSERT INTO economic_analyses (id, product_id, supplier_quote_id, sale_price,"
            " monthly_fixed_costs, recommendation, confidence, correlation_id,"
            " margin_evaluability, cac_evaluability)"
            " VALUES ('a-blank', 'p-1', 'q-1', 20.0, 500.0, 'REVIEW', 0.3, 'c',"
            " 'not_evaluable', 'not_evaluable')"
        )
    )

    run(connection, "downgrade")

    assert one(
        connection, "SELECT margin_percent FROM economic_analyses WHERE id = 'a-blank'"
    )[0] == 0.0
