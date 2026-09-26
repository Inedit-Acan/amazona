"""Ejecuta la migración del Milestone 32 de verdad, en los dos sentidos.

Lo que de verdad importa aquí no son las dos tablas nuevas sino la columna que
**desaparece**: `pipeline_runs.steps` pasa a ser filas de `pipeline_steps`, y esta
prueba comprueba con datos dentro que subir no pierde nada y que bajar reconstruye
el mismo JSON. Una migración destructiva sin esa prueba es una apuesta.

CI aplica la cadena entera sobre PostgreSQL limpio; esto acorta el ciclo y cubre
además el desajuste clásico: añadir una columna al modelo y olvidarla aquí.
"""

import importlib.util
import json
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.db.models.pipeline_run import PipelineRun
from app.db.models.pipeline_step import PipelineStep, PipelineStepAttempt

MIGRATION = Path(__file__).resolve().parents[2] / "alembic" / "versions" / "f4a1c7d9e2b8_async_pipeline.py"

#: El JSON tal y como lo escribía el Milestone 12: una ejecución completa.
LEGACY_COMPLETED = {
    "research": {"correlation_id": "cid-research", "entity_id": "prod-1", "candidate_count": 5},
    "sourcing": {"correlation_id": "cid-sourcing", "entity_id": "quote-1", "candidate_count": 3},
    "economics": {"correlation_id": "cid-econ", "entity_id": "econ-1", "recommendation": "GO"},
    "legal": {"correlation_id": "cid-legal", "entity_id": "legal-1", "recommendation": "REVIEW"},
    "ecommerce": {"correlation_id": "cid-shop", "entity_id": "shop-1", "status": "LAUNCHED"},
    "marketplace": {"correlation_id": "cid-mkt", "entity_id": "listing-1", "status": "BLOCKED"},
    "marketing": {"correlation_id": "cid-ads", "entity_id": "camp-1", "status": "BLOCKED"},
    "operations": {"correlation_id": "cid-ops", "entity_id": "ops-1", "status": "READY"},
    "cfo": {"correlation_id": "cid-cfo", "entity_id": "cfo-1", "status": "HEALTHY"},
}

#: Y una que se quedó a mitad.
LEGACY_PARTIAL = {"research": {"correlation_id": "cid-r2", "candidate_count": 0}}


