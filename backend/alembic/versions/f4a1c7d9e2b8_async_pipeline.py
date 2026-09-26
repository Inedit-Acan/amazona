"""async pipeline

Milestone 32 (ADR 0010). El pipeline pasa a ejecutarse en trabajos, con cada paso
persistido:

- pipeline_steps: un paso por fila, con su estado de ejecución, su
  correlation_id, la fila que produjo y lo que expone del negocio.
- pipeline_step_attempts: cada pasada por un paso, con el trabajo que lo intentó
  y su error (el `PipelineAttempt` del plan maestro §21).
- pipeline_runs: gana `job_id` (el trabajo que la ejecuta) y `request` (los
  parámetros de negocio, sin los cuales no se puede reanudar), y **pierde** el
  JSON `steps`, que pasa a ser las filas de arriba.

La columna `steps` no se borra sin más: se convierte primero. Cada clave del JSON
existente se escribe como una fila COMPLETED con su ordinal, su correlation_id y
su detalle, y el `downgrade` reconstruye el JSON a partir de las filas. Ninguna
ejecución ya registrada pierde información en ninguno de los dos sentidos.

Revision ID: f4a1c7d9e2b8
Revises: c8e2b17a4f93
Create Date: 2026-09-26

"""

import json
import uuid
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f4a1c7d9e2b8"
down_revision: str | Sequence[str] | None = "c8e2b17a4f93"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: El mismo orden que `app/pipeline/schemas.py::STEP_ORDER`. Se repite aquí a
#: propósito: una migración no debe cambiar de comportamiento porque el código de
#: la aplicación evolucione después.
STEP_ORDER: tuple[str, ...] = (
    "research",
    "sourcing",
    "economics",
    "legal",
    "ecommerce",
    "marketplace",
    "marketing",
    "operations",
    "cfo",
)

#: Claves del JSON que tienen columna propia en la tabla nueva; el resto del
#: diccionario es el `detail` del paso.
_OWN_COLUMNS = ("correlation_id", "entity_id", "step_status", "attempt", "error")


def _new_id() -> str:
    return str(uuid.uuid4())


