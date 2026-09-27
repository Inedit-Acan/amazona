"""signal evidence and comparisons

Milestone 35 (ADR 0013). Dos tablas nuevas y ninguna existente modificada.

- product_signal_observations: las medidas mensuales que componen una señal. En
  filas y no en un JSON por el mismo motivo que los pasos del pipeline en el
  Milestone 32: es consultable, y en un blob estaría escondido.
- research_comparisons: el informe de qué dice cada proveedor sobre la misma
  pregunta. Aquí el resumen sí va en JSON, porque un informe se lee entero.

Revision ID: a5f1c62d87e4
Revises: c93af2e5107b
Create Date: 2026-09-27

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a5f1c62d87e4"
down_revision: str | Sequence[str] | None = "c93af2e5107b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "product_signal_observations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("signal_id", sa.String(length=36), nullable=False),
        sa.Column("period", sa.String(length=16), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["signal_id"], ["product_signals.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_product_signal_observations_signal_id", "product_signal_observations", ["signal_id"]
    )
    op.create_index(
        "ix_signal_observations_signal_period", "product_signal_observations", ["signal_id", "period"]
    )

    op.create_table(
        "research_comparisons",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("market", sa.String(length=16), nullable=False),
        sa.Column("baseline_provider", sa.String(length=64), nullable=False),
        sa.Column("candidate_provider", sa.String(length=64), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.Column("correlation_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_research_comparisons_category", "research_comparisons", ["category"])
    op.create_index(
        "ix_research_comparisons_correlation_id", "research_comparisons", ["correlation_id"]
    )

    # RLS deny-by-default en toda tabla pública, desde su propia migración
    # (ADR 0003). El backend entra con la clave de servicio y no le afecta.
    if op.get_bind().dialect.name == "postgresql":
        for table in ("product_signal_observations", "research_comparisons"):
            op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_index("ix_research_comparisons_correlation_id", table_name="research_comparisons")
    op.drop_index("ix_research_comparisons_category", table_name="research_comparisons")
    op.drop_table("research_comparisons")

    op.drop_index("ix_signal_observations_signal_period", table_name="product_signal_observations")
    op.drop_index(
        "ix_product_signal_observations_signal_id", table_name="product_signal_observations"
    )
    op.drop_table("product_signal_observations")
