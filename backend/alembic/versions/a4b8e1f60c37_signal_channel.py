"""signal channel

Milestone 38 (ADR 0016). Una columna nueva en `product_signals` y nada más.

`market` decía en qué **geografía** se midió; `channel` dice en qué **canal**.
Hasta aquí solo existía la primera, así que una señal de competencia podía
significar cosas incompatibles sin que nada en el dato lo avisara: cuántos
vendedores compiten dentro de un marketplace no es lo mismo que cuánto cuesta
atraer a un comprador a una web propia.

## No hay relleno, y eso es una afirmación

Las filas existentes se quedan en `NULL`, que significa **agnóstica del canal** —
no «válida para todos». Y es correcto por lo que hay: las señales guardadas hoy
vienen de Wikimedia (interés por un tipo de producto, que no depende del canal) y
de fixtures (que no miden en ningún sitio). Atribuirles un canal sería afirmar que
se midió allí.

Nulable a propósito y sin valor por defecto: un `own_web` por defecto convertiría
cada señal antigua en una afirmación sobre el canal prioritario.

Revision ID: a4b8e1f60c37
Revises: f3d7a02c9e51
Create Date: 2026-09-28

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a4b8e1f60c37"
down_revision: str | Sequence[str] | None = "f3d7a02c9e51"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("product_signals", sa.Column("channel", sa.String(length=64), nullable=True))
    # Por aquí se pregunta: «la competencia de este canal», y «qué canales ha
    # medido alguien alguna vez».
    op.create_index("ix_product_signals_channel", "product_signals", ["channel"])


def downgrade() -> None:
    op.drop_index("ix_product_signals_channel", table_name="product_signals")
    op.drop_column("product_signals", "channel")
