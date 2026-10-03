"""Reanudar los eventos de pago guardados y no aplicados, con un tope de intentos que no inventa estados (Milestone
45, ADR 0029 §6).

Un `PaymentEvent` `RECEIVED` es dinero verificado que aún no se ha aplicado (el proceso cayó entre las dos
transacciones de la puerta). El
reconciliador lo reanuda llamando a `PaymentService.apply`: **la misma puerta de siempre**, con su reclamo
compare-and-set, así que aplicar un evento
dos veces no mueve dinero dos veces.

## El tope de intentos

- **El intento se reclama antes de llamar a `apply`**, en su propia transacción, con el tope dentro de la condición
del `UPDATE`:

      UPDATE payment_events SET reconcile_attempts = reconcile_attempts + 1, last_reconcile_at = :ahora
       WHERE id = :id AND processing_status = 'RECEIVED' AND reconcile_attempts < :tope

  Contarlo **antes** significa que una caída a mitad de `apply` también cuenta, y que dos reconciliadores no pueden
  pasarse del tope entre los dos.
- Un fallo guarda `last_reconcile_error` (el tipo y, de errores nuestros, el mensaje truncado: **nunca** el cuerpo ni
datos del evento) y sigue con el
  siguiente evento: un evento «venenoso» no bloquea el lote.
- **Al llegar al tope** el evento deja de reintentarse solo y **sigue `RECEIVED`**: no hay estado nuevo, no se
declara `FAILED`, no se libera ninguna
  reserva y no se pierde. Queda visible (`report`) con sus intentos, su edad y su último error. Se audita una vez
  (`payment_event.reconcile_capped`).
- **Las reentregas del proveedor no cuentan**: un webhook repetido sigue reanudando el evento por `PaymentIngress`;
el tope limita al programador.

## `retry_event`: la salida humana

Una acción **humana y operativa** (la consola). Reintenta el **procesamiento** de un evento ya guardado: llama a
`PaymentService.apply`. **No vuelve a
efectuar el cobro**, no llama al proveedor de pago, no crea eventos y respeta la unicidad de `(provider,
provider_event_id)` y el `payload_hash`
(no se tocan). Solo actúa sobre un evento `RECEIVED`; si está en cualquier otro estado no hace nada y no genera
ningún efecto económico. Queda auditado
quién lo pidió, cuándo, por qué y qué resultó.
"""

import datetime
import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError, ValidationError
from app.db.models.audit import AuditLog
from app.db.models.payment import PaymentEvent
from app.payments.domain import EventProcessing
from app.payments.service import PaymentService
from app.reconciliation.actions import RECONCILER_ACTOR, SWEEP_BATCH, safe_error

logger = logging.getLogger(__name__)


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


@dataclass
class EventSweepReport:
    examined: int = 0
    #: Resultado de `apply` por tipo (`applied`, `stale`, `conflict`, `unmatched`…), en minúsculas.
    outcomes: dict[str, int] = field(default_factory=dict)
    #: Eventos cuyo intento no se pudo reclamar (otro reconciliador lo hizo, o ya no estaban pendientes, o agotaron
    #: el tope).
    skipped: int = 0
    failed: list[tuple[str, str]] = field(default_factory=list)
    #: Eventos que con este intento alcanzaron el tope y dejan de reintentarse solos.
    capped_now: list[str] = field(default_factory=list)

    def summary(self) -> dict:
        return {
            "examined": self.examined,
            "outcomes": dict(sorted(self.outcomes.items())),
            "skipped": self.skipped,
            "failed": len(self.failed),
            "capped_now": len(self.capped_now),
        }


