"""action gate

Milestone 33 (ADR 0011). Ninguna tabla nueva: el gate decide en memoria y lo que
hay que persistir es a quién se le pide qué.

- pipeline_reviews gana `kind` (POST_HOC | ACTION_GATE), `step` y `action`. Las
  filas que ya existen son revisiones post-hoc del Milestone 14, así que se
  rellenan con POST_HOC: es lo que son, no un valor por defecto de conveniencia.
- pipeline_runs gana `requested_by_role`, el rol verificado de quien pidió la
  ejecución. Sin él, un worker que la ejecuta horas después no sabe en nombre de
  quién actúa, y el gate no puede consultar permisos.

Revision ID: b7e3d5c81f24
Revises: f4a1c7d9e2b8
Create Date: 2026-09-26

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b7e3d5c81f24"
down_revision: str | Sequence[str] | None = "f4a1c7d9e2b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("pipeline_reviews") as batch:
        batch.add_column(sa.Column("kind", sa.String(length=16), nullable=True))
        batch.add_column(sa.Column("step", sa.String(length=32), nullable=True))
        batch.add_column(sa.Column("action", sa.String(length=40), nullable=True))

    # Lo que hay hoy en la tabla son revisiones de ejecuciones ya terminadas.
    op.execute("UPDATE pipeline_reviews SET kind = 'POST_HOC' WHERE kind IS NULL")
    op.create_index("ix_pipeline_reviews_kind", "pipeline_reviews", ["kind"])

    with op.batch_alter_table("pipeline_runs") as batch:
        batch.add_column(sa.Column("requested_by_role", sa.String(length=32), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("pipeline_runs") as batch:
        batch.drop_column("requested_by_role")

    op.drop_index("ix_pipeline_reviews_kind", table_name="pipeline_reviews")
    with op.batch_alter_table("pipeline_reviews") as batch:
        batch.drop_column("action")
        batch.drop_column("step")
        batch.drop_column("kind")
