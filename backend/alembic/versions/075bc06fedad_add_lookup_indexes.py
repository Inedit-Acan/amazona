"""add lookup indexes

Revision ID: 075bc06fedad
Revises: 81219be53fb3
Create Date: 2026-09-17 09:00:00.000000

Milestone 13 (IVA-32): every "latest row for this product" query
(`.filter_by(product_id=...).order_by(created_at.desc()).first()`, used
throughout every Fase 3 service) and `GET /api/audit?correlation_id=`
were full table scans — none of the 12 domain tables had any index
beyond their primary key. Purely additive: no column/behavior changes.
"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "075bc06fedad"
down_revision: str | Sequence[str] | None = "81219be53fb3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PRODUCT_ID_TABLES = [
    "product_analyses",
    "supplier_quotes",
    "economic_analyses",
    "legal_analyses",
    "storefronts",
    "marketplace_listings",
    "marketing_campaigns",
    "operations_records",
    "pipeline_runs",
]


def upgrade() -> None:
    for table in _PRODUCT_ID_TABLES:
        op.create_index(f"ix_{table}_product_id", table, ["product_id"])
    op.create_index("ix_audit_log_correlation_id", "audit_log", ["correlation_id"])


def downgrade() -> None:
    op.drop_index("ix_audit_log_correlation_id", table_name="audit_log")
    for table in _PRODUCT_ID_TABLES:
        op.drop_index(f"ix_{table}_product_id", table_name=table)