class EventReconciler:
    def __init__(
        self,
        db: Session,
        *,
        older_than: datetime.timedelta,
        max_attempts: int,
        clock: Callable[[], datetime.datetime] = _utcnow,
        batch: int = SWEEP_BATCH,
    ) -> None:
        if max_attempts < 1:
            raise ValidationError("the attempt cap must be at least one")
        self._db = db
        self._older_than = older_than
        self._max_attempts = max_attempts
        self._clock = clock
        self._batch = batch

    def sweep(self, heartbeat: Callable[[], None] | None = None) -> EventSweepReport:
        report = EventSweepReport()
        limit = self._clock() - self._older_than
        ids = list(
            self._db.scalars(
                select(PaymentEvent.id)
                .where(
                    PaymentEvent.processing_status == EventProcessing.RECEIVED.value,
                    PaymentEvent.received_at < limit,
                    PaymentEvent.reconcile_attempts < self._max_attempts,
                )
                .order_by(PaymentEvent.received_at, PaymentEvent.id)
                .limit(self._batch)
            )
        )
        for event_id in ids:
            if heartbeat is not None:
                heartbeat()
            report.examined += 1
            attempt = self._claim_attempt(event_id)
            if attempt is None:
                report.skipped += 1
                continue
            try:
                outcome = PaymentService(self._db, clock=self._clock).apply(event_id)
            except Exception as exc:  # noqa: BLE001 - un evento que falla no puede abortar el lote
                self._db.rollback()
                capped = self._record_failure(event_id, attempt, exc)
                report.failed.append((event_id, type(exc).__name__))
                if capped:
                    report.capped_now.append(event_id)
                continue
            self._audit_attempt(event_id, attempt, outcome=outcome.lower())
            report.outcomes[outcome.lower()] = report.outcomes.get(outcome.lower(), 0) + 1
        return report

    # --- Interno -----------------------------------------------------------------------------

    def _claim_attempt(self, event_id: str) -> int | None:
        """Cuenta un intento **antes** de aplicar. `None` si no se pudo (ya no está `RECEIVED`, otro lo reclamó o
        agotó el tope)."""
        result = self._db.execute(
            update(PaymentEvent)
            .where(
                PaymentEvent.id == event_id,
                PaymentEvent.processing_status == EventProcessing.RECEIVED.value,
                PaymentEvent.reconcile_attempts < self._max_attempts,
            )
            .values(reconcile_attempts=PaymentEvent.reconcile_attempts + 1, last_reconcile_at=self._clock())
            .execution_options(synchronize_session=False)
        )
        assert isinstance(result, CursorResult)
        if result.rowcount != 1:
            self._db.rollback()
            return None
        attempts = self._db.scalar(select(PaymentEvent.reconcile_attempts).where(PaymentEvent.id == event_id))
        self._db.commit()
        return int(attempts or 0)

    def _record_failure(self, event_id: str, attempt: int, exc: Exception) -> bool:
        """Deja el último error, audita el intento fallido y, si es el que agota el tope, lo audita una vez. Devuelve
        si se alcanzó el tope."""
        error = safe_error(exc)
        capped = attempt >= self._max_attempts
        try:
            self._db.execute(
                update(PaymentEvent)
                .where(PaymentEvent.id == event_id)
                .values(last_reconcile_error=error, last_reconcile_at=self._clock())
                .execution_options(synchronize_session=False)
            )
            self._add_audit(
                event_id,
                "payment_event.reconcile_attempt",
                {"attempt": attempt, "max_attempts": self._max_attempts, "failed": True, "error": error},
            )
            if capped:
                self._add_audit(
                    event_id,
                    "payment_event.reconcile_capped",
                    {
                        "attempts": attempt,
                        "max_attempts": self._max_attempts,
                        "last_error": error,
                        "note": "the event stays RECEIVED and waits for a person: no state was invented",
                    },
                )
            self._db.commit()
        except Exception:  # noqa: BLE001 - dejar rastro del fallo no puede ser otro fallo del lote
            self._db.rollback()
            logger.warning("could not record the failure of payment event %s", event_id)
        return capped

    def _audit_attempt(self, event_id: str, attempt: int, *, outcome: str) -> None:
        try:
            self._add_audit(
                event_id,
                "payment_event.reconcile_attempt",
                {"attempt": attempt, "max_attempts": self._max_attempts, "failed": False, "outcome": outcome},
            )
            self._db.commit()
        except Exception:  # noqa: BLE001
            self._db.rollback()

    def _add_audit(self, event_id: str, action: str, after: dict) -> None:
        self._db.add(
            AuditLog(
                actor=RECONCILER_ACTOR,
                action=action,
                resource=f"payment_event:{event_id}",
                before=None,
                after=after,
                correlation_id=event_id,
            )
        )


