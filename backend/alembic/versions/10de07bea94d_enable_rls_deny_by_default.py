"""enable rls deny by default

Revision ID: 10de07bea94d
Revises: c1ff9cbdd4d3
Create Date: 2026-09-16 12:52:12.599707

Enables Row Level Security on every table in the public schema and adds
an explicit deny-all policy for Supabase's `anon`/`authenticated` roles.
See docs/architecture/adr-0003-rls-deny-by-default.md.

The backend connects as the `postgres` role, which owns every table
here and therefore bypasses RLS by default (we never set FORCE ROW
LEVEL SECURITY) — this migration changes nothing about how the backend
itself reads or writes data.

`anon`/`authenticated` are Supabase-provisioned roles that don't exist
on a vanilla PostgreSQL instance (e.g. CI's ephemeral service
container), so policy creation is skipped there — ENABLE ROW LEVEL
SECURITY with zero policies already denies every non-owner role
regardless of its name, so the deny-by-default outcome holds either
way; only the explicit, self-documenting policy is Supabase-specific.
"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "10de07bea94d"
down_revision: str | Sequence[str] | None = "c1ff9cbdd4d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = [
    "alembic_version",
    "agents",
    "audit_log",
    "budgets",
    "events",
    "incidents",
    "objectives",
    "policies",
    "agent_capabilities",
    "budget_allocations",
    "financial_events",
    "projects",
    "decisions",
    "tasks",
    "approvals",
    "decision_evidence",
    "task_dependencies",
    "products",
    "suppliers",
    "product_analyses",
    "memory_records",
    "roles",
    "users",
    "agent_execution_log",
]

_POLICY_NAME = "deny_all_anon_authenticated"

_TABLES_ARRAY_SQL = ", ".join(f"'{t}'" for t in _TABLES)


def upgrade() -> None:
    op.execute(
        f"""
        DO $$
        DECLARE
            tbl text;
            tables text[] := ARRAY[{_TABLES_ARRAY_SQL}];
            has_anon boolean := EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon');
            has_authenticated boolean := EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated');
        BEGIN
            FOREACH tbl IN ARRAY tables LOOP
                EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', tbl);

                IF has_anon AND has_authenticated THEN
                    EXECUTE format(
                        'CREATE POLICY {_POLICY_NAME} ON public.%I '
                        'AS PERMISSIVE FOR ALL TO anon, authenticated '
                        'USING (false) WITH CHECK (false)',
                        tbl
                    );
                END IF;
            END LOOP;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        DO $$
        DECLARE
            tbl text;
            tables text[] := ARRAY[{_TABLES_ARRAY_SQL}];
        BEGIN
            FOREACH tbl IN ARRAY tables LOOP
                EXECUTE format('DROP POLICY IF EXISTS {_POLICY_NAME} ON public.%I', tbl);
                EXECUTE format('ALTER TABLE public.%I DISABLE ROW LEVEL SECURITY', tbl);
            END LOOP;
        END $$;
        """
    )
