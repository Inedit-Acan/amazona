"""El fulfillment sigue a las acciones `fulfillment.purchase` y `fulfillment.ship` en la misma transacción
(Milestone 44, ADR 0028 §3 y §6).

`FulfilmentActionObserver` refleja en `Fulfillment` lo que le pasa a la `ExternalAction` de comprar o de enviar, dentro
de la transacción de cada transición de la acción. Por eso un fulfillment nunca dice «nada enviado» cuando la petición
pudo salir, ni «posiblemente enviado» cuando se sabe que no salió.

    COMPRAR                                          ENVIAR
    PENDING → CALLING    READY → PURCHASING          PURCHASED → SHIPPING
    → SUCCEEDED          PURCHASING → PURCHASED      SHIPPING → SHIPPED
    → FAILED_CONFIRMED   PURCHASING → READY (+1)     SHIPPING → PURCHASED (+1)      (CALLING o UNKNOWN)
    PENDING → FAILED     (nada: no salió)            (nada: no salió)
    → UNKNOWN_OUTCOME    PURCHASING → UNKNOWN(purchase)   SHIPPING → UNKNOWN(ship)
    UNKNOWN → SUCCEEDED / FAILED  → PURCHASED / READY(+1)  → SHIPPED / PURCHASED(+1)

(+1 = `failed_attempts + 1` y el código del fallo.)

**Un fallo de envío no es un `FAILED`.** Las unidades ya se compraron: el fulfillment vuelve a `PURCHASED`, las
unidades siguen asignadas, queda para que alguien lo mire y el envío puede reintentarse. **Un fallo de compra
confirmado vuelve a `READY`**: no se compró nada, así que ese es el estado verdadero; abandonarlo (`CANCELLED` o
`FAILED`) es una decisión de una persona que pasa por `release_allocation()`. Un resultado desconocido **no** devuelve
nada al pool.

La referencia de la acción es `order_fulfilment:{fulfillment_id}:{purchase|ship}`: cada fase es su propio «sitio», así
que una compra cerrada no se confunde con el envío que viene después.
"""

import datetime

from sqlalchemy import update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.actions.contract import ActionResponse, ActionStatus
from app.db.models.audit import AuditLog
from app.db.models.external_action import ExternalAction
from app.db.models.fulfillment import Fulfillment
from app.orders.fulfilment_domain import PHASE_FOR_OPERATION, FulfillmentStatus
from app.orders.fulfilment_port import PHASE_PURCHASE, PHASE_SHIP

FULFILMENT_REFERENCE_PREFIX = "order_fulfilment:"
PROJECTION_ACTOR = "fulfilment"


def fulfilment_reference(fulfillment_id: str, phase: str) -> str:
    """El «sitio» de la operación de esta fase de este fulfillment."""
    return f"{FULFILMENT_REFERENCE_PREFIX}{fulfillment_id}:{phase}"


def _parse(reference: str) -> tuple[str, str]:
    fulfillment_id, _, phase = reference.removeprefix(FULFILMENT_REFERENCE_PREFIX).rpartition(":")
    return fulfillment_id, phase


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


