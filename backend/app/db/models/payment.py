import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import IdMixin, TimestampMixin

_ACTIVE = "status IN ('REQUESTED', 'OPENING', 'UNKNOWN_OUTCOME', 'OPEN')"
_PAYMENT_STATUSES = (
    "status IN ('REQUESTED', 'OPENING', 'UNKNOWN_OUTCOME', 'OPEN', 'SUCCEEDED', 'FAILED', 'EXPIRED', "
    "'DUPLICATE_CAPTURE', 'CAPTURE_MISMATCH')"
)


class Payment(IdMixin, TimestampMixin, Base):
    """Un **intento de cobro** de un pedido (Milestone 44, ADR 0028 §2): un objeto de cobro en el proveedor.

    Un pedido tiene varios intentos (`attempt_number`). Los intentos fallidos no obligan a recrear el pedido.

    - **Como mucho un intento activo por pedido** (`REQUESTED`, `OPENING`, `UNKNOWN_OUTCOME`, `OPEN`): un intento de
      resultado desconocido **bloquea** los nuevos hasta reconciliarse o resolverse.
    - **Como mucho un `SUCCEEDED` por pedido**: la defensa contra *nuestro* código (dos cobros normales). **No** impide
      guardar la evidencia de que el proveedor cobró dos veces: ese segundo cobro real se guarda como
      `DUPLICATE_CAPTURE` (con `duplicate_of_payment_id`), y uno de un importe distinto, como `CAPTURE_MISMATCH`.
      Por eso tampoco se exige `captured_amount <= amount`: el dinero que existió se registra tal cual.
    - `refunded <= refund_committed <= captured` es lo que nuestro código no puede incumplir: se reserva con
      aritmética de base de datos y un `CHECK` de respaldo.

    El estado solo lo escriben `PaymentService` (eventos verificados) y el observador de la acción `payment.open`
    (`app/payments/projection.py`). Ninguna ruta lo toca."""

    __tablename__ = "payments"
    __table_args__ = (
        UniqueConstraint("order_id", "attempt_number", name="uq_payments_order_attempt"),
        Index(
            "uq_payments_one_succeeded_per_order",
            "order_id",
            unique=True,
            postgresql_where=text("status = 'SUCCEEDED'"),
            sqlite_where=text("status = 'SUCCEEDED'"),
        ),
        Index(
            "uq_payments_one_active_attempt_per_order",
            "order_id",
            unique=True,
            postgresql_where=text(_ACTIVE),
            sqlite_where=text(_ACTIVE),
        ),
        Index(
            "uq_payments_provider_payment_ref",
            "provider",
            "provider_payment_ref",
            unique=True,
            postgresql_where=text("provider_payment_ref IS NOT NULL"),
            sqlite_where=text("provider_payment_ref IS NOT NULL"),
        ),
        CheckConstraint(_PAYMENT_STATUSES, name="ck_payments_status"),
        CheckConstraint("attempt_number >= 1", name="ck_payments_attempt_positive"),
        CheckConstraint("amount > 0", name="ck_payments_amount_positive"),
        CheckConstraint(
            "captured_amount >= 0 AND refund_committed_amount >= 0 AND refunded_amount >= 0",
            name="ck_payments_amounts_not_negative",
        ),
        CheckConstraint(
            "refunded_amount <= refund_committed_amount AND refund_committed_amount <= captured_amount",
            name="ck_payments_refunds_within_captured",
        ),
        CheckConstraint(
            "status IN ('SUCCEEDED', 'DUPLICATE_CAPTURE', 'CAPTURE_MISMATCH') OR captured_amount = 0",
            name="ck_payments_captured_only_when_captured",
        ),
        CheckConstraint("status <> 'SUCCEEDED' OR captured_amount = amount", name="ck_payments_succeeded_is_exact"),
        CheckConstraint(
            "(status = 'DUPLICATE_CAPTURE') = (duplicate_of_payment_id IS NOT NULL)",
            name="ck_payments_duplicate_names_the_original",
        ),
    )

    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), index=True)
    attempt_number: Mapped[int] = mapped_column(Integer)
    provider: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24), default="REQUESTED")
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    currency: Mapped[str] = mapped_column(String(3))
    #: Lo que el proveedor llama a este cobro. Vacío hasta que se abre (o si la respuesta se perdió: entonces los
    #: eventos se emparejan por `client_reference`, que es el `id` de esta fila).
    provider_payment_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    captured_amount: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=Decimal(0))
    refund_committed_amount: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=Decimal(0))
    refunded_amount: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=Decimal(0))
    duplicate_of_payment_id: Mapped[str | None] = mapped_column(ForeignKey("payments.id"), nullable=True)
    last_failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    opened_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    succeeded_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_event_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(36))


