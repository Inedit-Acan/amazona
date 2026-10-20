"""La migración tarea ↔ agente (M48, Commit 7), ejecutada de verdad sobre SQLite y comprobada en su rama de PostgreSQL.

Qué cambia: `tasks.assigned_agent_id` deja de apuntar a la tabla `agents` (que el sistema no puebla: los agentes viven
en el REGISTRO del código, y una clave ajena a una tabla vacía no admite ningún id real) y `agent_execution_log` gana
el vínculo con la tarea, la foto de la asignación, el intento y las horas. **Ningún dato existente se toca**: todo lo
nuevo nace nulo, y las ejecuciones y tareas de las misiones anteriores quedan como estaban. Sin tablas nuevas, así que
no hay RLS que activar: las columnas heredan la de su tabla."""

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from m44_migration_test_support import RecordingOp, assert_migration_matches_model

import app.db.models  # noqa: F401 - registra todas las tablas en el metadata

MIGRATION = Path(__file__).resolve().parents[2] / "alembic" / "versions" / "a9d4f7b2c613_task_agent_relation.py"

OLD_SCHEMA = [
    "CREATE TABLE agents (id VARCHAR(36) PRIMARY KEY)",
    "CREATE TABLE projects (id VARCHAR(36) PRIMARY KEY)",
    """CREATE TABLE tasks (
        project_id VARCHAR(36) NOT NULL, name VARCHAR(255) NOT NULL, capability VARCHAR(100) NOT NULL, status
        VARCHAR(32) NOT NULL,
        assigned_agent_id VARCHAR(36), input JSON, output JSON, error TEXT, started_at DATETIME, completed_at DATETIME,
        id VARCHAR(36) NOT NULL, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL,
        PRIMARY KEY (id),
        FOREIGN KEY(assigned_agent_id) REFERENCES agents (id),
        FOREIGN KEY(project_id) REFERENCES projects (id))""",
    """CREATE TABLE agent_execution_log (
        agent_id VARCHAR(36) NOT NULL, capability VARCHAR(100) NOT NULL, duration_ms FLOAT NOT NULL, success BOOLEAN
        NOT NULL,
        correlation_id VARCHAR(36) NOT NULL, id VARCHAR(36) NOT NULL, created_at DATETIME NOT NULL, updated_at
        DATETIME NOT NULL,
        PRIMARY KEY (id))""",
]

NEW_EXECUTION_COLUMNS = {"task_id", "assigned_agent_id", "attempt", "started_at", "completed_at"}


