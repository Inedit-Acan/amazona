"""ceo chat

Milestone 52. La conversación escrita con el CEO: tres tablas NUEVAS y aditivas.

- `ceo_conversations`: quién conversa (`owner_subject`, el `sub` verificado) y un título opcional.
- `ceo_messages`: `user`, `assistant`, `tool` y `system_internal`, en orden (`seq`, único por conversación), con el
  contenido, los datos
  estructurados (la salida de una herramienta), y el uso del modelo (proveedor, modelo, versión del prompt, tokens,
  coste estimado y su categoría).
- `ceo_action_proposals`: lo que el CEO PROPONE (tipo de acción, objetivo, parámetros, efectos estimados, riesgo, scope
  de idempotencia) y su estado:
  `PROPOSED`, `EXECUTING`, `EXECUTED`, `FAILED` o `REJECTED`. Proponer no ejecuta.

## Qué NO hace

No toca ninguna fila existente, no añade columnas a ninguna tabla existente y no mezcla la memoria conversacional con
`memory_records`.

## RLS desde su propia migración

Con el patrón de la ADR 0003: `ENABLE ROW LEVEL SECURITY` y, solo en Supabase, la política
`deny_all_anon_authenticated`. Sin `FORCE`: el backend
es el dueño.

## Bajar

Es aditiva: bajar elimina las tres tablas y lo que hubiera en ellas (hay que exportarlas antes si importan).

Revision ID: c7a3f1d8e204
Revises: a9d4f7b2c613
Create Date: 2026-10-26

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c7a3f1d8e204"
down_revision: str | Sequence[str] | None = "a9d4f7b2c613"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("ceo_conversations", "ceo_messages", "ceo_action_proposals")

MESSAGE_ROLES = ("user", "assistant", "tool", "system_internal")
ACTION_TYPES = (
    "create_mission",
    "retry_task",
    "reassign_task",
    "resume_mission",
    "approve_approval",
    "reject_approval",
)
PROPOSAL_STATUSES = ("PROPOSED", "EXECUTING", "EXECUTED", "FAILED", "REJECTED")
RISK_LEVELS = ("low", "medium", "high")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


def upgrade() -> None:
    op.create_table(
        "ceo_conversations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_subject", sa.String(255), nullable=False),
        sa.Column("title", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_ceo_conversations_owner_subject", "ceo_conversations", ["owner_subject"])

    op.create_table(
        "ceo_messages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("conversation_id", sa.String(36), sa.ForeignKey("ceo_conversations.id"), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("structured", sa.JSON(), nullable=True),
        sa.Column("provider", sa.String(50), nullable=True),
        sa.Column("model", sa.String(100), nullable=True),
        sa.Column("prompt_version", sa.String(50), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("estimated_cost_usd", sa.Numeric(12, 6), nullable=True),
        sa.Column("external_cost_category", sa.String(40), nullable=True),
        sa.Column("correlation_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("conversation_id", "seq", name="uq_ceo_messages_conversation_seq"),
        sa.CheckConstraint(_in("role", MESSAGE_ROLES), name="ck_ceo_messages_role"),
    )
    op.create_index("ix_ceo_messages_conversation_id", "ceo_messages", ["conversation_id"])

    op.create_table(
        "ceo_action_proposals",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("conversation_id", sa.String(36), sa.ForeignKey("ceo_conversations.id"), nullable=False),
        sa.Column("message_id", sa.String(36), sa.ForeignKey("ceo_messages.id"), nullable=True),
        sa.Column("action_type", sa.String(40), nullable=False),
        sa.Column("target", sa.JSON(), nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("estimated_effects", sa.JSON(), nullable=False),
        sa.Column("risk_level", sa.String(10), nullable=False),
        sa.Column("requires_confirmation", sa.Boolean(), nullable=False),
        sa.Column("idempotency_scope", sa.String(60), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("resolved_by", sa.String(255), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("execution_result", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("result_message_id", sa.String(36), sa.ForeignKey("ceo_messages.id"), nullable=True),
        sa.Column("correlation_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(_in("action_type", ACTION_TYPES), name="ck_ceo_action_proposals_type"),
        sa.CheckConstraint(_in("status", PROPOSAL_STATUSES), name="ck_ceo_action_proposals_status"),
        sa.CheckConstraint(_in("risk_level", RISK_LEVELS), name="ck_ceo_action_proposals_risk"),
    )
    op.create_index("ix_ceo_action_proposals_conversation_id", "ceo_action_proposals", ["conversation_id"])

    _enable_rls()


def _enable_rls() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    with_policy = (
        bind.execute(sa.text("SELECT count(*) FROM pg_roles WHERE rolname IN ('anon', 'authenticated')")).scalar() == 2
    )
    for table in TABLES:
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
        if with_policy:
            op.execute(
                f"CREATE POLICY deny_all_anon_authenticated ON public.{table} "
                "AS PERMISSIVE FOR ALL TO anon, authenticated USING (false) WITH CHECK (false)"
            )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        for table in reversed(TABLES):
            op.execute(f"DROP POLICY IF EXISTS deny_all_anon_authenticated ON public.{table}")
    op.drop_index("ix_ceo_action_proposals_conversation_id", table_name="ceo_action_proposals")
    op.drop_table("ceo_action_proposals")
    op.drop_index("ix_ceo_messages_conversation_id", table_name="ceo_messages")
    op.drop_table("ceo_messages")
    op.drop_index("ix_ceo_conversations_owner_subject", table_name="ceo_conversations")
    op.drop_table("ceo_conversations")
