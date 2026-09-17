"""add pipeline review and kill switch tables

Revision ID: ebc8b88725e2
Revises: 075bc06fedad
Create Date: 2026-09-17 10:00:00.000000

Milestone 14 (IVA-33, ADR 0006): critical human controls over
PipelineOrchestrator (Milestone 12). `pipeline_reviews` gates risky runs
post-hoc (a human must approve/reject); `pipeline_kill_switch` gates new
runs pre-hoc (an operator can disable pipeline execution entirely). Both
RLS-enabled from birth, per ADR 0003. Also adds `pipeline_runs.needs_review`.
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ebc8b88725e2"
down_revision: str | Sequence[str] | None = "075bc06fedad"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_POLICY_NAME = "deny_all_anon_authenticated"


def _enable_rls(table: str) -> None:
    op.execute(
        f"""
        DO $$
        DECLARE
            has_anon boolean := EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon');
            has_authenticated boolean := EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated');
        BEGIN
            EXECUTE 'ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY';

            IF has_anon AND has_authenticated THEN
                EXECUTE (
                    'CREATE POLICY {_POLICY_NAME} ON public.{table} '
                    'AS PERMISSIVE FOR ALL TO anon, authenticated '
                    'USING (false) WITH CHECK (false)'
                );
            END IF;
        END $$;
        """
    )


def upgrade() -> None:
    op.add_column("pipeline_runs", sa.Column("needs_review", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_index("ix_pipeline_runs_needs_review", "pipeline_runs", ["needs_review"])

    op.create_table(
        "pipeline_reviews",
        sa.Column("pipeline_run_id", sa.String(length=36), nullable=False),
        sa.Column("reasons", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", sa.String(length=255), nullable=True),
        sa.Column("correlation_id", sa.String(length=36), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["pipeline_run_id"], ["pipeline_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_pipeline_reviews_pipeline_run_id", "pipeline_reviews", ["pipeline_run_id"])
    _enable_rls("pipeline_reviews")

    op.create_table(
        "pipeline_kill_switch",
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=True),
        sa.Column("updated_by", sa.String(length=255), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    _enable_rls("pipeline_kill_switch")


def downgrade() -> None:
    op.execute(f"DROP POLICY IF EXISTS {_POLICY_NAME} ON public.pipeline_kill_switch")
    op.drop_table("pipeline_kill_switch")

    op.execute(f"DROP POLICY IF EXISTS {_POLICY_NAME} ON public.pipeline_reviews")
    op.drop_index("ix_pipeline_reviews_pipeline_run_id", table_name="pipeline_reviews")
    op.drop_table("pipeline_reviews")

    op.drop_index("ix_pipeline_runs_needs_review", table_name="pipeline_runs")
    op.drop_column("pipeline_runs", "needs_review")
