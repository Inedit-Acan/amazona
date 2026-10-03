"""El registro de ingresos verificados (Milestone 45, ADR 0030).

**No es el libro contable ni fiscal de KOVA.** Es una lista **inmutable** de hechos monetarios operativos verificados,
una *proyección determinista* de los hechos de pago que `PaymentService` aplica (un `PaymentEvent` `APPLIED`). No es
una segunda fuente de verdad: cada entrada nombra el evento que la causó, el cobro, el pedido y, si es un reembolso, el
reembolso y la captura que revierte.

- Una entrada por evento (`UNIQUE (payment_event_id)`), una `CAPTURE` por cobro y una `REFUND` por reembolso.
- La clasificación de una `CAPTURE` sale del estado del cobro (`ORDER_PAYMENT`, `DUPLICATE_RECEIPT`,
  `MISMATCH_RECEIPT`); un `REFUND` **hereda** la de su captura, y la base lo hace cumplir con una clave ajena
  compuesta (clasificación, moneda y cobro iguales a los de la captura).
- Es **append-only**: un trigger rechaza `UPDATE` y `DELETE` (y `TRUNCATE` en PostgreSQL). La misma sentencia que crea
  el trigger en la migración se usa aquí (`after_create`), para que las bases de las pruebas y la real hablen de lo
  mismo.

Los importes son `Numeric(18,4)`: nunca `float`. Ningún dato personal.
"""

import datetime
from decimal import Decimal

from sqlalchemy import (
    DDL,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    event,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import IdMixin

#: PostgreSQL: una función y dos triggers (por fila para `UPDATE`/`DELETE`, por sentencia para `TRUNCATE`). El mensaje
#: no lleva `%` (el `DDL` de SQLAlchemy interpola `%`) ni `:` (`text()` lo tomaría por un parámetro).
APPEND_ONLY_POSTGRESQL = (
    """CREATE OR REPLACE FUNCTION revenue_ledger_entries_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION USING ERRCODE = 'restrict_violation',
        MESSAGE = 'revenue_ledger_entries is append-only - ' || TG_OP || ' is rejected';
END;
$$""",
    """CREATE TRIGGER revenue_ledger_entries_append_only_row BEFORE UPDATE OR DELETE ON revenue_ledger_entries
FOR EACH ROW EXECUTE FUNCTION revenue_ledger_entries_append_only()""",
    """CREATE TRIGGER revenue_ledger_entries_append_only_truncate BEFORE TRUNCATE ON revenue_ledger_entries
FOR EACH STATEMENT EXECUTE FUNCTION revenue_ledger_entries_append_only()""",
)

#: SQLite: un trigger por operación (no admite `UPDATE OR DELETE`).
APPEND_ONLY_SQLITE = (
    """CREATE TRIGGER revenue_ledger_entries_no_update BEFORE UPDATE ON revenue_ledger_entries
BEGIN
    SELECT RAISE(ABORT, 'revenue_ledger_entries is append-only - UPDATE is rejected');
END""",
    """CREATE TRIGGER revenue_ledger_entries_no_delete BEFORE DELETE ON revenue_ledger_entries
BEGIN
    SELECT RAISE(ABORT, 'revenue_ledger_entries is append-only - DELETE is rejected');
END""",
)

_KINDS = "kind IN ('CAPTURE', 'REFUND')"
_CLASSIFICATIONS = "classification IN ('ORDER_PAYMENT', 'DUPLICATE_RECEIPT', 'MISMATCH_RECEIPT')"


class RevenueLedgerEntry(IdMixin, Base):
    """Un hecho monetario verificado: una captura o un reembolso confirmados (ADR 0030 §3)."""

    __tablename__ = "revenue_ledger_entries"
    __table_args__ = (
        UniqueConstraint("payment_event_id", name="uq_revenue_entries_payment_event"),
        UniqueConstraint(
            "id", "classification", "currency", "payment_id", name="uq_revenue_entries_inheritance_target"
        ),
        ForeignKeyConstraint(
            ["capture_entry_id", "classification", "currency", "payment_id"],
            [
                "revenue_ledger_entries.id",
                "revenue_ledger_entries.classification",
                "revenue_ledger_entries.currency",
                "revenue_ledger_entries.payment_id",
            ],
            name="fk_revenue_entries_refund_inherits_capture",
        ),
        Index(
            "uq_revenue_entries_one_capture_per_payment",
            "payment_id",
            unique=True,
            postgresql_where=text("kind = 'CAPTURE'"),
            sqlite_where=text("kind = 'CAPTURE'"),
        ),
        Index(
            "uq_revenue_entries_one_entry_per_refund",
            "refund_id",
            unique=True,
            postgresql_where=text("refund_id IS NOT NULL"),
            sqlite_where=text("refund_id IS NOT NULL"),
        ),
        CheckConstraint(_KINDS, name="ck_revenue_entries_kind"),
        CheckConstraint(_CLASSIFICATIONS, name="ck_revenue_entries_classification"),
        CheckConstraint("amount > 0", name="ck_revenue_entries_amount_positive"),
        CheckConstraint("length(currency) = 3", name="ck_revenue_entries_currency_shape"),
        CheckConstraint("(kind = 'REFUND') = (refund_id IS NOT NULL)", name="ck_revenue_entries_refund_names_refund"),
        CheckConstraint(
            "(kind = 'REFUND') = (capture_entry_id IS NOT NULL)", name="ck_revenue_entries_refund_names_capture"
        ),
    )

    kind: Mapped[str] = mapped_column(String(10))
    classification: Mapped[str] = mapped_column(String(20))
    payment_event_id: Mapped[str] = mapped_column(ForeignKey("payment_events.id"))
    payment_id: Mapped[str] = mapped_column(ForeignKey("payments.id"), index=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), index=True)
    refund_id: Mapped[str | None] = mapped_column(ForeignKey("refunds.id"), nullable=True)
    capture_entry_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    currency: Mapped[str] = mapped_column(String(3))
    #: Cuándo ocurrió el hecho según el proveedor (`PaymentEvent.occurred_at`), no cuándo llegó.
    occurred_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True))
    #: Cuándo se proyectó: el reloj de la transacción que aplicó el evento.
    recorded_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True))


for _statement in APPEND_ONLY_POSTGRESQL:
    event.listen(RevenueLedgerEntry.__table__, "after_create", DDL(_statement).execute_if(dialect="postgresql"))
for _statement in APPEND_ONLY_SQLITE:
    event.listen(RevenueLedgerEntry.__table__, "after_create", DDL(_statement).execute_if(dialect="sqlite"))
