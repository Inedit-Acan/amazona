"""Ejecuta la migración del Milestone 31 de verdad, en los dos sentidos.

CI aplica la cadena entera sobre PostgreSQL limpio; esto acorta el ciclo y, sobre
todo, comprueba lo que es fácil equivocar: que las tres tablas queden con las
columnas que el modelo espera y que bajar no deje nada detrás.
"""

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.db.models.job import Job, JobAttempt, JobEvent

MIGRATION = Path(__file__).resolve().parents[2] / "alembic" / "versions" / "c8e2b17a4f93_async_job_runtime.py"


def load_migration():
    spec = importlib.util.spec_from_file_location("m31", MIGRATION)
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


def test_upgrade_creates_the_three_tables(connection):
    run(connection, "upgrade")

    assert {"jobs", "job_attempts", "job_events"} <= tables(connection)


@pytest.mark.parametrize("model", [Job, JobAttempt, JobEvent])
def test_the_migration_matches_the_model(connection, model):
    """El desajuste clásico: añadir una columna al modelo y olvidarla en la
    migración. En desarrollo no se nota porque los tests crean el esquema desde
    los modelos; en producción, la consulta revienta."""
    run(connection, "upgrade")

    expected = {column.name for column in model.__table__.columns}
    assert expected == columns(connection, model.__tablename__)


def test_the_claim_index_exists(connection):
    """El reclamo entra por status + available_at. Sin ese índice, cada vuelta
    de cada worker es un recorrido completo de la tabla."""
    run(connection, "upgrade")

    indexes = {row[1] for row in connection.execute(sa.text("PRAGMA index_list(jobs)")).fetchall()}
    assert "ix_jobs_claim" in indexes
    assert "ix_jobs_lease" in indexes


def test_the_idempotency_key_is_unique(connection):
    run(connection, "upgrade")
    insert = sa.text(
        "INSERT INTO jobs (id, type, status, payload, correlation_id, idempotency_key,"
        " attempt, max_attempts, available_at, created_at)"
        " VALUES (:id, 't', 'QUEUED', '{}', 'c', 'same-key', 0, 3, '2026-01-01', '2026-01-01')"
    )
    connection.execute(insert, {"id": "job-1"})

    with pytest.raises(sa.exc.IntegrityError):
        connection.execute(insert, {"id": "job-2"})


def test_downgrade_leaves_nothing_behind(connection):
    before = tables(connection)

    run(connection, "upgrade")
    run(connection, "downgrade")

    assert tables(connection) == before


def test_the_migration_follows_the_previous_head():
    module = load_migration()

    assert module.revision == "c8e2b17a4f93"
    assert module.down_revision == "a71c4f9d2b30"