class PaymentEvent(IdMixin, Base):
    """Un hecho que un proveedor cuenta, **verificado**, y qué se hizo con él (Milestone 44, ADR 0028 §1).

    Es un registro **inmutable salvo su estado de proceso**: los campos que identifican y describen el hecho
    (proveedor, id, tipo, importe, hash del cuerpo) no se reescriben nunca; solo `processing_status`,
    `processed_at`, `note` y los enlaces al cobro o al reembolso que se descubren al aplicarlo.

    - `(provider, provider_event_id)` es único: el mismo evento dos veces es **uno**.
    - **No se guarda el cuerpo bruto**: solo su `payload_hash` y una lista blanca de campos. Un cuerpo real
      contendría datos personales.
    - `RECEIVED` es el único estado no definitivo: significa «verificado y guardado, aún no aplicado» (el proceso
      cayó entre las dos transacciones). La reentrega del proveedor, o `reconcile-payment-events`, lo reanuda."""

    __tablename__ = "payment_events"
    __table_args__ = (
        UniqueConstraint("provider", "provider_event_id", name="uq_payment_events_provider_event"),
        Index(
            "ix_payment_events_received",
            "received_at",
            postgresql_where=text("processing_status = 'RECEIVED'"),
            sqlite_where=text("processing_status = 'RECEIVED'"),
        ),
        CheckConstraint(
            "processing_status IN ('RECEIVED', 'APPLIED', 'STALE', 'CONFLICT', 'UNMATCHED', 'REJECTED')",
            name="ck_payment_events_processing_status",
        ),
        CheckConstraint("(amount IS NULL) = (currency IS NULL)", name="ck_payment_events_amount_has_currency"),
        CheckConstraint("reconcile_attempts >= 0", name="ck_payment_events_reconcile_attempts_not_negative"),
    )

    provider: Mapped[str] = mapped_column(String(64))
    provider_event_id: Mapped[str] = mapped_column(String(128))
    event_type: Mapped[str] = mapped_column(String(32))
    payment_id: Mapped[str | None] = mapped_column(ForeignKey("payments.id"), nullable=True, index=True)
    refund_id: Mapped[str | None] = mapped_column(ForeignKey("refunds.id"), nullable=True)
    provider_payment_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    provider_refund_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    client_reference: Mapped[str | None] = mapped_column(String(64), nullable=True)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    occurred_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True))
    payload_hash: Mapped[str] = mapped_column(String(64))
    #: Solo campos de una lista blanca. Nunca el cuerpo.
    data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    processing_status: Mapped[str] = mapped_column(String(16), default="RECEIVED")
    processed_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    #: Campos de **proceso**, no del hecho (ADR 0029 §6): cuántas veces el reconciliador **programado** ha intentado
    #: aplicar este evento,
    #: con qué error falló la última y cuándo. El hecho (proveedor, id, tipo, importe, hash) sigue siendo inmutable.
    #: Un evento que llega al
    #: tope sigue `RECEIVED` (no hay estado nuevo) y queda visible para una persona; las reentregas del proveedor no
    #: cuentan.
    reconcile_attempts: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    last_reconcile_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    last_reconcile_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Refund(IdMixin, TimestampMixin, Base):
    """Una devolución de dinero cobrado (Milestone 44, ADR 0028 §5).

    Es entidad propia porque es una operación **que iniciamos nosotros** (con identidad, importe fijado y
    reintentos), y porque garantizar `Σ reembolsos ≤ cobrado` exige contar los reembolsos **en vuelo**. El importe
    se reserva sobre el cobro con aritmética de base de datos; `UNKNOWN_OUTCOME` **mantiene** la reserva y un
    fallo confirmado la libera.

    `origin` es quién la inició: `OPERATOR` (una persona con permiso) o `PROVIDER` (un hecho del proveedor, por
    ejemplo un reembolso desde su panel). Ningún camino crea reembolsos automáticamente."""

    __tablename__ = "refunds"
    __table_args__ = (
        Index(
            "uq_refunds_provider_refund_ref",
            "provider",
            "provider_refund_ref",
            unique=True,
            postgresql_where=text("provider_refund_ref IS NOT NULL"),
            sqlite_where=text("provider_refund_ref IS NOT NULL"),
        ),
        CheckConstraint("origin IN ('OPERATOR', 'PROVIDER')", name="ck_refunds_origin"),
        CheckConstraint(
            "status IN ('REQUESTED', 'SENDING', 'UNKNOWN_OUTCOME', 'SUCCEEDED', 'FAILED')", name="ck_refunds_status"
        ),
        CheckConstraint("amount > 0", name="ck_refunds_amount_positive"),
    )

    payment_id: Mapped[str] = mapped_column(ForeignKey("payments.id"), index=True)
    provider: Mapped[str] = mapped_column(String(64))
    origin: Mapped[str] = mapped_column(String(12))
    status: Mapped[str] = mapped_column(String(20), default="REQUESTED")
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    currency: Mapped[str] = mapped_column(String(3))
    reason: Mapped[str] = mapped_column(String(32))
    provider_refund_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    requested_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(36))
    requested_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
