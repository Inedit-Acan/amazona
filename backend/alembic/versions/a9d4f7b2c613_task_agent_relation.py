"""task agent relation

Milestone 48, Commit 7. La relación TAREA ↔ AGENTE pasa a ser explícita y verificable: ASIGNACIÓN ≠ EJECUCIÓN.

## Qué hace

1. `tasks.assigned_agent_id` **deja de ser una clave ajena a `agents`**. La columna existía desde el esquema inicial
   y nunca se usó: la tabla `agents` no se puebla (los agentes viven en el REGISTRO del código, y hoy tiene 0
   filas), así que la clave ajena no admitía ningún id real. Que el agente exista lo exige `TaskAssignmentService`
   al escribir y lo vuelve a comprobar cada lectura contra el registro. Se añade un índice.
2. `agent_execution_log` gana, todas **nulas**: `task_id` (clave ajena a `tasks`: una ejecución referencia una
   tarea que existe), `assigned_agent_id` (la FOTO de la asignación vigente al ejecutar, sin clave ajena),
   `attempt`, `started_at`, `completed_at`. Índice en `task_id`.

## Qué NO hace

**No toca ninguna fila.** Lo anterior (las tareas y las ejecuciones de las misiones de octubre) queda exactamente como
estaba: sin asignación, sin `task_id`. Una asignación que nunca se hizo no se fabrica, y una ejecución no se vincula a
una tarea por coincidencia de agente, de capacidad o de correlación. La historia anterior se lee, sin escribirla,
desde el evento `task.completed` de la auditoría (actor = agente, recurso = tarea). Sin tablas nuevas: no hay RLS que
activar; las columnas heredan la de su tabla.

## SQLite (solo pruebas)

SQLite no puede quitar una clave ajena ni añadir una con `ALTER`: se recrea la tabla con `batch_alter_table`, dando
nombre a la clave ajena sin nombre del esquema inicial. En PostgreSQL son `ALTER` directos; la clave ajena se quita
por su nombre de siempre (`tasks_assigned_agent_id_fkey`) y con `IF EXISTS`.

## Bajar

Se **niega** si perdería información que no se puede reconstruir: alguna tarea con `assigned_agent_id` (la clave ajena
que se restauraría apunta a una tabla vacía y no admite el valor) o alguna ejecución con `task_id`, foto o intento.
Con todo nulo, restaura la forma anterior. Solo se prueba en local; **no se aplica a Supabase sin autorización**.

Revision ID: a9d4f7b2c613
Revises: b7e4a1c9d052
Create Date: 2026-10-20

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a9d4f7b2c613"
down_revision: str | Sequence[str] | None = "b7e4a1c9d052"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Nombre de la clave ajena del esquema inicial en PostgreSQL (el que le da por omisión: `<tabla>_<columna>_fkey`).
PG_TASK_AGENT_FK = "tasks_assigned_agent_id_fkey"
LOG_TASK_FK = "fk_agent_execution_log_task_id_tasks"
#: Para que SQLite, al recrear `tasks`, dé nombre a la clave ajena que el esquema inicial dejó sin él y se pueda quitar.
SQLITE_FK_NAMING = {"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"}
SQLITE_TASK_AGENT_FK = "fk_tasks_assigned_agent_id_agents"

NEW_LOG_COLUMNS = ("task_id", "assigned_agent_id", "attempt", "started_at", "completed_at")


def _dialect() -> str:
    return op.get_bind().dialect.name


def upgrade() -> None:
    if _dialect() == "postgresql":
        op.execute(f"ALTER TABLE tasks DROP CONSTRAINT IF EXISTS {PG_TASK_AGENT_FK}")
        op.create_index("ix_tasks_assigned_agent_id", "tasks", ["assigned_agent_id"])
        op.add_column("agent_execution_log", sa.Column("task_id", sa.String(length=36), nullable=True))
        op.add_column("agent_execution_log", sa.Column("assigned_agent_id", sa.String(length=36), nullable=True))
        op.add_column("agent_execution_log", sa.Column("attempt", sa.Integer(), nullable=True))
        op.add_column("agent_execution_log", sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))
        op.add_column("agent_execution_log", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
        op.create_foreign_key(LOG_TASK_FK, "agent_execution_log", "tasks", ["task_id"], ["id"])
        op.create_index("ix_agent_execution_log_task_id", "agent_execution_log", ["task_id"])
        return

    with op.batch_alter_table("tasks", naming_convention=SQLITE_FK_NAMING) as batch:
        batch.drop_constraint(SQLITE_TASK_AGENT_FK, type_="foreignkey")
        batch.create_index("ix_tasks_assigned_agent_id", ["assigned_agent_id"])
    with op.batch_alter_table("agent_execution_log") as batch:
        batch.add_column(sa.Column("task_id", sa.String(length=36), nullable=True))
        batch.add_column(sa.Column("assigned_agent_id", sa.String(length=36), nullable=True))
        batch.add_column(sa.Column("attempt", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_foreign_key(LOG_TASK_FK, "tasks", ["task_id"], ["id"])
        batch.create_index("ix_agent_execution_log_task_id", ["task_id"])


def _refuse_if_information_would_be_lost() -> None:
    bind = op.get_bind()
    assigned = bind.execute(sa.text("SELECT count(*) FROM tasks WHERE assigned_agent_id IS NOT NULL")).scalar()
    if assigned:
        raise RuntimeError(
            f"{assigned} task(s) have an assigned_agent_id: going down would restore a foreign key to the empty agents "
            "table that cannot hold those values, and would lose the assignments. Nothing was changed."
        )
    linked = bind.execute(
        sa.text(
            "SELECT count(*) FROM agent_execution_log"
            " WHERE task_id IS NOT NULL OR assigned_agent_id IS NOT NULL OR attempt IS NOT NULL"
        )
    ).scalar()
    if linked:
        raise RuntimeError(
            f"{linked} execution(s) carry a task link, an assignment snapshot or an attempt: going down would lose "
            "them. Nothing was changed."
        )


def downgrade() -> None:
    _refuse_if_information_would_be_lost()
    if _dialect() == "postgresql":
        op.drop_index("ix_agent_execution_log_task_id", table_name="agent_execution_log")
        op.drop_constraint(LOG_TASK_FK, "agent_execution_log", type_="foreignkey")
        for column in NEW_LOG_COLUMNS:
            op.drop_column("agent_execution_log", column)
        op.drop_index("ix_tasks_assigned_agent_id", table_name="tasks")
        op.create_foreign_key(PG_TASK_AGENT_FK, "tasks", "agents", ["assigned_agent_id"], ["id"])
        return

    with op.batch_alter_table("agent_execution_log") as batch:
        batch.drop_index("ix_agent_execution_log_task_id")
        batch.drop_constraint(LOG_TASK_FK, type_="foreignkey")
        for column in NEW_LOG_COLUMNS:
            batch.drop_column(column)
    with op.batch_alter_table("tasks") as batch:
        batch.drop_index("ix_tasks_assigned_agent_id")
        batch.create_foreign_key(SQLITE_TASK_AGENT_FK, "agents", ["assigned_agent_id"], ["id"])
