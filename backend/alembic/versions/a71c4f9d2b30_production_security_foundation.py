"""production security foundation

Milestone 29 (ADR 0007). Additive and reversible:

- users.subject: the `sub` of the access token that owns the account, so a
  verified identity resolves to a local user and therefore to a role.
- audit_log.actor_role / actor_source: what role the actor held and whether its
  identity was verified. Nullable because rows written before this migration
  predate verified identity and the trail is append-only.
- roles: the seven roles of the plan maestro, seeded idempotently.

Revision ID: a71c4f9d2b30
Revises: ebc8b88725e2
Create Date: 2026-09-25

"""

import datetime
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a71c4f9d2b30"
down_revision: str | Sequence[str] | None = "ebc8b88725e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLE_NAMES = ("OWNER", "ADMIN", "OPERATOR", "ANALYST", "REVIEWER", "VIEWER", "SYSTEM")


def upgrade() -> None:
    op.add_column("users", sa.Column("subject", sa.String(length=255), nullable=True))
    op.create_index("ix_users_subject", "users", ["subject"], unique=True)

    op.add_column("audit_log", sa.Column("actor_role", sa.String(length=50), nullable=True))
    op.add_column("audit_log", sa.Column("actor_source", sa.String(length=20), nullable=True))

    # Seeded here rather than at runtime: a deployment that has not applied its
    # migrations must not be able to grant roles.
    roles = sa.table(
        "roles",
        sa.column("id", sa.String),
        sa.column("name", sa.String),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    connection = op.get_bind()
    existing = {row[0] for row in connection.execute(sa.text("SELECT name FROM roles")).fetchall()}
    missing = [name for name in ROLE_NAMES if name not in existing]
    if missing:
        # A concrete timestamp, not sa.func.now(): bulk_insert binds these as
        # values, so a SQL function object would be sent as a parameter.
        now = datetime.datetime.now(datetime.UTC)
        op.bulk_insert(
            roles,
            [
                {"id": f"role-{name.lower()}", "name": name, "created_at": now, "updated_at": now}
                for name in missing
            ],
        )


def downgrade() -> None:
    op.get_bind().execute(
        sa.text("DELETE FROM roles WHERE id IN :ids").bindparams(
            sa.bindparam("ids", value=tuple(f"role-{name.lower()}" for name in ROLE_NAMES), expanding=True)
        )
    )
    op.drop_column("audit_log", "actor_source")
    op.drop_column("audit_log", "actor_role")
    op.drop_index("ix_users_subject", table_name="users")
    op.drop_column("users", "subject")
