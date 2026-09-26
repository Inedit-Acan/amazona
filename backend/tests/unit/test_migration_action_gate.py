"""Ejecuta la migración del Milestone 33 de verdad, en los dos sentidos.

Lo que importa aquí es el relleno: las filas que ya existen en `pipeline_reviews`
son revisiones post-hoc del Milestone 14, y tienen que quedar marcadas como tales
—no como una puerta del ActionGate sin resolver, que las metería en la bandeja
pidiendo una decisión que nadie espera—.
"""

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.db.models.pipeline_review import PipelineReview
from app.db.models.pipeline_run import PipelineRun

VERSIONS = Path(__file__).resolve().parents[2] / "alembic" / "versions"
MIGRATION = VERSIONS / "b7e3d5c81f24_action_gate.py"


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def connection():
    """Una base con el esquema **anterior** a esta migración: `pipeline_reviews`
    sin clase y `pipeline_runs` sin el rol de quien la pidió."""
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    with engine.connect() as conn:
        conn.execute(
            sa.text(
                "CREATE TABLE pipeline_runs ("
                " id VARCHAR(36) NOT NULL PRIMARY KEY, product_id VARCHAR(36),"
                " category VARCHAR(64) NOT NULL, market VARCHAR(16) NOT NULL,"
                " status VARCHAR(16) NOT NULL, failed_step VARCHAR(32),"
                " needs_review BOOLEAN NOT NULL, correlation_id VARCHAR(36) NOT NULL,"
                " job_id VARCHAR(36), request JSON,"
                " created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL)"
            )
        )
        conn.execute(
            sa.text(
                "CREATE TABLE pipeline_reviews ("
                " id VARCHAR(36) NOT NULL PRIMARY KEY, pipeline_run_id VARCHAR(36) NOT NULL,"
                " reasons JSON NOT NULL, status VARCHAR(16) NOT NULL, resolved_at DATETIME,"
                " resolved_by VARCHAR(255), correlation_id VARCHAR(36) NOT NULL,"
                " created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL)"
            )
        )
        yield conn
    engine.dispose()


def run(conn, direction: str) -> None:
    module = load(MIGRATION, "m33")
    with Operations.context(MigrationContext.configure(conn)):
        getattr(module, direction)()


def columns(conn, table: str) -> set[str]:
    return {row[1] for row in conn.execute(sa.text(f"PRAGMA table_info({table})")).fetchall()}


def seed_review(conn, review_id: str) -> None:
    conn.execute(
        sa.text(
            "INSERT INTO pipeline_reviews (id, pipeline_run_id, reasons, status, correlation_id,"
            " created_at, updated_at)"
            " VALUES (:id, 'run-1', '[\"economics recommendation is NO_GO\"]', 'PENDING', 'cid-1',"
            " '2026-09-20 10:00:00', '2026-09-20 10:00:00')"
        ),
        {"id": review_id},
    )


@pytest.mark.parametrize("model", [PipelineReview, PipelineRun])
def test_the_migration_matches_the_model(connection, model):
    run(connection, "upgrade")

    expected = {column.name for column in model.__table__.columns}
    assert expected == columns(connection, model.__tablename__)


def test_the_reviews_that_already_existed_are_post_hoc(connection):
    """No son puertas sin resolver: son revisiones de ejecuciones terminadas, y
    marcarlas mal las metería en la bandeja pidiendo algo que nadie espera."""
    seed_review(connection, "rev-1")

    run(connection, "upgrade")

    row = connection.execute(
        sa.text("SELECT kind, step, action, status FROM pipeline_reviews WHERE id = 'rev-1'")
    ).one()
    assert row.kind == "POST_HOC"
    assert row.step is None
    assert row.action is None
    assert row.status == "PENDING"


def test_the_kind_is_indexed(connection):
    """La bandeja pregunta por clase en cada carga."""
    run(connection, "upgrade")

    indexes = {row[1] for row in connection.execute(sa.text("PRAGMA index_list(pipeline_reviews)"))}
    assert "ix_pipeline_reviews_kind" in indexes


def test_downgrade_leaves_the_previous_shape(connection):
    before_reviews = columns(connection, "pipeline_reviews")
    before_runs = columns(connection, "pipeline_runs")
    seed_review(connection, "rev-2")

    run(connection, "upgrade")
    run(connection, "downgrade")

    assert columns(connection, "pipeline_reviews") == before_reviews
    assert columns(connection, "pipeline_runs") == before_runs
    # Y la fila sigue ahí: bajar no puede llevarse revisiones por delante.
    assert connection.execute(sa.text("SELECT count(*) FROM pipeline_reviews")).scalar() == 1


def test_the_migration_follows_the_previous_head():
    module = load(MIGRATION, "m33")

    assert module.revision == "b7e3d5c81f24"
    assert module.down_revision == "f4a1c7d9e2b8"
