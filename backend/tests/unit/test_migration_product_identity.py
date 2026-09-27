"""Ejecuta la migración del Milestone 36 de verdad, en los dos sentidos y con
datos dentro — porque esta sí rellena una columna sobre filas que ya existían."""

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.db.models.product import Product
from app.db.models.product_identity_alias import ProductIdentityAlias
from app.integrations.product_intelligence import identity

MIGRATION = (
    Path(__file__).resolve().parents[2] / "alembic" / "versions" / "d1e8b4a7c206_product_identity.py"
)


def load_migration():
    spec = importlib.util.spec_from_file_location("m36", MIGRATION)
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
                "CREATE TABLE products (id VARCHAR(36) NOT NULL PRIMARY KEY,"
                " name VARCHAR(255), category VARCHAR(100), status VARCHAR(32),"
                " created_by VARCHAR(255), source VARCHAR(32),"
                " created_at DATETIME, updated_at DATETIME)"
            )
        )
        yield conn
    engine.dispose()


def run(conn, direction: str) -> None:
    module = load_migration()
    with Operations.context(MigrationContext.configure(conn)):
        getattr(module, direction)()


def add_product(conn, product_id: str, name: str) -> None:
    conn.execute(
        sa.text(
            "INSERT INTO products (id, name, category, status, created_by, source)"
            " VALUES (:id, :name, 'home', 'CANDIDATE', 'agent-product-research-1', 'research')"
        ),
        {"id": product_id, "name": name},
    )


def tables(conn) -> set[str]:
    return set(sa.inspect(conn).get_table_names())


def columns(conn, table: str) -> set[str]:
    return {row[1] for row in conn.execute(sa.text(f"PRAGMA table_info({table})")).fetchall()}


def test_upgrade_adds_the_column_and_the_table(connection):
    run(connection, "upgrade")

    assert "identity_key" in columns(connection, "products")
    assert "product_identity_aliases" in tables(connection)


def test_the_migration_matches_the_models(connection):
    run(connection, "upgrade")

    assert {c.name for c in ProductIdentityAlias.__table__.columns} == columns(
        connection, "product_identity_aliases"
    )
    assert {c.name for c in Product.__table__.columns} == columns(connection, "products")


def test_existing_rows_get_the_identity_of_their_name(connection):
    """Dejarlas a NULL haría que la primera investigación las duplicara todas."""
    add_product(connection, "p-1", "Air fryer")
    add_product(connection, "p-2", "  AIR   FRYER ")
    add_product(connection, "p-3", "Belt (clothing)")

    run(connection, "upgrade")

    keys = dict(connection.execute(sa.text("SELECT id, identity_key FROM products")).all())
    assert keys["p-1"] == "air fryer"
    assert keys["p-2"] == "air fryer"
    assert keys["p-3"] == "belt"


def test_the_frozen_copy_still_agrees_with_the_application(connection):
    """La migración lleva su propia copia de `fold` a propósito: tiene que poder
    ejecutarse dentro de tres años. Este test avisa el día que divergen."""
    module = load_migration()

    for name in ["Air fryer", "  AIR FRYER ", "Belt (clothing)", "Café", "???", "Чайник"]:
        assert module.fold(name) == identity.fold(name), name


def test_the_backfill_does_not_apply_the_alias_catalogue(connection):
    """Un límite escrito, no un descuido: congelar una lista que cambia daría la
    ilusión de estar al día. Una fila antigua llamada `airfryer` conserva su
    propia clave y su duplicado preexistente no se resuelve solo."""
    add_product(connection, "p-1", "airfryer")

    run(connection, "upgrade")

    key = connection.execute(sa.text("SELECT identity_key FROM products")).scalar()
    assert key == "airfryer"
    assert identity.resolve("airfryer").key == "air fryer"


def test_the_lookup_index_exists(connection):
    """Se busca por identidad y categoría antes de crear cada producto."""
    run(connection, "upgrade")

    indexes = {row[1] for row in connection.execute(sa.text("PRAGMA index_list(products)"))}
    assert "ix_products_identity_category" in indexes


def test_a_fusion_keeps_its_reason(connection):
    run(connection, "upgrade")
    add_product(connection, "p-1", "Air fryer")
    connection.execute(
        sa.text(
            "INSERT INTO product_identity_aliases (id, product_id, alias, identity_key, method,"
            " correlation_id, created_at) VALUES ('a-1', 'p-1', 'airfryer', 'air fryer',"
            " 'alias:v1', 'cid-1', '2026-09-27 00:00:00')"
        )
    )

    row = connection.execute(
        sa.text("SELECT alias, method FROM product_identity_aliases WHERE id = 'a-1'")
    ).one()

    assert row.alias == "airfryer"
    assert row.method == "alias:v1"


def test_the_identity_is_not_unique_on_purpose(connection):
    """Aquí también hay productos dados de alta a mano: una restricción única
    impediría crear dos cosas que la normalización colapse."""
    run(connection, "upgrade")
    add_product(connection, "p-1", "Air fryer")
    add_product(connection, "p-2", "air fryer")

    connection.execute(sa.text("UPDATE products SET identity_key = 'air fryer'"))

    assert connection.execute(sa.text("SELECT COUNT(*) FROM products")).scalar() == 2


def test_downgrade_leaves_nothing_behind(connection):
    add_product(connection, "p-1", "Air fryer")
    before = tables(connection)
    before_columns = columns(connection, "products")

    run(connection, "upgrade")
    run(connection, "downgrade")

    assert tables(connection) == before
    assert columns(connection, "products") == before_columns
    # Y la fila sigue ahí: la migración no es destructiva en ningún sentido.
    assert connection.execute(sa.text("SELECT COUNT(*) FROM products")).scalar() == 1


def test_the_migration_follows_the_previous_head():
    module = load_migration()

    assert module.revision == "d1e8b4a7c206"
    assert module.down_revision == "a5f1c62d87e4"
