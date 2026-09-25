"""Runs the Milestone 29 migration for real, both ways.

CI applies the whole chain to a clean PostgreSQL; this keeps the feedback loop
short and, more importantly, checks the things that are easy to get wrong in a
data migration: that the seed lands, that it does not duplicate when the rows
are already there, and that downgrade leaves the schema as it was.
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
    / "a71c4f9d2b30_production_security_foundation.py"
)


def load_migration():
    spec = importlib.util.spec_from_file_location("m29", MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def connection():
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    with engine.connect() as conn:
        # The pre-migration shape of the three tables it touches, as migration
        # 473eb2bee176 and the initial schema leave them.
        conn.execute(
            sa.text(
                "CREATE TABLE roles ("
                " id VARCHAR(36) PRIMARY KEY, name VARCHAR(50) UNIQUE NOT NULL,"
                " created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL)"
            )
        )
        conn.execute(
            sa.text(
                "CREATE TABLE users ("
                " id VARCHAR(36) PRIMARY KEY, email VARCHAR(255) UNIQUE NOT NULL,"
                " display_name VARCHAR(255), role_id VARCHAR(36),"
                " created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL)"
            )
        )
        conn.execute(
            sa.text(
                "CREATE TABLE audit_log ("
                " id VARCHAR(36) PRIMARY KEY, actor VARCHAR(255) NOT NULL, action VARCHAR(255) NOT NULL,"
                " resource VARCHAR(255) NOT NULL, before JSON, after JSON,"
                " correlation_id VARCHAR(36) NOT NULL, created_at DATETIME NOT NULL)"
            )
        )
        yield conn
    engine.dispose()


def _insert_role(conn, role_id: str, name: str) -> None:
    conn.execute(
        sa.text(
            "INSERT INTO roles (id, name, created_at, updated_at)"
            " VALUES (:id, :name, '2026-01-01 00:00:00', '2026-01-01 00:00:00')"
        ),
        {"id": role_id, "name": name},
    )


def columns(conn, table: str) -> set[str]:
    return {row[1] for row in conn.execute(sa.text(f"PRAGMA table_info({table})")).fetchall()}


def role_names(conn) -> list[str]:
    return sorted(row[0] for row in conn.execute(sa.text("SELECT name FROM roles")).fetchall())


def run(conn, direction: str) -> None:
    module = load_migration()
    with Operations.context(MigrationContext.configure(conn)):
        getattr(module, direction)()


def test_upgrade_adds_the_identity_columns(connection):
    run(connection, "upgrade")

    assert "subject" in columns(connection, "users")
    assert {"actor_role", "actor_source"} <= columns(connection, "audit_log")


def test_upgrade_seeds_the_seven_roles(connection):
    run(connection, "upgrade")

    assert role_names(connection) == ["ADMIN", "ANALYST", "OPERATOR", "OWNER", "REVIEWER", "SYSTEM", "VIEWER"]


def test_upgrade_does_not_duplicate_roles_that_already_exist(connection):
    _insert_role(connection, "role-owner", "OWNER")

    run(connection, "upgrade")

    assert role_names(connection).count("OWNER") == 1
    assert len(role_names(connection)) == 7


def test_downgrade_restores_the_previous_schema(connection):
    before = columns(connection, "users"), columns(connection, "audit_log")

    run(connection, "upgrade")
    run(connection, "downgrade")

    assert (columns(connection, "users"), columns(connection, "audit_log")) == before
    assert role_names(connection) == []


def test_downgrade_leaves_roles_it_did_not_seed(connection):
    _insert_role(connection, "role-custom", "CUSTOM")

    run(connection, "upgrade")
    run(connection, "downgrade")

    assert role_names(connection) == ["CUSTOM"]


def test_the_migration_follows_the_previous_head():
    module = load_migration()

    assert module.revision == "a71c4f9d2b30"
    assert module.down_revision == "ebc8b88725e2"
