"""economics by channel and currency

Milestone 40 (ADR 0018). Un análisis económico pasa a decir en qué canal, en qué
moneda y con qué conversión se calculó — y a poder decir que **no se pudo
calcular**, que es distinto de que saliera mal.

## Lo que se añade

La tabla `exchange_rates`, donde una persona declara el cambio que le aplicó el
banco: la única fuente de tipos de cambio que cuesta cero euros. La dirección va
en los nombres de las columnas (`1 base_currency = rate quote_currency`), porque
sin eso un 1,08 puede ser dólares por euro o euros por dólar y entre las dos
lecturas hay un 16 %.

Y trece columnas en `economic_analyses`. Las monetarias son `Numeric(12, 4)` y
no `Float`: dinero en coma flotante pierde céntimos, y cuatro decimales porque
un coste unitario de 0,0042 € existe. Las que ya estaban se quedan en `Float`;
migrar treinta revisiones es un milestone propio y la frontera está escrita en
`app/money/serialization.py`.

## Lo que se rellena, y lo que no

`margin_evaluability` y `cac_evaluability` se rellenan `evaluable` en las filas
existentes: eran evaluables con lo que se sabía entonces, y decir lo contrario
sería reescribir el pasado.

**No se rellenan el canal ni la moneda.** Se quedan en `NULL`, que significa
«nadie lo declaró» y no «vale para todos». Las filas anteriores a este milestone
se calcularon sin saber dónde se vendía ni en qué moneda estaba el coste — de
hecho, mezclándolas—, y ponerles ahora `own_web` y `EUR` sería afirmar dos cosas
que nadie afirmó.

`units_per_order` tampoco: un 1 rellenado aquí sería exactamente la suposición
silenciosa que este milestone quita de en medio.

## Bajar cuesta información

`margin_percent` vuelve a ser `NOT NULL`, y los análisis que no se pudieron
evaluar pasan a valer 0,0 — es decir, pasan a parecer productos con margen cero
en vez de productos sin evaluar. Es esta migración vista del revés, y hay un
test que lo dice en voz alta.

Revision ID: d8b4c1e70a29
Revises: c7d2f4a90b13
Create Date: 2026-09-29

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d8b4c1e70a29"
down_revision: str | Sequence[str] | None = "c7d2f4a90b13"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _analysis_columns() -> tuple[sa.Column, ...]:
    """Columnas nuevas de `economic_analyses`. Una función y no una constante
    porque un objeto `Column` se consume al añadirlo."""
    return (
        sa.Column("channel", sa.String(length=64), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("units_per_order", sa.Integer(), nullable=True),
        sa.Column("units_per_order_provenance", sa.String(length=32), nullable=True),
        sa.Column(
            "margin_evaluability",
            sa.String(length=24),
            nullable=False,
            server_default="evaluable",
        ),
        sa.Column(
            "cac_evaluability",
            sa.String(length=24),
            nullable=False,
            server_default="evaluable",
        ),
        sa.Column("missing_inputs", sa.JSON(), nullable=True),
        sa.Column("contribution_margin_per_unit", sa.Numeric(12, 4), nullable=True),
        sa.Column("contribution_margin_per_order", sa.Numeric(12, 4), nullable=True),
        sa.Column("allocated_fixed_cost_per_order", sa.Numeric(12, 4), nullable=True),
        sa.Column("max_breakeven_cac", sa.Numeric(12, 4), nullable=True),
        sa.Column("fx_conversions", sa.JSON(), nullable=True),
    )


def upgrade() -> None:
    op.create_table(
        "exchange_rates",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("base_currency", sa.String(length=3), nullable=False),
        sa.Column("quote_currency", sa.String(length=3), nullable=False),
        # `Numeric(18, 8)`: una tasa necesita más decimales que un importe, y es
        # la cifra por la que se multiplica todo lo demás.
        sa.Column("rate", sa.Numeric(18, 8), nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("source", sa.String(length=255), nullable=False),
        sa.Column("provenance", sa.String(length=32), nullable=False),
        sa.Column("declared_by", sa.String(length=255), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_exchange_rates_pair_date",
        "exchange_rates",
        ["base_currency", "quote_currency", "effective_date"],
    )
    op.create_index("ix_exchange_rates_effective_date", "exchange_rates", ["effective_date"])
    op.create_index("ix_exchange_rates_provenance", "exchange_rates", ["provenance"])

    for column in _analysis_columns():
        op.add_column("economic_analyses", column)

    op.create_index("ix_economic_analyses_channel", "economic_analyses", ["channel"])

    # `batch_alter_table` porque SQLite no sabe cambiar la nulabilidad con
    # ALTER: recrea la tabla. En PostgreSQL usa el ALTER directo.
    with op.batch_alter_table("economic_analyses") as batch:
        batch.alter_column("margin_percent", existing_type=sa.Float(), nullable=True)


def downgrade() -> None:
    # El esquema anterior no sabe representar «no se pudo evaluar», así que lo
    # no evaluado pasa a parecer margen cero. Bajar cuesta exactamente eso.
    op.get_bind().execute(
        sa.text("UPDATE economic_analyses SET margin_percent = 0 WHERE margin_percent IS NULL")
    )
    with op.batch_alter_table("economic_analyses") as batch:
        batch.alter_column("margin_percent", existing_type=sa.Float(), nullable=False)

    op.drop_index("ix_economic_analyses_channel", table_name="economic_analyses")
    for column in _analysis_columns():
        op.drop_column("economic_analyses", column.name)

    op.drop_index("ix_exchange_rates_provenance", table_name="exchange_rates")
    op.drop_index("ix_exchange_rates_effective_date", table_name="exchange_rates")
    op.drop_index("ix_exchange_rates_pair_date", table_name="exchange_rates")
    op.drop_table("exchange_rates")
