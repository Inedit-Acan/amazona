"""Ejecuta la migración del Milestone 43 de verdad, en los dos sentidos y con datos
dentro.

El esquema de partida está escrito a mano y **congelado**: es el que dejó el
Milestone 41 en las tablas que esta migración referencia. Un test de migración que
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
    / "b6d2f8a41c93_national_transpositions_and_anchors.py"
)
NEW_TABLES = {"national_transpositions", "national_anchors"}

SCHEMA_BEFORE_M43 = (
    "CREATE TABLE regulatory_requirements (id VARCHAR(36) NOT NULL PRIMARY KEY,"
    " celex VARCHAR(16) NOT NULL, transposition_reference VARCHAR(255))",
    "INSERT INTO regulatory_requirements (id, celex, transposition_reference)"
    " VALUES ('r-1', '32009L0048', 'Real Decreto 1205/2011')",
)


def load_migration():
    spec = importlib.util.spec_from_file_location("m43", MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def connection():
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    with engine.connect() as conn:
        conn.execute(sa.text("PRAGMA foreign_keys=ON"))
        for statement in SCHEMA_BEFORE_M43:
            conn.execute(sa.text(statement))
        yield conn
    engine.dispose()


def run(conn, direction: str) -> None:
    module = load_migration()
    with Operations.context(MigrationContext.configure(conn)):
        getattr(module, direction)()


def tables(conn) -> set[str]:
    return {r[0] for r in conn.execute(sa.text("SELECT name FROM sqlite_master WHERE type='table'"))}


def columns(conn, table) -> set[str]:
    return {r[1] for r in conn.execute(sa.text(f"PRAGMA table_info({table})")).fetchall()}


def test_the_revision_chains_after_the_security_migration_that_closes_the_rls_gap():
    module = load_migration()

    assert module.revision == "b6d2f8a41c93"
    assert module.down_revision == "9f2b6c0a1d47"


def test_upgrade_creates_the_two_tables(connection):
    run(connection, "upgrade")

    assert NEW_TABLES <= tables(connection)


def test_the_layers_live_in_different_tables(connection):
    run(connection, "upgrade")

    assert {"requirement_id", "national_id", "provenance", "declared_by", "withdrawn_at"} <= columns(
        connection, "national_transpositions"
    )
    assert {
        "national_id",
        "verified_at",
        "recheck_after",
        "consolidated",
        "informational",
        "notice",
        "attribution",
        "source_metadata",
        "relations",
        "publication_state",
        "publication_detail",
        "publication_url",
    } <= columns(connection, "national_anchors")


def test_upgrade_does_not_touch_the_existing_requirement_or_its_free_text(connection):
    before = columns(connection, "regulatory_requirements")

    run(connection, "upgrade")

    assert columns(connection, "regulatory_requirements") == before
    row = connection.execute(
        sa.text("SELECT celex, transposition_reference FROM regulatory_requirements")
    ).one()
    assert tuple(row) == ("32009L0048", "Real Decreto 1205/2011")


def test_data_survives_the_round_trip_and_downgrade_removes_only_the_new_tables(connection):
    run(connection, "upgrade")
    connection.execute(
        sa.text(
            "INSERT INTO national_transpositions (id, requirement_id, national_id, provenance,"
            " declared_by) VALUES ('t-1', 'r-1', 'BOE-A-2011-14252', 'declared', 'owner')"
        )
    )
    connection.execute(
        sa.text(
            "INSERT INTO national_anchors (id, national_id, provider, provenance, verified_at,"
            " recheck_after, consolidated, informational, notice, attribution, source_metadata,"
            " relations, publication_state) VALUES ('a-1', 'BOE-A-2011-14252', 'boe-open-data',"
            " 'third_party_verified', '2026-09-30 10:00:00', '2026-10-30 10:00:00', 1, 1, 'n', 'a',"
            " '{\"identificador\": \"BOE-A-2011-14252\"}', '{\"previous\": [], \"next\": []}',"
            " 'confirmed')"
        )
    )

    stored = connection.execute(sa.text("SELECT national_id FROM national_transpositions")).scalar_one()
    assert stored == "BOE-A-2011-14252"

    run(connection, "downgrade")

    assert not NEW_TABLES & tables(connection)
    assert "regulatory_requirements" in tables(connection)
    assert connection.execute(sa.text("SELECT count(*) FROM regulatory_requirements")).scalar_one() == 1


def test_upgrade_after_downgrade_works_again(connection):
    run(connection, "upgrade")
    run(connection, "downgrade")
    run(connection, "upgrade")

    assert NEW_TABLES <= tables(connection)


def test_a_transposition_cannot_point_at_a_missing_requirement(connection):
    run(connection, "upgrade")

    with pytest.raises(sa.exc.IntegrityError):
        connection.execute(
            sa.text(
                "INSERT INTO national_transpositions (id, requirement_id, national_id, provenance,"
                " declared_by) VALUES ('t-x', 'missing', 'BOE-A-2011-14252', 'declared', 'owner')"
            )
        )