def load_migration():
    spec = importlib.util.spec_from_file_location("task_agent_relation_migration", MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def conn():
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    with engine.connect() as connection:
        for statement in OLD_SCHEMA:
            connection.execute(sa.text(statement))
        # El histórico real: tareas sin asignar y ejecuciones sin vínculo.
        connection.execute(sa.text("INSERT INTO projects (id) VALUES ('p-1')"))
        now = "2026-10-19 11:39:00"
        for index, capability in enumerate(("market_validation", "decision_synthesis")):
            connection.execute(
                sa.text(
                    "INSERT INTO tasks (project_id, name, capability, status, id, created_at, updated_at)"
                    f" VALUES ('p-1', 't{index}', '{capability}', 'COMPLETED', 't-{index}', '{now}', '{now}')"
                )
            )
        connection.execute(
            sa.text(
                "INSERT INTO agent_execution_log"
                " (agent_id, capability, duration_ms, success, correlation_id, id, created_at, updated_at)"
                f" VALUES ('agent-product-1', 'market_validation', 0.04, 1, 'c-old', 'e-0', '{now}', '{now}')"
            )
        )
        connection.commit()
        yield connection
    engine.dispose()


def run(connection, direction: str) -> None:
    with Operations.context(MigrationContext.configure(connection)):
        getattr(load_migration(), direction)()


def columns(connection, table: str) -> dict[str, bool]:
    return {c["name"]: c["nullable"] for c in sa.inspect(connection).get_columns(table)}


def test_it_adds_the_link_the_snapshot_the_attempt_and_the_times_all_nullable(conn):
    run(conn, "upgrade")

    found = columns(conn, "agent_execution_log")
    assert NEW_EXECUTION_COLUMNS <= set(found)
    assert all(found[name] for name in NEW_EXECUTION_COLUMNS), "todo lo nuevo admite nulo: el histórico no se inventa"


def test_it_does_not_touch_a_single_existing_row(conn):
    before_tasks = conn.execute(sa.text("SELECT * FROM tasks ORDER BY id")).fetchall()
    before_log = conn.execute(
        sa.text("SELECT agent_id, capability, duration_ms, success, correlation_id, id FROM agent_execution_log")
    ).fetchall()

    run(conn, "upgrade")

    assert conn.execute(sa.text("SELECT * FROM tasks ORDER BY id")).fetchall() == before_tasks
    assert (
        conn.execute(
            sa.text("SELECT agent_id, capability, duration_ms, success, correlation_id, id FROM agent_execution_log")
        ).fetchall()
        == before_log
    )
    row = conn.execute(
        sa.text("SELECT task_id, assigned_agent_id, attempt, started_at, completed_at FROM agent_execution_log")
    ).one()
    assert tuple(row) == (None, None, None, None, None)
    assert conn.execute(sa.text("SELECT count(*) FROM tasks WHERE assigned_agent_id IS NOT NULL")).scalar() == 0


def test_the_assignment_no_longer_points_at_the_empty_agents_table_but_the_project_link_stays(conn):
    run(conn, "upgrade")

    foreign_keys = {
        tuple(fk["constrained_columns"]): fk["referred_table"] for fk in sa.inspect(conn).get_foreign_keys("tasks")
    }

    assert ("assigned_agent_id",) not in foreign_keys
    assert foreign_keys[("project_id",)] == "projects"


def test_an_agent_id_from_the_registry_can_now_be_stored_on_a_task(conn):
    run(conn, "upgrade")
    conn.execute(sa.text("PRAGMA foreign_keys = ON"))

    conn.execute(sa.text("UPDATE tasks SET assigned_agent_id = 'agent-product-1' WHERE id = 't-0'"))

    assert conn.execute(sa.text("SELECT assigned_agent_id FROM tasks WHERE id = 't-0'")).scalar() == "agent-product-1"


def test_an_execution_references_a_task_that_exists(conn):
    run(conn, "upgrade")

    foreign_keys = {
        tuple(fk["constrained_columns"]): fk["referred_table"]
        for fk in sa.inspect(conn).get_foreign_keys("agent_execution_log")
    }
    assert foreign_keys == {("task_id",): "tasks"}

    conn.execute(sa.text("PRAGMA foreign_keys = ON"))
    with pytest.raises(sa.exc.IntegrityError):
        conn.execute(
            sa.text(
                "INSERT INTO agent_execution_log"
                " (agent_id, capability, duration_ms, success, correlation_id, id, created_at, updated_at, task_id)"
                " VALUES ('agent-product-1', 'market_validation', 1, 1, 'c', 'e-9',"
                " '2026-10-20 10:00:00', '2026-10-20 10:00:00', 'no-such-task')"
            )
        )


def test_the_migrated_tables_match_what_the_model_declares(conn):
    run(conn, "upgrade")

    assert_migration_matches_model(conn, ("tasks", "agent_execution_log"))


def test_it_creates_the_two_indexes_the_reads_use(conn):
    run(conn, "upgrade")

    indexes = {
        table: {i["name"] for i in sa.inspect(conn).get_indexes(table)} for table in ("tasks", "agent_execution_log")
    }

    assert "ix_tasks_assigned_agent_id" in indexes["tasks"]
    assert "ix_agent_execution_log_task_id" in indexes["agent_execution_log"]


def test_going_down_with_nothing_new_restores_the_old_shape(conn):
    run(conn, "upgrade")

    run(conn, "downgrade")

    assert not NEW_EXECUTION_COLUMNS & set(columns(conn, "agent_execution_log"))
    assert {tuple(fk["constrained_columns"]) for fk in sa.inspect(conn).get_foreign_keys("tasks")} == {
        ("assigned_agent_id",),
        ("project_id",),
    }


def test_going_down_is_refused_when_it_would_lose_information_that_cannot_be_rebuilt(conn):
    run(conn, "upgrade")
    conn.execute(sa.text("UPDATE tasks SET assigned_agent_id = 'agent-product-1' WHERE id = 't-0'"))

    with pytest.raises(RuntimeError, match="assigned"):
        run(conn, "downgrade")

    assert NEW_EXECUTION_COLUMNS <= set(columns(conn, "agent_execution_log")), "no se deshizo nada a medias"


def test_going_down_is_refused_when_an_execution_already_carries_a_link(conn):
    run(conn, "upgrade")
    conn.execute(sa.text("UPDATE agent_execution_log SET task_id = 't-0', attempt = 1"))

    with pytest.raises(RuntimeError, match="execution"):
        run(conn, "downgrade")


def test_the_postgresql_branch_drops_the_foreign_key_by_name_with_if_exists_and_adds_no_new_table(monkeypatch):
    module = load_migration()
    recorder = RecordingOp(supabase_roles=False)
    monkeypatch.setattr(module, "op", recorder)

    module.upgrade()

    assert any(
        "DROP CONSTRAINT IF EXISTS tasks_assigned_agent_id_fkey" in statement for statement in recorder.statements
    )
    assert not any("CREATE TABLE" in statement.upper() for statement in recorder.statements)


def test_the_revision_chain_has_one_head_after_b7e4a1c9d052():
    module = load_migration()

    assert module.revision == "a9d4f7b2c613"
    assert module.down_revision == "b7e4a1c9d052"


def test_the_postgresql_branch_adds_the_five_columns_the_foreign_key_and_the_two_indexes(monkeypatch):
    module = load_migration()
    calls: list[tuple[str, tuple]] = []

    class Recorder(RecordingOp):
        def add_column(self, table, column):
            calls.append(("add_column", (table, column.name, column.nullable)))

        def create_index(self, name, table, cols, **_):
            calls.append(("create_index", (name, table, tuple(cols))))

        def create_foreign_key(self, name, source, target, local, remote, **_):
            calls.append(("create_foreign_key", (name, source, target, tuple(local), tuple(remote))))

    monkeypatch.setattr(module, "op", Recorder(supabase_roles=False))

    module.upgrade()

    assert {c[1][1] for c in calls if c[0] == "add_column"} == NEW_EXECUTION_COLUMNS
    assert all(c[1][2] for c in calls if c[0] == "add_column"), "todo lo nuevo admite nulo"
    assert ("create_index", ("ix_tasks_assigned_agent_id", "tasks", ("assigned_agent_id",))) in calls
    assert ("create_index", ("ix_agent_execution_log_task_id", "agent_execution_log", ("task_id",))) in calls
    assert (
        "create_foreign_key",
        ("fk_agent_execution_log_task_id_tasks", "agent_execution_log", "tasks", ("task_id",), ("id",)),
    ) in calls
