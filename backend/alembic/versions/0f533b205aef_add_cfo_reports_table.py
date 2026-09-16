"""add cfo reports table

Revision ID: 0f533b205aef
Revises: 833c46295739
Create Date: 2026-09-16 20:00:00.000000

Creates `cfo_reports` (Milestone 10, Agente CFO — catalog-wide financial
health, consolidating EconomicAnalysis + MarketingCampaign + BudgetEngine
reservations) with Row Level Security enabled from birth, per ADR 0003 —
same pattern as the 8 Fase 3 agents' tables. Unlike those tables, this one
has no product/market foreign key: it aggregates across the whole catalog
in a single run. See docs/architecture/adr-0003-rls-deny-by-default.md.
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0f533b205aef"
down_revision: str | Sequence[str] | None = "833c46295739"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "cfo_reports"
_POLICY_NAME = "deny_all_anon_authenticated"


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("financial_health_status", sa.String(length=16), nullable=False),
        sa.Column("recommendation", sa.String(length=16), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("data", sa.JSON(), nullable=True),
        sa.Column("correlation_id", sa.String(length=36), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
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
