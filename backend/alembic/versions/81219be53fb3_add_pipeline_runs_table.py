"""add pipeline runs table

Revision ID: 81219be53fb3
Revises: 0f533b205aef
Create Date: 2026-09-16 21:00:00.000000

Creates `pipeline_runs` (Milestone 12, ADR 0005 — the PipelineOrchestrator
that chains the 9 Fase 3 steps, research through CFO, in one invocation)
with Row Level Security enabled from birth, per ADR 0003. See
docs/architecture/adr-0005-fase-3-pipeline-orchestrator.md.
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "81219be53fb3"
down_revision: str | Sequence[str] | None = "0f533b205aef"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "pipeline_runs"
_POLICY_NAME = "deny_all_anon_authenticated"


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("product_id", sa.String(length=36), nullable=True),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("market", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("failed_step", sa.String(length=32), nullable=True),
        sa.Column("steps", sa.JSON(), nullable=False),
        sa.Column("correlation_id", sa.String(length=36), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
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
