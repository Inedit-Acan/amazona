"""Ejecuta la migración del Milestone 39 de verdad, en los dos sentidos y con
datos dentro.

El esquema de partida está escrito a mano y **congelado**: es el que dejó el
Milestone 38, no el de los modelos vivos. Un test de migración que compara
contra el modelo de hoy caduca en cuanto otro milestone toca la tabla, y ya ha
pasado dos veces en este repositorio.

Lo que más importa de lo que se comprueba aquí no es que las columnas aparezcan,
sino **qué se rellena y qué no**: la procedencia de lo existente, el cero que se
convierte en nulo, y la moneda y el destino que se quedan en blanco porque nadie
los dijo nunca.
"""

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.core.text import fold

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "c7d2f4a90b13_supplier_intelligence.py"
)


def load_migration():
    spec = importlib.util.spec_from_file_location("m39", MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


#: `suppliers` y `supplier_quotes` tal y como estaban al cerrar el Milestone 38.
#: Congelado a propósito: ver la nota del módulo.
SCHEMA_BEFORE_M39 = (
    "CREATE TABLE products (id VARCHAR(36) NOT NULL PRIMARY KEY, name VARCHAR(255))",
    "CREATE TABLE suppliers ("
    " id VARCHAR(36) NOT NULL PRIMARY KEY, name VARCHAR(255),"
    " verified BOOLEAN NOT NULL DEFAULT 0, region VARCHAR(100), contact_info JSON,"
    " reliability_score FLOAT NOT NULL DEFAULT 0,"
    " created_at DATETIME, updated_at DATETIME)",
    "CREATE TABLE supplier_quotes ("
    " id VARCHAR(36) NOT NULL PRIMARY KEY, product_id VARCHAR(36), supplier_id VARCHAR(36),"
    " analysis_type VARCHAR(32) DEFAULT 'sourcing', unit_price FLOAT NOT NULL,"
    " moq INTEGER NOT NULL, lead_time_days INTEGER NOT NULL,"
    " verified BOOLEAN NOT NULL DEFAULT 0, reliability_score FLOAT NOT NULL DEFAULT 0,"
    " logistics_cost_per_unit FLOAT NOT NULL, total_landed_cost_per_unit FLOAT NOT NULL,"
    " data JSON, correlation_id VARCHAR(36), created_at DATETIME, updated_at DATETIME)",
)


@pytest.fixture()
def connection():
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    with engine.connect() as conn:
        for statement in SCHEMA_BEFORE_M39:
            conn.execute(sa.text(statement))
        conn.execute(sa.text("INSERT INTO products (id, name) VALUES ('p-1', 'Earbuds')"))
        yield conn
    engine.dispose()


def run(conn, direction: str) -> None:
    module = load_migration()
    with Operations.context(MigrationContext.configure(conn)):
        getattr(module, direction)()


def add_supplier(conn, supplier_id, name, region, verified, reliability):
    conn.execute(
        sa.text(
            "INSERT INTO suppliers (id, name, verified, region, reliability_score)"
            " VALUES (:id, :name, :verified, :region, :reliability)"
        ),
        {
            "id": supplier_id,
            "name": name,
            "verified": verified,
            "region": region,
            "reliability": reliability,
        },
    )


def add_quote(conn, quote_id, supplier_id, verified=1, price=4.2, logistics=1.2):
    conn.execute(
        sa.text(
            "INSERT INTO supplier_quotes (id, product_id, supplier_id, unit_price, moq,"
            " lead_time_days, verified, reliability_score, logistics_cost_per_unit,"
            " total_landed_cost_per_unit, correlation_id)"
            " VALUES (:id, 'p-1', :supplier_id, :price, 500, 25, :verified, 0.88,"
            " :logistics, :landed, 'corr-1')"
        ),
        {
            "id": quote_id,
            "supplier_id": supplier_id,
            "price": price,
            "verified": verified,
            "logistics": logistics,
            "landed": price + logistics,
        },
    )


def columns(conn, table) -> set[str]:
    return {row[1] for row in conn.execute(sa.text(f"PRAGMA table_info({table})")).fetchall()}


def one(conn, sql, **params):
    return conn.execute(sa.text(sql), params).fetchone()


# --- Subida ------------------------------------------------------------------


def test_upgrade_adds_the_commercial_terms_a_quote_was_missing(connection):
    run(connection, "upgrade")

    assert {
        "currency",
        "quoted_unit",
        "quoted_quantity",
        "transit_days",
        "transport_mode",
        "incoterm",
        "payment_terms",
        "destination_market",
        "valid_from",
        "valid_until",
        "provenance",
        "source",
        "logistics_provenance",
    } <= columns(connection, "supplier_quotes")


def test_upgrade_removes_both_booleans(connection):
    run(connection, "upgrade")

    assert "verified" not in columns(connection, "suppliers")
    assert "verified" not in columns(connection, "supplier_quotes")
    # La fiabilidad es un hecho sobre la empresa, no sobre una tarifa.
    assert "reliability_score" not in columns(connection, "supplier_quotes")


def test_everything_that_existed_is_declared_a_fixture_whatever_the_boolean_said(connection):
    """Todas las filas existentes salen de `MockSupplierDirectory`, que es el
    único proveedor que el dominio SUPPLIERS ha tenido nunca. El `verified` que
    algunas traían era una propiedad del fixture, no una verificación."""
    add_supplier(connection, "s-1", "Shenzhen Volta Electronics", "china", 1, 0.88)
    add_supplier(connection, "s-2", "Guadalajara ElectroPack", "mexico", 0, 0.55)
    add_quote(connection, "q-1", "s-1", verified=1)
    add_quote(connection, "q-2", "s-2", verified=0)

    run(connection, "upgrade")

    for supplier_id in ("s-1", "s-2"):
        assert one(
            connection, "SELECT verification FROM suppliers WHERE id = :id", id=supplier_id
        )[0] == "simulated"
    for quote_id in ("q-1", "q-2"):
        row = one(
            connection,
            "SELECT provenance, source FROM supplier_quotes WHERE id = :id",
            id=quote_id,
        )
        assert row[0] == "simulated"
        assert row[1] == "fixtures:mock-supplier-directory"


def test_a_reliability_of_zero_becomes_unknown(connection):
    """Ningún valor del fixture es cero: un cero solo puede venir del
    `default=0.0`, que es la ausencia disfrazada de dato."""
    add_supplier(connection, "s-1", "Real Rated", "china", 1, 0.88)
    add_supplier(connection, "s-2", "Never Rated", "eu", 0, 0.0)

    run(connection, "upgrade")

    rated = one(
        connection,
        "SELECT reliability_score, reliability_provenance FROM suppliers WHERE id = 's-1'",
    )
    unrated = one(
        connection,
        "SELECT reliability_score, reliability_provenance FROM suppliers WHERE id = 's-2'",
    )
    assert rated == (0.88, "simulated")
    assert unrated == (None, None)


def test_the_logistics_estimate_is_attributed_to_us_not_to_the_supplier(connection):
    add_supplier(connection, "s-1", "Shenzhen Volta Electronics", "china", 1, 0.88)
    add_quote(connection, "q-1", "s-1")

    run(connection, "upgrade")

    assert one(
        connection, "SELECT logistics_provenance FROM supplier_quotes WHERE id = 'q-1'"
    )[0] == "amazona_estimate"


def test_currency_and_destination_are_not_filled_in(connection):
    """Nadie dijo nunca en qué moneda estaban esos precios ni hasta dónde
    llegaba ese coste: inventarlo ahora sería atribuir una convención a una
    fila de hace meses."""
    add_supplier(connection, "s-1", "Shenzhen Volta Electronics", "china", 1, 0.88)
    add_quote(connection, "q-1", "s-1")

    run(connection, "upgrade")

    assert one(
        connection,
        "SELECT currency, destination_market FROM supplier_quotes WHERE id = 'q-1'",
    ) == (None, None)


def test_existing_suppliers_get_an_identity_so_they_are_not_duplicated(connection):
    """Sin este relleno, el primer sourcing posterior crearía un duplicado de
    cada proveedor existente."""
    add_supplier(connection, "s-1", "Shenzhen Volta Electronics", "china", 1, 0.88)

    run(connection, "upgrade")

    key, method = one(
        connection, "SELECT identity_key, identity_method FROM suppliers WHERE id = 's-1'"
    )
    assert key == f"{fold('Shenzhen Volta Electronics')}|region:china"
    assert method == "normalised"


def test_the_frozen_fold_in_the_migration_matches_the_one_the_app_uses_today(connection):
    """El día que dejen de coincidir habrá que decidirlo a mano, no
    descubrirlo con un duplicado en producción."""
    module = load_migration()

    for name in ("Shenzhen Volta Electronics", "Fábrica Real S.L.", "Porto Leather & Co", "???"):
        assert module.fold(name) == fold(name), name


def test_upgrade_creates_the_capability_table(connection):
    run(connection, "upgrade")

    assert {
        "supplier_id",
        "product_id",
        "capability",
        "supported",
        "provenance",
        "source",
        "note",
        "observed_at",
    } <= columns(connection, "supplier_capabilities")


def test_a_quote_can_now_leave_its_numbers_unsaid(connection):
    run(connection, "upgrade")

    connection.execute(
        sa.text(
            "INSERT INTO supplier_quotes (id, product_id, supplier_id, provenance, correlation_id)"
            " VALUES ('q-empty', 'p-1', 's-1', 'supplier_claim', 'corr-2')"
        )
    )

    assert one(
        connection,
        "SELECT unit_price, moq, total_landed_cost_per_unit FROM supplier_quotes"
        " WHERE id = 'q-empty'",
    ) == (None, None, None)


# --- Bajada ------------------------------------------------------------------


def test_downgrade_restores_the_previous_shape(connection):
    add_supplier(connection, "s-1", "Shenzhen Volta Electronics", "china", 1, 0.88)
    add_quote(connection, "q-1", "s-1")

    run(connection, "upgrade")
    run(connection, "downgrade")

    assert "verified" in columns(connection, "suppliers")
    assert "verified" in columns(connection, "supplier_quotes")
    assert "reliability_score" in columns(connection, "supplier_quotes")
    assert "currency" not in columns(connection, "supplier_quotes")
    assert "identity_key" not in columns(connection, "suppliers")
    assert connection.execute(
        sa.text("SELECT COUNT(*) FROM sqlite_master WHERE name = 'supplier_capabilities'")
    ).scalar() == 0


def test_downgrading_keeps_the_rows_and_their_numbers(connection):
    add_supplier(connection, "s-1", "Shenzhen Volta Electronics", "china", 1, 0.88)
    add_quote(connection, "q-1", "s-1", price=4.2, logistics=1.2)

    run(connection, "upgrade")
    run(connection, "downgrade")

    row = one(
        connection,
        "SELECT unit_price, moq, logistics_cost_per_unit, total_landed_cost_per_unit"
        " FROM supplier_quotes WHERE id = 'q-1'",
    )
    assert row == (4.2, 500, 1.2, 5.4)


def test_downgrading_a_fixture_supplier_does_not_call_it_verified(connection):
    """Lo simulado vuelve a `false`, que es lo que era antes de que alguien lo
    llamara `true` sin motivo."""
    add_supplier(connection, "s-1", "Shenzhen Volta Electronics", "china", 1, 0.88)
    add_quote(connection, "q-1", "s-1", verified=1)

    run(connection, "upgrade")
    run(connection, "downgrade")

    assert one(connection, "SELECT verified FROM suppliers WHERE id = 's-1'")[0] == 0
    assert one(connection, "SELECT verified FROM supplier_quotes WHERE id = 'q-1'")[0] == 0


def test_downgrading_loses_what_the_old_schema_cannot_say(connection):
    """Bajar cuesta información y conviene que un test lo diga: el esquema
    anterior no sabe representar «no se sabe»."""
    run(connection, "upgrade")
    connection.execute(
        sa.text(
            "INSERT INTO suppliers (id, name, region, verification) "
            "VALUES ('s-manual', 'Fábrica Real', 'eu', 'supplier_claim')"
        )
    )
    connection.execute(
        sa.text(
            "INSERT INTO supplier_quotes (id, product_id, supplier_id, provenance, correlation_id)"
            " VALUES ('q-empty', 'p-1', 's-manual', 'supplier_claim', 'corr-2')"
        )
    )

    run(connection, "downgrade")

    assert one(
        connection,
        "SELECT unit_price, moq, total_landed_cost_per_unit FROM supplier_quotes"
        " WHERE id = 'q-empty'",
    ) == (0.0, 0, 0.0)
