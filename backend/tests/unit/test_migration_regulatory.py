"""Ejecuta la migración del Milestone 41 de verdad, en los dos sentidos y con datos
dentro.

El esquema de partida está escrito a mano y **congelado**: es el que dejó el
Milestone 40 en las tablas que esta migración referencia. Un test de migración que
compara contra los modelos vivos caduca en cuanto otro milestone toca la tabla.
"""

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "e5f8a2c1b7d4_regulatory_requirements_and_anchors.py"
)

NEW_TABLES = {"regulatory_requirements", "regulatory_anchors", "compliance_evidence"}

#: Lo único que esta migración necesita del pasado: la tabla `products` a la que
#: apunta la clave foránea de la evidencia, y una fila de `legal_analyses` para
#: comprobar que no se toca.
SCHEMA_BEFORE_M41 = (
    "CREATE TABLE products (id VARCHAR(36) NOT NULL PRIMARY KEY, name VARCHAR(255) NOT NULL)",
    "CREATE TABLE legal_analyses ("
    " id VARCHAR(36) NOT NULL PRIMARY KEY, product_id VARCHAR(36), market VARCHAR(16),"
    " recommendation VARCHAR(16), confidence FLOAT, data JSON, correlation_id VARCHAR(36))",
)


def load_migration():
    spec = importlib.util.spec_from_file_location("m41", MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def connection():
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    with engine.connect() as conn:
        for statement in SCHEMA_BEFORE_M41:
            conn.execute(sa.text(statement))
        yield conn
    engine.dispose()


def run(conn, direction: str) -> None:
    module = load_migration()
    with Operations.context(MigrationContext.configure(conn)):
        getattr(module, direction)()


def tables(conn) -> set[str]:
    return {
        row[0]
        for row in conn.execute(sa.text("SELECT name FROM sqlite_master WHERE type='table'"))
    }


def columns(conn, table) -> set[str]:
    return {row[1] for row in conn.execute(sa.text(f"PRAGMA table_info({table})")).fetchall()}


def test_the_revision_chains_after_the_single_previous_head():
    module = load_migration()

    assert module.revision == "e5f8a2c1b7d4"
    assert module.down_revision == "d8b4c1e70a29"


def test_upgrade_creates_the_three_tables(connection):
    run(connection, "upgrade")

    assert NEW_TABLES <= tables(connection)


def test_the_three_questions_live_in_three_different_tables(connection):
    run(connection, "upgrade")

    assert {"product_scope", "applicability_provenance", "declared_by", "celex"} <= columns(
        connection, "regulatory_requirements"
    )
    assert {
        "verified_at",
        "recheck_after",
        "source_effective_from",
        "source_effective_to",
        "in_force",
        "found",
    } <= columns(connection, "regulatory_anchors")
    assert {"product_id", "requirement_id", "provenance", "valid_until"} <= columns(
        connection, "compliance_evidence"
    )


def test_upgrade_does_not_touch_existing_legal_analyses(connection):
    connection.execute(
        sa.text(
            "INSERT INTO legal_analyses (id, product_id, market, recommendation, confidence,"
            " correlation_id) VALUES ('a-1', 'p-1', 'eu', 'GO', 0.85, 'c-1')"
        )
    )
    before = columns(connection, "legal_analyses")

    run(connection, "upgrade")

    assert columns(connection, "legal_analyses") == before
    row = connection.execute(sa.text("SELECT recommendation, confidence FROM legal_analyses")).one()
    assert tuple(row) == ("GO", 0.85)


def test_data_survives_a_round_trip_within_the_new_tables(connection):
    run(connection, "upgrade")
    connection.execute(sa.text("INSERT INTO products (id, name) VALUES ('p-1', 'Toy')"))
    connection.execute(
        sa.text(
            "INSERT INTO regulatory_requirements (id, product_scope, scope_key, jurisdiction, celex,"
            " regulation, requirement, kind, applicability_provenance, declared_by)"
            " VALUES ('r-1', 'Toys', 'toys', 'eu', '32023R0988', 'GPSR', 'text', 'obligation',"
            " 'declared', 'owner')"
        )
    )
    connection.execute(
        sa.text(
            "INSERT INTO regulatory_anchors (id, celex, provider, verified_at, recheck_after, found,"
            " act_type, source_url) VALUES ('a-1', '32023R0988', 'eur-lex-cellar',"
            " '2026-09-29 10:00:00', '2026-10-29 10:00:00', 1, 'regulation', 'https://x')"
        )
    )
    connection.execute(
        sa.text(
            "INSERT INTO compliance_evidence (id, product_id, requirement_id, provenance, declared_by)"
            " VALUES ('e-1', 'p-1', 'r-1', 'declared', 'owner')"
        )
    )

    counts = [
        connection.execute(sa.text(f"SELECT COUNT(*) FROM {t}")).scalar() for t in sorted(NEW_TABLES)
    ]

    assert counts == [1, 1, 1]


def test_an_anchor_defaults_to_third_party_verified(connection):
    run(connection, "upgrade")
    connection.execute(
        sa.text(
            "INSERT INTO regulatory_anchors (id, celex, provider, verified_at, recheck_after, found,"
            " act_type, source_url) VALUES ('a-1', '32023R0988', 'eur-lex-cellar',"
            " '2026-09-29', '2026-10-29', 1, 'regulation', 'https://x')"
        )
    )

    assert (
        connection.execute(sa.text("SELECT provenance FROM regulatory_anchors")).scalar()
        == "third_party_verified"
    )


def test_downgrade_drops_the_three_tables_and_leaves_the_rest(connection):
    run(connection, "upgrade")

    run(connection, "downgrade")

    assert not (NEW_TABLES & tables(connection))
    assert {"products", "legal_analyses"} <= tables(connection)


def test_downgrade_with_data_inside_works(connection):
    run(connection, "upgrade")
    connection.execute(
        sa.text(
            "INSERT INTO regulatory_requirements (id, product_scope, scope_key, jurisdiction, celex,"
            " regulation, requirement, kind, applicability_provenance, declared_by)"
            " VALUES ('r-1', 'Toys', 'toys', 'eu', '32023R0988', 'GPSR', 'text', 'obligation',"
            " 'declared', 'owner')"
        )
    )

    run(connection, "downgrade")

    assert "regulatory_requirements" not in tables(connection)


def test_the_migration_can_go_up_again_after_going_down(connection):
    run(connection, "upgrade")
    run(connection, "downgrade")

    run(connection, "upgrade")

    assert NEW_TABLES <= tables(connection)
