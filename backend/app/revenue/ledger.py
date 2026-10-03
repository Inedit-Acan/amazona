"""La única vía de escritura del registro de ingresos verificados (ADR 0030 §7).

Solo `PaymentService` llama a este módulo, **dentro de la transacción que aplica el evento** y justo después del
cambio económico que la entrada representa: o cambian el estado del cobro y nace la entrada, o no cambia nada. Si la
entrada no se puede escribir, el evento no se aplica (sigue `RECEIVED` y entra en el ciclo de la ADR 0029).

**Un fallo del registro nunca se confunde con la carrera de las capturas.** `PaymentService._capture` captura el
`IntegrityError` de «un solo `SUCCEEDED` por pedido» para reescribir la captura como duplicada; si una violación del
propio registro llegara allí como `IntegrityError` se leería como esa carrera. Por eso aquí se convierte en
`RevenueLedgerWriteError`, que no es un `IntegrityError` y sube hasta deshacer el evento entero.
"""

import datetime
from collections.abc import Callable
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models.payment import Payment, PaymentEvent, Refund
from app.db.models.revenue import RevenueLedgerEntry
from app.revenue.domain import EntryKind, classify_capture


class RevenueLedgerWriteError(RuntimeError):
    """La entrada de un hecho verificado no se pudo escribir. El evento no debe aplicarse."""


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


class RevenueLedger:
    def __init__(self, db: Session, *, clock: Callable[[], datetime.datetime] = _utcnow) -> None:
        self._db = db
        self._clock = clock

    def record_capture(
        self, *, event: PaymentEvent, payment: Payment, payment_status: str, amount: Decimal
    ) -> RevenueLedgerEntry:
        """La entrada `CAPTURE` de una captura que `PaymentService` acaba de registrar en el cobro."""
        return self._write(
            RevenueLedgerEntry(
                kind=EntryKind.CAPTURE.value,
                classification=classify_capture(payment_status).value,
                payment_event_id=event.id,
                payment_id=payment.id,
                order_id=payment.order_id,
                refund_id=None,
                capture_entry_id=None,
                amount=amount,
                currency=payment.currency,
                occurred_at=event.occurred_at,
                recorded_at=self._clock(),
            )
        )

    def record_refund(
        self, *, event: PaymentEvent, payment: Payment, refund: Refund, amount: Decimal
    ) -> RevenueLedgerEntry | None:
        """La entrada `REFUND` de un reembolso confirmado, que **hereda** la clasificación de la captura que revierte.

        Devuelve `None` cuando el cobro no tiene entrada de captura: es un cobro **anterior al registro**
        (`outside_ledger`, ADR 0030 §13), y un reembolso nunca se bloquea por una laguna del registro."""
        capture = self.capture_entry_of(payment.id)
        if capture is None:
            return None
        return self._write(
            RevenueLedgerEntry(
                kind=EntryKind.REFUND.value,
                classification=capture.classification,
                payment_event_id=event.id,
                payment_id=payment.id,
                order_id=payment.order_id,
                refund_id=refund.id,
                capture_entry_id=capture.id,
                amount=amount,
                currency=capture.currency,
                occurred_at=event.occurred_at,
                recorded_at=self._clock(),
            )
        )

    def capture_entry_of(self, payment_id: str) -> RevenueLedgerEntry | None:
        return self._db.scalars(
            select(RevenueLedgerEntry).where(
                RevenueLedgerEntry.payment_id == payment_id, RevenueLedgerEntry.kind == EntryKind.CAPTURE.value
            )
        ).one_or_none()

    def _write(self, entry: RevenueLedgerEntry) -> RevenueLedgerEntry:
        try:
            self._db.add(entry)
            self._db.flush()
        except IntegrityError as exc:
            # Solo el tipo: el mensaje de la base podría llevar valores. El evento sigue `RECEIVED` y se reintenta.
            raise RevenueLedgerWriteError(
                f"the {entry.kind} entry of event {entry.payment_event_id} could not be written "
                f"({type(exc.orig).__name__})"
            ) from exc
        return entry
