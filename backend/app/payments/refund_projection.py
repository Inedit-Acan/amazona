"""El reembolso sigue a la acción `payment.refund` en la misma transacción (Milestone 44, ADR 0028 §3 y §5).

`RefundActionObserver` refleja en `Refund` lo que le pasa a la `ExternalAction` de devolver el dinero, y mueve la
reserva de lo reembolsable (`refund_committed_amount`) en la misma transacción que la transición de la acción:

    PENDING  → CALLING             REQUESTED → SENDING            (la frontera de durabilidad)
    CALLING  → SUCCEEDED           SENDING → SENDING (+ la referencia del proveedor): aceptado, **sin confirmar**
    CALLING  → FAILED_CONFIRMED    SENDING → FAILED               (+ se libera la reserva)
    PENDING  → FAILED_CONFIRMED    REQUESTED → FAILED (`not_sent`) (+ se libera la reserva: nunca salió)
    CALLING  → UNKNOWN_OUTCOME     SENDING → UNKNOWN_OUTCOME      (la reserva **se mantiene**)
    UNKNOWN  → SUCCEEDED / FAILED  UNKNOWN_OUTCOME → SENDING / FAILED   (consulta, respuesta tardía o persona)

**Que el proveedor acepte la petición no es que el dinero haya vuelto.** Como en un cobro, lo que cuenta es un hecho
verificado: `refund.succeeded` (lo aplica `PaymentService`, que sube `refunded_amount`). Hasta entonces el reembolso
sigue `SENDING`, con la reserva puesta. Solo un fallo **confirmado** libera la reserva; un resultado desconocido no.
"""

import datetime
from decimal import Decimal

from sqlalchemy import update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.actions.contract import ActionResponse, ActionStatus
from app.db.models.audit import AuditLog
from app.db.models.external_action import ExternalAction
from app.db.models.payment import Refund
from app.payments import ledger
from app.payments.domain import RefundStatus

REFUND_REFERENCE_PREFIX = "order_refund:"
PROJECTION_ACTOR = "payments"


def refund_reference(refund_id: str) -> str:
    """El «sitio» de la operación de devolver este reembolso."""
    return f"{REFUND_REFERENCE_PREFIX}{refund_id}"


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


class RefundActionObserver:
    def on_transition(
        self,
        db: Session,
        action: ExternalAction,
        *,
        previous: str,
        current: str,
        response: ActionResponse | None,
    ) -> None:
        refund = db.get(Refund, action.reference.removeprefix(REFUND_REFERENCE_PREFIX))
        if refund is None:
            raise RuntimeError(f"action {action.id} refers to a refund that does not exist: {action.reference}")
        db.refresh(refund)

        if (previous, current) == (ActionStatus.PENDING.value, ActionStatus.CALLING.value):
            self._begin(db, refund, action)
        elif current == ActionStatus.SUCCEEDED.value:
            self._accepted(db, refund, action, response)
        elif current == ActionStatus.FAILED_CONFIRMED.value:
            self._failed(db, refund, action, previous)
        elif current == ActionStatus.UNKNOWN_OUTCOME.value:
            self._unknown(db, refund, action)

    # --- Transiciones ----------------------------------------------------------------------------

    def _begin(self, db: Session, refund: Refund, action: ExternalAction) -> None:
        if not self._move(db, refund, action, {RefundStatus.REQUESTED}, RefundStatus.SENDING):
            # Una acción que empieza sobre un reembolso que no está `REQUESTED` es una incoherencia: se aborta antes de
            # que la petición salga (la excepción deshace la transición de la acción).
            raise RuntimeError(f"refund {refund.id} is {refund.status}, not REQUESTED: the call must not start")

    def _accepted(self, db: Session, refund: Refund, action: ExternalAction, response: ActionResponse | None) -> None:
        # Aceptado por el proveedor ≠ dinero devuelto. Un `UNKNOWN_OUTCOME` que se resuelve como hecho vuelve a
        # `SENDING` (enviado, a la espera del hecho verificado).
        if refund.status == RefundStatus.UNKNOWN_OUTCOME.value:
            self._move(db, refund, action, {RefundStatus.UNKNOWN_OUTCOME}, RefundStatus.SENDING)
        elif refund.status == RefundStatus.FAILED.value:
            self._anomaly(db, refund, action, "refund_accepted_after_the_refund_was_recorded_as_failed")
        reference = response.reference if response is not None else None
        if reference and refund.provider_refund_ref is None:
            try:
                with db.begin_nested():
                    self._execute(
                        db,
                        update(Refund)
                        .where(Refund.id == refund.id, Refund.provider_refund_ref.is_(None))
                        .values(provider_refund_ref=reference),
                    )
            except IntegrityError:
                self._anomaly(db, refund, action, "provider_reference_already_belongs_to_another_refund")

    def _failed(self, db: Session, refund: Refund, action: ExternalAction, previous: str) -> None:
        code = {
            ActionStatus.PENDING.value: "not_sent",
            ActionStatus.CALLING.value: "provider_rejected",
        }.get(previous, "resolved_failed")
        moved = self._move(
            db,
            refund,
            action,
            {RefundStatus.REQUESTED, RefundStatus.SENDING, RefundStatus.UNKNOWN_OUTCOME},
            RefundStatus.FAILED,
            finished_at=_now(),
            failure_code=code,
        )
        if not moved:
            self._anomaly(db, refund, action, "refund_failed_after_the_refund_moved_on")
            return
        # Solo un fallo confirmado devuelve lo apartado, y en la misma transacción que el cambio de estado.
        if not ledger.release(db, refund.payment_id, Decimal(str(refund.amount))):
            raise RuntimeError(f"refund {refund.id}: its reservation could not be released from the payment")

    def _unknown(self, db: Session, refund: Refund, action: ExternalAction) -> None:
        moved = self._move(db, refund, action, {RefundStatus.SENDING}, RefundStatus.UNKNOWN_OUTCOME)
        if not moved and refund.status != RefundStatus.UNKNOWN_OUTCOME.value:
            self._anomaly(db, refund, action, "refund_unknown_after_the_refund_moved_on")

    # --- Interno -------------------------------------------------------------------------------------

    def _move(
        self,
        db: Session,
        refund: Refund,
        action: ExternalAction,
        expected: set[RefundStatus],
        target: RefundStatus,
        **values,
    ) -> bool:
        before = refund.status
        result = self._execute(
            db,
            update(Refund)
            .where(Refund.id == refund.id, Refund.status.in_([s.value for s in expected]))
            .values(status=target.value, **values),
        )
        if result.rowcount != 1:
            return False
        db.refresh(refund)
        db.add(
            AuditLog(
                actor=PROJECTION_ACTOR,
                action="refund.status_changed",
                resource=f"refund:{refund.id}",
                before={"status": before},
                after={"status": target.value, "external_action_id": action.id, "operation": action.operation},
                correlation_id=action.correlation_id,
            )
        )
        return True

    @staticmethod
    def _execute(db: Session, statement) -> CursorResult:
        result = db.execute(statement.execution_options(synchronize_session=False))
        assert isinstance(result, CursorResult)
        return result

    @staticmethod
    def _anomaly(db: Session, refund: Refund, action: ExternalAction, what: str) -> None:
        db.add(
            AuditLog(
                actor=PROJECTION_ACTOR,
                action=f"refund.anomaly.{what}",
                resource=f"refund:{refund.id}",
                before=None,
                after={
                    "refund_status": refund.status,
                    "external_action_id": action.id,
                    "action_status": action.status,
                },
                correlation_id=action.correlation_id,
            )
        )
