"""database identity guards

Hardening pre-M44 (ADR 0026). Lo que el código daba por único y la base de datos no garantizaba:

- `budgets.name`: un presupuesto por nombre;
- `budget_allocations.budget_id`: un saldo por presupuesto (medido en PostgreSQL: con 30 primeras reservas a la
  vez, 3 de 12 pruebas dejaron entre 2 y 4 filas, y cada comprobación de límite miraba la suya);
- `pipeline_kill_switch.name`: un interruptor por nombre;
- `financial_events`: una `reference` se **reserva** una vez y se **liquida** (compromete o libera) una vez. Dos
  liquidaciones de la misma reserva contarían el dinero dos veces;
- `pipeline_reviews`: a lo sumo una pregunta `PENDING` por paso (`ACTION_GATE`) y una revisión a posteriori
  `PENDING` por ejecución.

## Esta migración no toca datos

No borra, no fusiona y no «arregla» filas. Si ya hay duplicados, **se niega a continuar** antes de cambiar nada
(DDL transaccional en PostgreSQL) y dice cuáles son, para que una persona decida qué fila es la buena. Antes de
aplicarla a una base real, comprobar de solo lectura:

    SELECT name, count(*) FROM budgets GROUP BY name HAVING count(*) > 1;
    SELECT budget_id, count(*) FROM budget_allocations GROUP BY budget_id HAVING count(*) > 1;
    SELECT name, count(*) FROM pipeline_kill_switch GROUP BY name HAVING count(*) > 1;
    SELECT reference, count(*) FROM financial_events
      WHERE type = 'RESERVE' AND reference IS NOT NULL GROUP BY reference HAVING count(*) > 1;
    SELECT reference, count(*) FROM financial_events
      WHERE type IN ('COMMIT', 'RELEASE') AND reference IS NOT NULL GROUP BY reference HAVING count(*) > 1;
    SELECT pipeline_run_id, step, count(*) FROM pipeline_reviews
      WHERE kind = 'ACTION_GATE' AND status = 'PENDING' GROUP BY 1, 2 HAVING count(*) > 1;
    SELECT pipeline_run_id, count(*) FROM pipeline_reviews
      WHERE kind = 'POST_HOC' AND status = 'PENDING' GROUP BY 1 HAVING count(*) > 1;

Las siete deben devolver cero filas.

## RLS

No crea tablas: no hay nada que activar (el guardia `test_migration_rls_gap` sigue cubriendo la cadena).

## Bajar

Quita las restricciones y los índices y no toca ninguna fila. Tras bajar, la base vuelve a admitir duplicados.

Revision ID: e1b8d4a62f37
Revises: d7a3c5e91b24
Create Date: 2026-10-01

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e1b8d4a62f37"
down_revision: str | Sequence[str] | None = "d7a3c5e91b24"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: (qué se garantiza, consulta que devuelve las filas que lo incumplen)
DUPLICATE_CHECKS: tuple[tuple[str, str], ...] = (
    ("budgets.name", "SELECT name, count(*) FROM budgets GROUP BY name HAVING count(*) > 1"),
    (
        "budget_allocations.budget_id",
        "SELECT budget_id, count(*) FROM budget_allocations GROUP BY budget_id HAVING count(*) > 1",
    ),
    ("pipeline_kill_switch.name", "SELECT name, count(*) FROM pipeline_kill_switch GROUP BY name HAVING count(*) > 1"),
    (
        "financial_events: one RESERVE per reference",
        "SELECT reference, count(*) FROM financial_events WHERE type = 'RESERVE' AND reference IS NOT NULL "
        "GROUP BY reference HAVING count(*) > 1",
    ),
    (
        "financial_events: one COMMIT or RELEASE per reference",
        "SELECT reference, count(*) FROM financial_events WHERE type IN ('COMMIT', 'RELEASE') "
        "AND reference IS NOT NULL GROUP BY reference HAVING count(*) > 1",
    ),
    (
        "pipeline_reviews: one pending ACTION_GATE per step",
        "SELECT pipeline_run_id, step, count(*) FROM pipeline_reviews WHERE kind = 'ACTION_GATE' "
        "AND status = 'PENDING' GROUP BY pipeline_run_id, step HAVING count(*) > 1",
    ),
    (
        "pipeline_reviews: one pending POST_HOC per run",
        "SELECT pipeline_run_id, count(*) FROM pipeline_reviews WHERE kind = 'POST_HOC' "
        "AND status = 'PENDING' GROUP BY pipeline_run_id HAVING count(*) > 1",
    ),
)

_RESERVE = "type = 'RESERVE'"
_SETTLEMENT = "type IN ('COMMIT', 'RELEASE')"
_GATE = "kind = 'ACTION_GATE' AND status = 'PENDING'"
_POST_HOC = "kind = 'POST_HOC' AND status = 'PENDING'"


def _refuse_if_duplicates() -> None:
    bind = op.get_bind()
    found: list[str] = []
    for what, query in DUPLICATE_CHECKS:
        rows = bind.execute(sa.text(query)).fetchall()
        if rows:
            sample = ", ".join(str(tuple(row)) for row in rows[:5])
            found.append(f"  - {what}: {len(rows)} duplicated value(s), e.g. {sample}")
    if found:
        raise RuntimeError(
            "refusing to add the uniqueness guards: the database already has duplicates, and this migration never "
            "deletes or merges rows. Decide by hand which row is the right one, then run it again:\n" + "\n".join(found)
        )


def upgrade() -> None:
    _refuse_if_duplicates()
    with op.batch_alter_table("budgets") as batch:
        batch.create_unique_constraint("uq_budgets_name", ["name"])
    with op.batch_alter_table("budget_allocations") as batch:
        batch.create_unique_constraint("uq_budget_allocations_budget_id", ["budget_id"])
    with op.batch_alter_table("pipeline_kill_switch") as batch:
        batch.create_unique_constraint("uq_pipeline_kill_switch_name", ["name"])
    op.create_index(
        "uq_financial_events_one_reserve_per_reference",
        "financial_events",
        ["reference"],
        unique=True,
        postgresql_where=sa.text(_RESERVE),
        sqlite_where=sa.text(_RESERVE),
    )
    op.create_index(
        "uq_financial_events_one_settlement_per_reference",
        "financial_events",
        ["reference"],
        unique=True,
        postgresql_where=sa.text(_SETTLEMENT),
        sqlite_where=sa.text(_SETTLEMENT),
    )
    op.create_index(
        "uq_pipeline_reviews_one_pending_gate_per_step",
        "pipeline_reviews",
        ["pipeline_run_id", "step"],
        unique=True,
        postgresql_where=sa.text(_GATE),
        sqlite_where=sa.text(_GATE),
    )
    op.create_index(
        "uq_pipeline_reviews_one_pending_post_hoc_per_run",
        "pipeline_reviews",
        ["pipeline_run_id"],
        unique=True,
        postgresql_where=sa.text(_POST_HOC),
        sqlite_where=sa.text(_POST_HOC),
    )


def downgrade() -> None:
    op.drop_index("uq_pipeline_reviews_one_pending_post_hoc_per_run", table_name="pipeline_reviews")
    op.drop_index("uq_pipeline_reviews_one_pending_gate_per_step", table_name="pipeline_reviews")
    op.drop_index("uq_financial_events_one_settlement_per_reference", table_name="financial_events")
    op.drop_index("uq_financial_events_one_reserve_per_reference", table_name="financial_events")
    with op.batch_alter_table("pipeline_kill_switch") as batch:
        batch.drop_constraint("uq_pipeline_kill_switch_name", type_="unique")
    with op.batch_alter_table("budget_allocations") as batch:
        batch.drop_constraint("uq_budget_allocations_budget_id", type_="unique")
    with op.batch_alter_table("budgets") as batch:
        batch.drop_constraint("uq_budgets_name", type_="unique")