# --- La salida humana --------------------------------------------------------------------------


@dataclass(frozen=True)
class RetryResult:
    event_id: str
    status_before: str
    attempts_before: int
    #: Si se intentó aplicar. `False`: el evento no estaba `RECEIVED` y no se hizo nada.
    performed: bool
    #: El resultado de `apply` en minúsculas, si se aplicó.
    outcome: str | None = None
    #: Si `apply` falló: el tipo y, de errores nuestros, el mensaje truncado.
    error: str | None = None


def retry_event(
    db: Session,
    event_id: str,
    *,
    actor: str,
    reason: str,
    clock: Callable[[], datetime.datetime] = _utcnow,
) -> RetryResult:
    """Reintenta el **procesamiento** de un `PaymentEvent` `RECEIVED` (ADR 0029 §6). No cobra, no llama al proveedor,
    no toca el hecho."""
    if not reason.strip():
        raise ValidationError("retrying a payment event needs a reason")
    event = db.get(PaymentEvent, event_id, populate_existing=True)
    if event is None:
        raise NotFoundError(f"payment event {event_id} not found")
    status_before: str = event.processing_status
    attempts_before = int(event.reconcile_attempts)
    before = {
        "processing_status": status_before,
        "reconcile_attempts": attempts_before,
        "last_reconcile_error": event.last_reconcile_error,
    }

    def audit(action: str, after: dict) -> None:
        db.add(
            AuditLog(
                actor=actor,
                action=action,
                resource=f"payment_event:{event_id}",
                before=before,
                after={"reason": reason[:500], **after},
                correlation_id=event_id,
            )
        )

    if event.processing_status != EventProcessing.RECEIVED.value:
        note = "the event is not RECEIVED: nothing was done"
        audit("payment_event.reprocess_requested", {"performed": False, "note": note})
        db.commit()
        return RetryResult(event_id, event.processing_status, event.reconcile_attempts, performed=False)

    moved = db.execute(
        update(PaymentEvent)
        .where(PaymentEvent.id == event_id, PaymentEvent.processing_status == EventProcessing.RECEIVED.value)
        .values(reconcile_attempts=0, last_reconcile_error=None)
        .execution_options(synchronize_session=False)
    )
    assert isinstance(moved, CursorResult)
    audit("payment_event.reprocess_requested", {"performed": moved.rowcount == 1})
    db.commit()
    if moved.rowcount != 1:  # lo aplicó otro mientras tanto: ya no hay nada que reintentar
        current = db.get(PaymentEvent, event_id, populate_existing=True)
        status = current.processing_status if current is not None else status_before
        return RetryResult(event_id, status, attempts_before, performed=False)

    try:
        outcome = PaymentService(db, clock=clock).apply(event_id)
    except Exception as exc:  # noqa: BLE001 - se informa, no se oculta: el evento sigue RECEIVED
        db.rollback()
        error = safe_error(exc)
        db.execute(
            update(PaymentEvent)
            .where(PaymentEvent.id == event_id)
            .values(last_reconcile_error=error, last_reconcile_at=clock())
            .execution_options(synchronize_session=False)
        )
        audit("payment_event.reprocess_result", {"outcome": None, "error": error})
        db.commit()
        return RetryResult(
            event_id, status_before, attempts_before, performed=True, error=error
        )
    audit("payment_event.reprocess_result", {"outcome": outcome.lower()})
    db.commit()
    return RetryResult(event_id, status_before, attempts_before, True, outcome.lower())
