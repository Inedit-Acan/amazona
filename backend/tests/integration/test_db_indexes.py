"""Milestone 13 (IVA-32): every "latest row for this product" query and
GET /api/audit?correlation_id= were full table scans — no model had an
index beyond its primary key. This locks in that the fix stays in place:
if a future change removes `index=True`, this test catches it without
needing a real database."""

import app.db.models  # noqa: F401 — populates Base.metadata with every table
from app.db.base import Base

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


def _has_index_on(table_name: str, column_name: str) -> bool:
    table = Base.metadata.tables[table_name]
    column = table.c[column_name]
    return column.index is True or any(column in index.columns.values() for index in table.indexes)


def test_every_product_id_column_used_for_latest_row_lookups_is_indexed():
    for table_name in _PRODUCT_ID_TABLES:
        assert _has_index_on(table_name, "product_id"), f"{table_name}.product_id has no index"


def test_audit_log_correlation_id_is_indexed():
    assert _has_index_on("audit_log", "correlation_id")
