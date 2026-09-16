"""add economic analyses table

Revision ID: 5264d502182d
Revises: 60efd4316cac
Create Date: 2026-09-16 14:00:00.000000

Creates `economic_analyses` (Fase 3, Agente 3 economic/risk analysis)
with Row Level Security enabled from birth, per ADR 0003 — same pattern
as `supplier_quotes` (60efd4316cac). See
docs/architecture/adr-0003-rls-deny-by-default.md.
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5264d502182d"
down_revision: str | Sequence[str] | None = "60efd4316cac"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "economic_analyses"
_POLICY_NAME = "deny_all_anon_authenticated"


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("product_id", sa.String(length=36), nullable=False),
        sa.Column("supplier_quote_id", sa.String(length=36), nullable=False),
        sa.Column("analysis_type", sa.String(length=32), nullable=False),
        sa.Column("sale_price", sa.Float(), nullable=False),
        sa.Column("monthly_fixed_costs", sa.Float(), nullable=False),
        sa.Column("margin_percent", sa.Float(), nullable=False),
        sa.Column("recommendation", sa.String(length=16), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("data", sa.JSON(), nullable=True),
        sa.Column("correlation_id", sa.String(length=36), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.ForeignKeyConstraint(["supplier_quote_id"], ["supplier_quotes.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.execute(
        f"""
        DO $$
        DECLARE
            has_anon boolean := EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon');
            has_authenticated boolean := EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated');
        BEGIN
            EXECUTE 'ALTER TABLE public.{_TABLE} ENABLE ROW LEVEL SECURITY';

            IF has_anon AND has_authenticated THEN
                EXECUTE (
                    'CREATE POLICY {_POLICY_NAME} ON public.{_TABLE} '
                    'AS PERMISSIVE FOR ALL TO anon, authenticated '
                    'USING (false) WITH CHECK (false)'
                );
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute(f"DROP POLICY IF EXISTS {_POLICY_NAME} ON public.{_TABLE}")
    op.drop_table(_TABLE)
