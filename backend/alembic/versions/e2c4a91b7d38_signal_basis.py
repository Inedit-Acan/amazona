"""signal basis

Milestone 37 (ADR 0015). Sustituye el booleano `simulated` de `product_signals`
por `basis`, que distingue tres cosas donde antes había dos.

`simulated` juntaba un número que una fuente **observó** y uno que una fuente
**modeló**: las dos vienen del mundo y no valen lo mismo. Presentar una
estimación propietaria como una medición es la misma clase de mentira que
presentar un fixture como un dato, y con un booleano no había forma de no
cometerla.

## Es destructiva, y por eso se prueba con datos dentro

La columna vieja **se elimina**: dos fuentes de verdad para lo mismo es
exactamente el problema que el Milestone 34 vino a arreglar, y dejar `simulated`
al lado de `basis` lo reintroduciría con otro nombre.

El `downgrade` reconstruye `simulated` desde `basis` (`simulated` ↔ `basis ==
'simulated'`). Lo que se pierde al bajar es la distinción entre medido y
estimado, porque en el esquema viejo no cabe — y eso es el motivo del milestone,
no un defecto de la migración.

Revision ID: e2c4a91b7d38
Revises: d1e8b4a7c206
Create Date: 2026-09-28

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e2c4a91b7d38"
down_revision: str | Sequence[str] | None = "d1e8b4a7c206"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "product_signals",
        sa.Column("basis", sa.String(length=16), nullable=False, server_default="measured"),
    )
    # Lo que era simulado sigue siéndolo; lo que no, se declara medido. Ninguna
    # fila existente pasa a `estimated`: nadie ha medido ni modelado nada nuevo,
    # y marcar como estimación algo que no lo es sería inventar procedencia.
    op.execute("UPDATE product_signals SET basis = 'simulated' WHERE simulated")
    op.execute("UPDATE product_signals SET basis = 'measured' WHERE NOT simulated")

    op.create_index("ix_product_signals_basis", "product_signals", ["basis"])
    op.drop_index("ix_product_signals_simulated", table_name="product_signals")
    op.drop_column("product_signals", "simulated")


def downgrade() -> None:
    op.add_column(
        "product_signals",
        sa.Column("simulated", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.execute("UPDATE product_signals SET simulated = (basis = 'simulated')")

    op.create_index("ix_product_signals_simulated", "product_signals", ["simulated"])
    op.drop_index("ix_product_signals_basis", table_name="product_signals")
    op.drop_column("product_signals", "basis")