class FulfilmentActionObserver:
    def on_transition(
        self,
        db: Session,
        action: ExternalAction,
        *,
        previous: str,
        current: str,
        response: ActionResponse | None,
    ) -> None:
        fulfillment_id, phase = _parse(action.reference)
        if phase not in (PHASE_PURCHASE, PHASE_SHIP) or PHASE_FOR_OPERATION.get(action.operation) != phase:
            raise RuntimeError(f"action {action.id} has a reference that does not match its operation")
        fulfillment = db.get(Fulfillment, fulfillment_id)
        if fulfillment is None:
            raise RuntimeError(f"action {action.id} refers to a fulfillment that does not exist: {action.reference}")
        db.refresh(fulfillment)

        if (previous, current) == (ActionStatus.PENDING.value, ActionStatus.CALLING.value):
            self._begin(db, fulfillment, action, phase)
        elif current == ActionStatus.SUCCEEDED.value:
            self._done(db, fulfillment, action, phase, response)
            action.applied_at = _now()  # el dominio ya registró este resultado: la operación queda cerrada del todo
        elif current == ActionStatus.FAILED_CONFIRMED.value:
            self._failed(db, fulfillment, action, phase, previous)
        elif current == ActionStatus.UNKNOWN_OUTCOME.value:
            self._unknown(db, fulfillment, action, phase)

    # --- Transiciones ----------------------------------------------------------------------------

    def _begin(self, db: Session, fulfillment: Fulfillment, action: ExternalAction, phase: str) -> None:
        start, going = (
            (FulfillmentStatus.READY, FulfillmentStatus.PURCHASING)
            if phase == PHASE_PURCHASE
            else (FulfillmentStatus.PURCHASED, FulfillmentStatus.SHIPPING)
        )
        if not self._move(db, fulfillment, action, {start}, going):
            # Una acción que empieza sobre un fulfillment que no está donde debe (por ejemplo, se canceló justo
            # antes) se aborta antes de que la petición salga: la excepción deshace la transición de la acción.
            raise RuntimeError(
                f"fulfillment {fulfillment.id} is {fulfillment.status}, not {start.value}: the {phase} must not start"
            )

    def _done(
        self, db: Session, fulfillment: Fulfillment, action: ExternalAction, phase: str, response: ActionResponse | None
    ) -> None:
        reference = response.reference if response is not None else None
        if phase == PHASE_PURCHASE:
            moved = self._move(
                db,
                fulfillment,
                action,
                {FulfillmentStatus.PURCHASING, FulfillmentStatus.UNKNOWN_OUTCOME},
                FulfillmentStatus.PURCHASED,
                unknown_phase=None,
                purchased_at=_now(),
            )
            if moved and reference:
                try:
                    with db.begin_nested():
                        self._execute(
                            db,
                            update(Fulfillment)
                            .where(Fulfillment.id == fulfillment.id, Fulfillment.purchase_reference.is_(None))
                            .values(purchase_reference=reference),
                        )
                except IntegrityError:
                    self._anomaly(db, fulfillment, action, "purchase_reference_already_belongs_to_another_fulfillment")
        else:
            moved = self._move(
                db,
                fulfillment,
                action,
                {FulfillmentStatus.SHIPPING, FulfillmentStatus.UNKNOWN_OUTCOME},
                FulfillmentStatus.SHIPPED,
                unknown_phase=None,
                shipped_at=_now(),
                tracking_reference=reference,
            )
        if not moved:
            self._anomaly(db, fulfillment, action, f"{phase}_succeeded_after_the_fulfillment_moved_on")

    def _failed(self, db: Session, fulfillment: Fulfillment, action: ExternalAction, phase: str, previous: str) -> None:
        if previous == ActionStatus.PENDING.value:
            # La petición nunca salió: no hubo intento que contar. El fulfillment sigue donde estaba.
            if fulfillment.status not in (FulfillmentStatus.READY.value, FulfillmentStatus.PURCHASED.value):
                self._anomaly(db, fulfillment, action, f"{phase}_never_sent_but_the_fulfillment_moved_on")
            return
        code = "provider_rejected" if previous == ActionStatus.CALLING.value else "resolved_failed"
        if phase == PHASE_PURCHASE:
            expected = {FulfillmentStatus.PURCHASING, FulfillmentStatus.UNKNOWN_OUTCOME}
            target = FulfillmentStatus.READY
        else:
            expected = {FulfillmentStatus.SHIPPING, FulfillmentStatus.UNKNOWN_OUTCOME}
            target = FulfillmentStatus.PURCHASED
        moved = self._move(
            db,
            fulfillment,
            action,
            expected,
            target,
            unknown_phase=None,
            failed_attempts=Fulfillment.failed_attempts + 1,
            last_failure_code=f"{phase}:{code}",
        )
        if not moved:
            self._anomaly(db, fulfillment, action, f"{phase}_failed_after_the_fulfillment_moved_on")

    def _unknown(self, db: Session, fulfillment: Fulfillment, action: ExternalAction, phase: str) -> None:
        current = FulfillmentStatus.PURCHASING if phase == PHASE_PURCHASE else FulfillmentStatus.SHIPPING
        moved = self._move(db, fulfillment, action, {current}, FulfillmentStatus.UNKNOWN_OUTCOME, unknown_phase=phase)
        if not moved and fulfillment.status != FulfillmentStatus.UNKNOWN_OUTCOME.value:
            self._anomaly(db, fulfillment, action, f"{phase}_unknown_after_the_fulfillment_moved_on")

    # --- Interno -------------------------------------------------------------------------------------

    def _move(
        self,
        db: Session,
        fulfillment: Fulfillment,
        action: ExternalAction,
        expected: set[FulfillmentStatus],
        target: FulfillmentStatus,
        **values,
    ) -> bool:
        before = fulfillment.status
        result = self._execute(
            db,
            update(Fulfillment)
            .where(Fulfillment.id == fulfillment.id, Fulfillment.status.in_([s.value for s in expected]))
            .values(status=target.value, **values),
        )
        if result.rowcount != 1:
            return False
        db.refresh(fulfillment)
        db.add(
            AuditLog(
                actor=PROJECTION_ACTOR,
                action="fulfillment.status_changed",
                resource=f"fulfillment:{fulfillment.id}",
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
    def _anomaly(db: Session, fulfillment: Fulfillment, action: ExternalAction, what: str) -> None:
        db.add(
            AuditLog(
                actor=PROJECTION_ACTOR,
                action=f"fulfillment.anomaly.{what}",
                resource=f"fulfillment:{fulfillment.id}",
                before=None,
                after={
                    "fulfillment_status": fulfillment.status,
                    "external_action_id": action.id,
                    "action_status": action.status,
                },
                correlation_id=action.correlation_id,
            )
        )
