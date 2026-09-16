"""add supplier quotes table

Revision ID: 60efd4316cac
Revises: 10de07bea94d
Create Date: 2026-09-16 13:15:28.985720

Creates `supplier_quotes` (Fase 3, Agente 2 sourcing) with Row Level
Security enabled from birth, per ADR 0003 — unlike the 24 pre-existing
tables, this one never goes through a retroactive RLS-enabling
migration. See docs/architecture/adr-0003-rls-deny-by-default.md for
why ENABLE ROW LEVEL SECURITY is safe for the backend's `postgres` role
(table owner, bypasses RLS) and why the explicit deny policy is only
created when the Supabase-provisioned `anon`/`authenticated` roles
exist (skipped on a vanilla Postgres such as CI's ephemeral container).
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "60efd4316cac"
down_revision: str | Sequence[str] | None = "10de07bea94d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "supplier_quotes"
_POLICY_NAME = "deny_all_anon_authenticated"


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("product_id", sa.String(length=36), nullable=False),
        sa.Column("supplier_id", sa.String(length=36), nullable=False),
        sa.Column("analysis_type", sa.String(length=32), nullable=False),
        sa.Column("unit_price", sa.Float(), nullable=False),
        sa.Column("moq", sa.Integer(), nullable=False),
        sa.Column("lead_time_days", sa.Integer(), nullable=False),
        sa.Column("verified", sa.Boolean(), nullable=False),
        sa.Column("reliability_score", sa.Float(), nullable=False),
        sa.Column("logistics_cost_per_unit", sa.Float(), nullable=False),
        sa.Column("total_landed_cost_per_unit", sa.Float(), nullable=False),
        sa.Column("data", sa.JSON(), nullable=True),
        sa.Column("correlation_id", sa.String(length=36), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.ForeignKeyConstraint(["supplier_id"], ["suppliers.id"]),
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
