"""payment event reconciliation process fields

Milestone 45 (ADR 0029 §6). El reconciliador **programado** reanuda los eventos de pago guardados y no aplicados
(`RECEIVED`). Un evento que
falla siempre no puede reintentarse para siempre ni bloquear a los demás: hace falta contar los intentos.

Se añaden tres campos de **proceso** (no del hecho; el hecho —proveedor, id, tipo, importe, hash— sigue siendo
inmutable):

- `reconcile_attempts`: cuántas veces lo ha intentado el reconciliador programado (0 por defecto; `CHECK >= 0`);
- `last_reconcile_error`: el último error (tipo y mensaje truncado; **nunca** el cuerpo ni datos del evento);
- `last_reconcile_at`: cuándo fue el último intento.

Un evento que llega al tope **sigue `RECEIVED`**: no se crea ningún estado nuevo, no se declara fallido y no se
libera nada.

## Bajar

Es aditiva: no modifica ni borra datos existentes. Bajar elimina los tres campos (solo metadatos de proceso: ningún
hecho financiero); los
eventos `RECEIVED` siguen igual y vuelven a poder reanudarse sin recuento.

Revision ID: d7e2a9c4f1b8
Revises: b3c8f1a5d742
Create Date: 2026-10-03

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d7e2a9c4f1b8"
down_revision: str | Sequence[str] | None = "b3c8f1a5d742"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("payment_events") as batch:
        batch.add_column(sa.Column("reconcile_attempts", sa.Integer(), nullable=False, server_default=sa.text("0")))
        batch.add_column(sa.Column("last_reconcile_error", sa.String(length=500), nullable=True))
        batch.add_column(sa.Column("last_reconcile_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_check_constraint("ck_payment_events_reconcile_attempts_not_negative", "reconcile_attempts >= 0")


def downgrade() -> None:
    with op.batch_alter_table("payment_events") as batch:
        batch.drop_constraint("ck_payment_events_reconcile_attempts_not_negative", type_="check")
        batch.drop_column("last_reconcile_at")
        batch.drop_column("last_reconcile_error")
        batch.drop_column("reconcile_attempts")