def load_migration():
    spec = importlib.util.spec_from_file_location("m32", MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def connection():
    """Una base con el esquema **anterior** a esta migración: `pipeline_runs` con
    su JSON `steps` y sin `job_id` ni `request`."""
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    with engine.connect() as conn:
        conn.execute(
            sa.text(
                "CREATE TABLE jobs (id VARCHAR(36) NOT NULL PRIMARY KEY, type VARCHAR(100),"
                " status VARCHAR(20))"
            )
        )
        conn.execute(
            sa.text(
                "CREATE TABLE pipeline_runs ("
                " id VARCHAR(36) NOT NULL PRIMARY KEY,"
                " product_id VARCHAR(36),"
                " category VARCHAR(64) NOT NULL,"
                " market VARCHAR(16) NOT NULL,"
                " status VARCHAR(16) NOT NULL,"
                " failed_step VARCHAR(32),"
                " steps JSON NOT NULL,"
                " needs_review BOOLEAN NOT NULL,"
                " correlation_id VARCHAR(36) NOT NULL,"
                " created_at DATETIME NOT NULL,"
                " updated_at DATETIME NOT NULL)"
            )
        )
        yield conn
    engine.dispose()


def seed(conn, run_id: str, status: str, steps: dict) -> None:
    conn.execute(
        sa.text(
            "INSERT INTO pipeline_runs (id, product_id, category, market, status, failed_step, steps,"
            " needs_review, correlation_id, created_at, updated_at)"
            " VALUES (:id, 'prod-1', 'home', 'us', :status, NULL, :steps, 0, :cid,"
            " '2026-09-20 10:00:00', '2026-09-20 10:00:00')"
        ),
        {"id": run_id, "status": status, "steps": json.dumps(steps), "cid": f"cid-{run_id}"},
    )


def run(conn, direction: str) -> None:
    module = load_migration()
    with Operations.context(MigrationContext.configure(conn)):
        getattr(module, direction)()


def tables(conn) -> set[str]:
    return set(sa.inspect(conn).get_table_names())


def columns(conn, table: str) -> set[str]:
    return {row[1] for row in conn.execute(sa.text(f"PRAGMA table_info({table})")).fetchall()}


def test_upgrade_creates_the_two_tables(connection):
    run(connection, "upgrade")

    assert {"pipeline_steps", "pipeline_step_attempts"} <= tables(connection)


@pytest.mark.parametrize("model", [PipelineRun, PipelineStep, PipelineStepAttempt])
def test_the_migration_matches_the_model(connection, model):
    """El desajuste clásico: añadir una columna al modelo y olvidarla en la
    migración. En desarrollo no se nota porque los tests crean el esquema desde
    los modelos; en producción, la consulta revienta."""
    run(connection, "upgrade")

    expected = {column.name for column in model.__table__.columns}
    assert expected == columns(connection, model.__tablename__)


def test_upgrade_drops_the_steps_json_and_adds_the_new_columns(connection):
    run(connection, "upgrade")

    present = columns(connection, "pipeline_runs")
    assert "steps" not in present
    assert {"job_id", "request"} <= present


def test_upgrade_turns_the_existing_json_into_rows_without_losing_anything(connection):
    seed(connection, "run-1", "COMPLETED", LEGACY_COMPLETED)

    run(connection, "upgrade")

    rows = connection.execute(
        sa.text(
            "SELECT name, ordinal, status, correlation_id, entity_id, detail FROM pipeline_steps"
            " WHERE pipeline_run_id = 'run-1' ORDER BY ordinal"
        )
    ).fetchall()
    assert [row[0] for row in rows] == [
        "research",
        "sourcing",
        "economics",
        "legal",
        "ecommerce",
        "marketplace",
        "marketing",
        "operations",
        "cfo",
    ]
    assert {row[2] for row in rows} == {"COMPLETED"}

    by_name = {row[0]: row for row in rows}
    assert by_name["research"][3] == "cid-research"
    assert by_name["research"][4] == "prod-1"
    assert json.loads(by_name["research"][5]) == {"candidate_count": 5}
    # El estado de negocio que la evaluación de riesgo lee (ADR 0006) sigue ahí.
    assert json.loads(by_name["marketplace"][5]) == {"status": "BLOCKED"}
    assert json.loads(by_name["economics"][5]) == {"recommendation": "GO"}


def test_a_partial_run_keeps_its_last_step_failed_and_the_rest_skipped(connection):
    """Una ejecución que se quedó a mitad tiene que quedar reanudable: el paso
    que no pudo entregar nada es FAILED, y los que nunca corrieron, SKIPPED."""
    seed(connection, "run-2", "PARTIAL", LEGACY_PARTIAL)

    run(connection, "upgrade")

    statuses = dict(
        connection.execute(
            sa.text("SELECT name, status FROM pipeline_steps WHERE pipeline_run_id = 'run-2'")
        ).fetchall()
    )
    assert statuses["research"] == "FAILED"
    assert statuses["sourcing"] == "SKIPPED"
    assert statuses["cfo"] == "SKIPPED"


def test_upgrade_backfills_what_the_request_can_still_be_deduced_from(connection):
    """Las ejecuciones anteriores no guardaron sus parámetros. Se rellena lo que
    consta en columnas propias y nada más: un precio de venta inventado sería
    peor que admitir que no está."""
    seed(connection, "run-3", "COMPLETED", LEGACY_COMPLETED)

    run(connection, "upgrade")

    request = connection.execute(
        sa.text("SELECT request FROM pipeline_runs WHERE id = 'run-3'")
    ).scalar()
    assert json.loads(request) == {"category": "home", "market": "us"}


def test_downgrade_rebuilds_the_same_json(connection):
    seed(connection, "run-4", "COMPLETED", LEGACY_COMPLETED)

    run(connection, "upgrade")
    run(connection, "downgrade")

    restored = connection.execute(sa.text("SELECT steps FROM pipeline_runs WHERE id = 'run-4'")).scalar()
    assert json.loads(restored) == LEGACY_COMPLETED


def test_downgrade_leaves_nothing_behind(connection):
    before = tables(connection)
    before_columns = columns(connection, "pipeline_runs")

    run(connection, "upgrade")
    run(connection, "downgrade")

    assert tables(connection) == before
    assert columns(connection, "pipeline_runs") == before_columns


def test_the_unique_constraint_stops_a_duplicated_step(connection):
    """Reanudar no puede duplicar filas: un paso por nombre y por ejecución."""
    run(connection, "upgrade")
    insert = sa.text(
        "INSERT INTO pipeline_steps (id, pipeline_run_id, name, ordinal, status, attempt,"
        " created_at, updated_at)"
        " VALUES (:id, 'run-9', 'research', 0, 'PENDING', 0, '2026-01-01', '2026-01-01')"
    )
    connection.execute(insert, {"id": "step-1"})

    with pytest.raises(sa.exc.IntegrityError):
        connection.execute(insert, {"id": "step-2"})


def test_the_migration_follows_the_previous_head():
    module = load_migration()

    assert module.revision == "f4a1c7d9e2b8"
    assert module.down_revision == "c8e2b17a4f93"
