"""El cobro sigue a la acción `payment.open` en la misma transacción (Milestone 44, ADR 0028 §3).

`PaymentOpenObserver` refleja en `Payment` lo que le pasa a la `ExternalAction` de abrir el cobro, dentro de la
transacción de cada transición de la acción. Por eso un cobro nunca dice «nada enviado» (`REQUESTED`) cuando la
petición pudo salir, ni «posiblemente enviado» (`OPENING`) cuando se sabe que no salió:

    PENDING  → CALLING             REQUESTED → OPENING          (la frontera de durabilidad)
    CALLING  → SUCCEEDED           OPENING → OPEN               (+ la referencia del proveedor, si la dio)
    CALLING  → FAILED_CONFIRMED    OPENING → FAILED
    PENDING  → FAILED_CONFIRMED    REQUESTED → FAILED (`not_sent`)   (el barrido: nunca salió)
    CALLING  → UNKNOWN_OUTCOME     OPENING → UNKNOWN_OUTCOME
    UNKNOWN  → SUCCEEDED / FAILED  UNKNOWN_OUTCOME → OPEN / FAILED   (consulta, respuesta tardía o persona)

Una acción que se cierra *contra* un hecho ya verificado (por ejemplo, la acción termina fallida y un webhook ya
había traído la captura) **no** cambia el cobro: se audita como anomalía. Un hecho del proveedor, verificado, manda
sobre la lectura de una respuesta.
"""

import datetime

from sqlalchemy import update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.actions.contract import ActionResponse, ActionStatus
from app.db.models.audit import AuditLog
from app.db.models.external_action import ExternalAction
from app.db.models.payment import Payment
from app.payments.domain import PaymentStatus

PAYMENT_REFERENCE_PREFIX = "order_payment:"
PROJECTION_ACTOR = "payments"

_NOT_YET_OPEN = (PaymentStatus.REQUESTED.value, PaymentStatus.OPENING.value, PaymentStatus.UNKNOWN_OUTCOME.value)


def payment_reference(payment_id: str) -> str:
    """El «sitio» de la operación de abrir este cobro."""
    return f"{PAYMENT_REFERENCE_PREFIX}{payment_id}"


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


class PaymentOpenObserver:
    def on_transition(
        self,
        db: Session,
        action: ExternalAction,
        *,
        previous: str,
        current: str,
        response: ActionResponse | None,
    ) -> None:
        payment = db.get(Payment, action.reference.removeprefix(PAYMENT_REFERENCE_PREFIX))
        if payment is None:
            raise RuntimeError(f"action {action.id} refers to a payment that does not exist: {action.reference}")
        db.refresh(payment)

        if (previous, current) == (ActionStatus.PENDING.value, ActionStatus.CALLING.value):
            self._begin(db, payment, action)
        elif current == ActionStatus.SUCCEEDED.value:
            self._opened(db, payment, action, response)
        elif current == ActionStatus.FAILED_CONFIRMED.value:
            self._failed(db, payment, action, previous)
        elif current == ActionStatus.UNKNOWN_OUTCOME.value:
            self._unknown(db, payment, action)

    # --- Transiciones ----------------------------------------------------------------------------

    def _begin(self, db: Session, payment: Payment, action: ExternalAction) -> None:
        if not self._move(db, payment, action, {PaymentStatus.REQUESTED}, PaymentStatus.OPENING):
            # Una acción que empieza sobre un cobro que no está `REQUESTED` es una incoherencia: se aborta antes de
            # que la petición salga (la excepción deshace la transición de la acción).
            raise RuntimeError(f"payment {payment.id} is {payment.status}, not REQUESTED: the call must not start")

    def _opened(self, db: Session, payment: Payment, action: ExternalAction, response: ActionResponse | None) -> None:
        reference = response.reference if response is not None else None
        moved = self._move(
            db,
            payment,
            action,
            {PaymentStatus.OPENING, PaymentStatus.UNKNOWN_OUTCOME},
            PaymentStatus.OPEN,
            opened_at=_now(),
        )
        if not moved:
            self._anomaly(db, payment, action, "payment_open_succeeded_after_the_payment_moved_on")
        if reference and payment.provider_payment_ref is None:
            try:
                with db.begin_nested():
                    self._execute(
                        db,
                        update(Payment)
                        .where(Payment.id == payment.id, Payment.provider_payment_ref.is_(None))
                        .values(provider_payment_ref=reference),
                    )
            except IntegrityError:
                self._anomaly(db, payment, action, "provider_reference_already_belongs_to_another_payment")

    def _failed(self, db: Session, payment: Payment, action: ExternalAction, previous: str) -> None:
        code = {
            ActionStatus.PENDING.value: "not_sent",
            ActionStatus.CALLING.value: "provider_rejected",
        }.get(previous, "resolved_failed")
        moved = self._move(
            db,
            payment,
            action,
            {PaymentStatus.REQUESTED, PaymentStatus.OPENING, PaymentStatus.UNKNOWN_OUTCOME},
            PaymentStatus.FAILED,
            closed_at=_now(),
            last_failure_code=code,
        )
        if not moved:
            self._anomaly(db, payment, action, "payment_open_failed_after_the_payment_moved_on")

    def _unknown(self, db: Session, payment: Payment, action: ExternalAction) -> None:
        moved = self._move(db, payment, action, {PaymentStatus.OPENING}, PaymentStatus.UNKNOWN_OUTCOME)
        if not moved and payment.status not in (PaymentStatus.UNKNOWN_OUTCOME.value,):
            self._anomaly(db, payment, action, "payment_open_unknown_after_the_payment_moved_on")

    # --- Interno -------------------------------------------------------------------------------------

    def _move(
        self,
        db: Session,
        payment: Payment,
        action: ExternalAction,
        expected: set[PaymentStatus],
        target: PaymentStatus,
        **values,
    ) -> bool:
        before = payment.status
        result = self._execute(
            db,
            update(Payment)
            .where(Payment.id == payment.id, Payment.status.in_([s.value for s in expected]))
            .values(status=target.value, **values),
        )
        if result.rowcount != 1:
            return False
        db.refresh(payment)
        db.add(
            AuditLog(
                actor=PROJECTION_ACTOR,
                action="payment.status_changed",
                resource=f"payment:{payment.id}",
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
    def _anomaly(db: Session, payment: Payment, action: ExternalAction, what: str) -> None:
        db.add(
            AuditLog(
                actor=PROJECTION_ACTOR,
                action=f"payment.anomaly.{what}",
                resource=f"payment:{payment.id}",
                before=None,
                after={
                    "payment_status": payment.status,
                    "external_action_id": action.id,
                    "action_status": action.status,
                },
                correlation_id=action.correlation_id,
            )
        )