def upgrade() -> None:
    op.create_table(
        "pipeline_steps",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("pipeline_run_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=32), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("correlation_id", sa.String(length=36), nullable=True),
        sa.Column("entity_id", sa.String(length=36), nullable=True),
        sa.Column("detail", sa.JSON(), nullable=True),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("error", sa.String(length=2000), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["pipeline_run_id"], ["pipeline_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("pipeline_run_id", "name", name="uq_pipeline_steps_run_name"),
    )
    op.create_index("ix_pipeline_steps_pipeline_run_id", "pipeline_steps", ["pipeline_run_id"])
    op.create_index("ix_pipeline_steps_status", "pipeline_steps", ["status"])
    op.create_index("ix_pipeline_steps_run_ordinal", "pipeline_steps", ["pipeline_run_id", "ordinal"])

    op.create_table(
        "pipeline_step_attempts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("pipeline_step_id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=True),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error", sa.String(length=2000), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["pipeline_step_id"], ["pipeline_steps.id"]),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_pipeline_step_attempts_pipeline_step_id", "pipeline_step_attempts", ["pipeline_step_id"])

    with op.batch_alter_table("pipeline_runs") as batch:
        batch.add_column(sa.Column("job_id", sa.String(length=36), nullable=True))
        batch.add_column(sa.Column("request", sa.JSON(), nullable=True))
    op.create_index("ix_pipeline_runs_job_id", "pipeline_runs", ["job_id"])

    _migrate_steps_into_rows()
    _backfill_request()

    # Ahora sí: el JSON ya está en filas y las filas son la única verdad. Tener
    # las dos cosas a la vez es la forma más segura de que se desincronicen.
    with op.batch_alter_table("pipeline_runs") as batch:
        batch.drop_column("steps")

    if op.get_bind().dialect.name == "postgresql":
        # RLS deny-by-default en toda tabla pública, desde su propia migración
        # (ADR 0003). El backend entra con la clave de servicio y no le afecta.
        for table in ("pipeline_steps", "pipeline_step_attempts"):
            op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def _migrate_steps_into_rows() -> None:
    """Convierte el JSON `pipeline_runs.steps` de cada ejecución ya registrada en
    filas de `pipeline_steps`. Lo que había eran ejecuciones terminadas —el JSON
    se escribía al final—, así que sus pasos quedan COMPLETED con un intento."""
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, steps, status, created_at FROM pipeline_runs")).fetchall()
    insert = sa.text(
        "INSERT INTO pipeline_steps (id, pipeline_run_id, name, ordinal, status, correlation_id,"
        " entity_id, detail, attempt, error, started_at, finished_at, created_at, updated_at)"
        " VALUES (:id, :run_id, :name, :ordinal, :status, :correlation_id, :entity_id, :detail,"
        " :attempt, NULL, NULL, NULL, :created_at, :updated_at)"
    ).bindparams(sa.bindparam("detail", type_=sa.JSON()))

    for run_id, steps, run_status, created_at in rows:
        payload = steps
        if isinstance(payload, str):
            payload = json.loads(payload or "{}")
        if not isinstance(payload, dict):
            continue

        for name, entry in payload.items():
            entry = entry if isinstance(entry, dict) else {}
            detail = {key: value for key, value in entry.items() if key not in _OWN_COLUMNS}
            ordinal = STEP_ORDER.index(name) if name in STEP_ORDER else len(STEP_ORDER)
            # Una ejecución PARTIAL se paró en su último paso registrado: ese es
            # el que no pudo entregar nada, y así queda reanudable.
            last = ordinal == max(
                (STEP_ORDER.index(k) if k in STEP_ORDER else len(STEP_ORDER)) for k in payload
            )
            status = "FAILED" if (run_status == "PARTIAL" and last) else "COMPLETED"
            bind.execute(
                insert,
                {
                    "id": _new_id(),
                    "run_id": run_id,
                    "name": name,
                    "ordinal": ordinal,
                    "status": status,
                    "correlation_id": entry.get("correlation_id"),
                    "entity_id": entry.get("entity_id"),
                    "detail": detail,
                    "attempt": 1,
                    "created_at": created_at,
                    "updated_at": created_at,
                },
            )

        # Los pasos que esa ejecución nunca llegó a registrar existen igual, para
        # que la ejecución tenga sus nueve filas y se pueda reanudar.
        missing = [name for name in STEP_ORDER if name not in payload]
        for name in missing:
            bind.execute(
                insert,
                {
                    "id": _new_id(),
                    "run_id": run_id,
                    "name": name,
                    "ordinal": STEP_ORDER.index(name),
                    "status": "SKIPPED",
                    "correlation_id": None,
                    "entity_id": None,
                    "detail": None,
                    "attempt": 0,
                    "created_at": created_at,
                    "updated_at": created_at,
                },
            )


def _backfill_request() -> None:
    """Las ejecuciones anteriores a este milestone no guardaron sus parámetros.
    Se rellena lo que sí consta en columnas propias —categoría y mercado— y nada
    más: inventar un precio de venta o una región de destino sería peor que
    admitir que no están, y la aplicación rechaza reanudarlas diciéndolo."""
    bind = op.get_bind()
    update = sa.text("UPDATE pipeline_runs SET request = :request WHERE id = :id").bindparams(
        sa.bindparam("request", type_=sa.JSON())
    )
    rows = bind.execute(sa.text("SELECT id, category, market FROM pipeline_runs")).fetchall()
    for run_id, category, market in rows:
        bind.execute(update, {"id": run_id, "request": {"category": category, "market": market}})


def downgrade() -> None:
    with op.batch_alter_table("pipeline_runs") as batch:
        batch.add_column(sa.Column("steps", sa.JSON(), nullable=True))

    _restore_steps_json()

    op.drop_index("ix_pipeline_runs_job_id", table_name="pipeline_runs")
    with op.batch_alter_table("pipeline_runs") as batch:
        batch.drop_column("request")
        batch.drop_column("job_id")

    op.drop_index("ix_pipeline_step_attempts_pipeline_step_id", table_name="pipeline_step_attempts")
    op.drop_table("pipeline_step_attempts")
    for name in ("ix_pipeline_steps_run_ordinal", "ix_pipeline_steps_status", "ix_pipeline_steps_pipeline_run_id"):
        op.drop_index(name, table_name="pipeline_steps")
    op.drop_table("pipeline_steps")


def _restore_steps_json() -> None:
    """Reconstruye el JSON a partir de las filas, para que bajar tampoco pierda
    nada. Los pasos que nunca se ejecutaron no entran: el JSON antiguo solo
    contenía los que habían producido algo."""
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT pipeline_run_id, name, ordinal, status, correlation_id, entity_id, detail"
            " FROM pipeline_steps ORDER BY pipeline_run_id, ordinal"
        )
    ).fetchall()

    grouped: dict[str, dict] = {}
    for run_id, name, _ordinal, status, correlation_id, entity_id, detail in rows:
        if status in ("PENDING", "SKIPPED"):
            continue
        parsed = json.loads(detail) if isinstance(detail, str) else (detail or {})
        entry: dict = {"correlation_id": correlation_id}
        if entity_id is not None:
            entry["entity_id"] = entity_id
        entry.update(parsed if isinstance(parsed, dict) else {})
        grouped.setdefault(run_id, {})[name] = entry

    update = sa.text("UPDATE pipeline_runs SET steps = :steps WHERE id = :id").bindparams(
        sa.bindparam("steps", type_=sa.JSON())
    )
    for run_id, steps in grouped.items():
        bind.execute(update, {"id": run_id, "steps": steps})
    # Una ejecución sin ningún paso registrable se queda con un JSON vacío, no
    # con NULL: la columna original era NOT NULL en el modelo.
    bind.execute(
        sa.text("UPDATE pipeline_runs SET steps = :empty WHERE steps IS NULL").bindparams(
            sa.bindparam("empty", value={}, type_=sa.JSON())
        )
    )
