"""index of the revenue ledger reads

Milestone 45 (ADR 0030, lecturas de agregados). Un índice **aditivo** sobre `revenue_ledger_entries`:
`(occurred_at, id)`, y en PostgreSQL con `INCLUDE (currency, classification, kind, amount)`.

Por qué: las lecturas de solo lectura (resumen, serie y página de entradas) filtran por el instante del hecho
(`occurred_at`) y paginan con un cursor `(occurred_at, id)`. Medido en PostgreSQL local sobre 990 000 entradas
(404 MB con sus índices), con consultas idénticas:

| Consulta | Sin índice | Con este índice |
|---|---|---|
| primera página (100) | 140 ms | ~1 ms |
| página profunda por cursor | 205-454 ms | ~1 ms |
| resumen de 30 días | 126 ms | 12 ms |
| serie diaria de 30 días | 135 ms | 31 ms |

El índice ocupa 72 MB frente a 119 MB de la tabla. La tabla es append-only: el coste de escritura es el de una
inserción más en un índice. No toca datos ni otras tablas; no hay retrorrelleno.

## Bajar

Quita el índice. Solo metadato de acceso: las entradas y los hechos de pago no cambian.

Revision ID: e5a1d7c93b04
Revises: c4e8b1d9a273
Create Date: 2026-10-03

"""

from collections.abc import Sequence

from alembic import op

revision: str = "e5a1d7c93b04"
down_revision: str | Sequence[str] | None = "c4e8b1d9a273"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "revenue_ledger_entries"
INDEX = "ix_revenue_entries_occurred_at"


def upgrade() -> None:
    op.create_index(
        INDEX,
        TABLE,
        ["occurred_at", "id"],
        postgresql_include=["currency", "classification", "kind", "amount"],
    )


def downgrade() -> None:
    op.drop_index(INDEX, table_name=TABLE)
