"""external api costs

Milestone 37 (plan maestro §25). Una tabla nueva y ninguna existente modificada.

El §25 lo pide literalmente y **antes** de introducir LLM o APIs comerciales:
`provider, operation, units, estimated_cost, actual_cost, currency,
correlation_id`. Están los siete, más `unit` (qué se cuenta), `outcome` y
`denied_reason` — porque **una denegación también se anota**: es la fila que
explica por qué una investigación volvió sin señales, y sin ella el sistema
parecería roto en vez de prudente.

En filas y no en un contador agregado por el mismo motivo que los pasos del
pipeline en el Milestone 32 y las observaciones en el 35: se puede preguntar «¿qué
gastó esta ejecución?» y «¿cuánto llevamos hoy con este proveedor?».

Revision ID: f3d7a02c9e51
Revises: e2c4a91b7d38
Create Date: 2026-09-28

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f3d7a02c9e51"
down_revision: str | Sequence[str] | None = "e2c4a91b7d38"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "external_api_costs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("operation", sa.String(length=64), nullable=False),
        sa.Column("units", sa.Integer(), nullable=False),
        sa.Column("unit", sa.String(length=16), nullable=False),
        sa.Column("estimated_cost", sa.Float(), nullable=False),
        # Nulo **no es cero**: es que el proveedor todavía no ha dicho lo que
        # cobró. La misma distinción que sostiene todo lo demás desde el M34.
        sa.Column("actual_cost", sa.Float(), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("denied_reason", sa.Text(), nullable=True),
        sa.Column("correlation_id", sa.String(length=36), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_external_api_costs_provider", "external_api_costs", ["provider"])
    op.create_index("ix_external_api_costs_outcome", "external_api_costs", ["outcome"])
    op.create_index(
        "ix_external_api_costs_provider_day", "external_api_costs", ["provider", "observed_at"]
    )
    op.create_index(
        "ix_external_api_costs_correlation", "external_api_costs", ["correlation_id"]
    )

    # RLS deny-by-default en toda tabla pública, desde su propia migración
    # (ADR 0003). El backend entra con la clave de servicio y no le afecta.
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE external_api_costs ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE external_api_costs FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_index("ix_external_api_costs_correlation", table_name="external_api_costs")
    op.drop_index("ix_external_api_costs_provider_day", table_name="external_api_costs")
    op.drop_index("ix_external_api_costs_outcome", table_name="external_api_costs")
    op.drop_index("ix_external_api_costs_provider", table_name="external_api_costs")
    op.drop_table("external_api_costs")
