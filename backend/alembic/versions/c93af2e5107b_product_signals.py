"""product signals

Milestone 34 (ADR 0012). Una tabla nueva y ninguna existente modificada.

`product_signals` guarda cada medición con su procedencia completa —los nueve
campos del plan maestro §8—: quién la produjo, de qué fuente, preguntando qué,
en qué mercado, cuándo, con qué método, con cuánta confianza, cómo volver al
dato crudo, y si es simulada.

Es aditivo: `product_analyses` sigue guardando el análisis y su score. Esto
guarda de qué está hecho.

Revision ID: c93af2e5107b
Revises: b7e3d5c81f24
Create Date: 2026-09-26

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c93af2e5107b"
down_revision: str | Sequence[str] | None = "b7e3d5c81f24"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "product_signals",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("product_id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=255), nullable=False),
        sa.Column("query", sa.String(length=255), nullable=False),
        sa.Column("market", sa.String(length=16), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("method", sa.Text(), nullable=False),
        sa.Column("raw_reference", sa.String(length=500), nullable=True),
        sa.Column("simulated", sa.Boolean(), nullable=False),
        sa.Column("correlation_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_product_signals_product_id", "product_signals", ["product_id"])
    op.create_index("ix_product_signals_kind", "product_signals", ["kind"])
    op.create_index("ix_product_signals_provider", "product_signals", ["provider"])
    op.create_index("ix_product_signals_simulated", "product_signals", ["simulated"])
    op.create_index("ix_product_signals_product_kind", "product_signals", ["product_id", "kind"])
    op.create_index("ix_product_signals_correlation", "product_signals", ["correlation_id"])

    # RLS deny-by-default en toda tabla pública, desde su propia migración
    # (ADR 0003). El backend entra con la clave de servicio y no le afecta.
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE product_signals ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE product_signals FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    for name in (
        "ix_product_signals_correlation",
        "ix_product_signals_product_kind",
        "ix_product_signals_simulated",
        "ix_product_signals_provider",
        "ix_product_signals_kind",
        "ix_product_signals_product_id",
    ):
        op.drop_index(name, table_name="product_signals")
    op.drop_table("product_signals")
