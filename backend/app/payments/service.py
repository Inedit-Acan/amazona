"""`PaymentService`: el único sitio donde un evento de pago verificado cambia dinero (Milestone 44, ADR 0028).

Lo llama la puerta (`PaymentIngress`) para un evento simulado y para el webhook de una pasarela real: **es la misma
lógica y la misma máquina de estados**. Nada más escribe el estado de un cobro (salvo el observador de la acción
`payment.open`, que refleja lo que pasó al abrirlo), y nada más pone un pedido en `PAID`.

## Una sola transacción por evento

El evento ya está guardado (`RECEIVED`, transacción 1). Aquí, en una sola transacción, se **reclama** (nadie más lo
aplica a la vez), se aplican los efectos sobre el cobro y el pedido, y se marca su resultado. Si el proceso muere a
mitad, la transacción se deshace y el evento sigue `RECEIVED`: la reentrega del proveedor, o
`reconcile-payment-events`, lo reanuda. No existe «medio aplicado».

## La evidencia financiera nunca se descarta

Una captura es dinero recibido. Se registra en cualquier estado salvo `REQUESTED` (de ahí no pudo salir nada), también
tarde (tras un `FAILED` o `EXPIRED`), también si el pedido ya está cobrado (`DUPLICATE_CAPTURE`), cancelado
(el cobro se registra y el pedido **no** vuelve a `PAID`) o si el importe no es el esperado (`CAPTURE_MISMATCH`). El
sistema no «arregla» el pedido por su cuenta: lo marca para que una persona lo mire. Lo único que no se puede
registrar es un dinero sin importe; el evento se conserva entero igualmente.

Un evento que describe algo que ya no cambia nada es `STALE`; uno que contradice un hecho ya registrado, o que no se
puede aplicar sin inventar, es `CONFLICT` y se conserva con su importe y su moneda para que la contabilidad lo vea.
"""

import datetime
from collections.abc import Callable
from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.db.models.audit import AuditLog
from app.db.models.order import Order
from app.db.models.payment import Payment, PaymentEvent, Refund
from app.orders.domain import OrderStatus
from app.payments import ledger
from app.payments.domain import (
    CAPTURE_ACCEPTING_STATUSES,
    CAPTURED_PAYMENT_STATUSES,
    CLOSABLE_PAYMENT_STATUSES,
    REFUND_ORIGIN_PROVIDER,
    EventProcessing,
    PaymentStatus,
    RefundStatus,
)
from app.payments.port import PaymentEventType

PAYMENTS_ACTOR = "payments"

_REFUND_EVENTS = frozenset({PaymentEventType.REFUND_SUCCEEDED, PaymentEventType.REFUND_FAILED})


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


def _dec(value: object) -> Decimal:
    return Decimal(str(value))


def _aware(value: datetime.datetime) -> datetime.datetime:
    """SQLite devuelve fechas sin zona; todas las que se guardan son UTC."""
    return value if value.tzinfo is not None else value.replace(tzinfo=datetime.UTC)


class PaymentService:
    def __init__(self, db: Session, *, clock: Callable[[], datetime.datetime] = _utcnow) -> None:
        self._db = db
        self._clock = clock

    # --- Aplicar un evento verificado ----------------------------------------------------------

    def apply(self, event_id: str) -> str:
        """Aplica un evento guardado y devuelve su resultado (`EventProcessing`). Idempotente: uno ya aplicado no
        vuelve a hacer nada."""
        event = self._db.get(PaymentEvent, event_id)
        if event is None:
            raise NotFoundError(f"payment event {event_id} not found")
        if event.processing_status != EventProcessing.RECEIVED.value:
            return event.processing_status

        # Reclamo: el UPDATE toma el bloqueo de la fila. Quien llegue después espera a que esta transacción
        # termine y ve el resultado final (`rowcount == 0`). El valor provisional nunca se confirma: se
        # sobrescribe antes del commit.
        claim = self._execute(
            update(PaymentEvent)
            .where(PaymentEvent.id == event.id, PaymentEvent.processing_status == EventProcessing.RECEIVED.value)
            .values(processing_status=EventProcessing.APPLIED.value)
        )
        if claim.rowcount != 1:
            self._db.rollback()
            self._db.expire_all()
            return self._db.get(PaymentEvent, event_id).processing_status  # type: ignore[union-attr]

        try:
            outcome, note, payment, refund = self._dispatch(event)
            self._finish(event, outcome, note, payment, refund)
            self._db.commit()
        except BaseException:
            self._db.rollback()  # el evento sigue RECEIVED: se reanuda
            raise
        return outcome.value

    # --- Reparto ---------------------------------------------------------------------------------

    def _dispatch(self, event: PaymentEvent) -> tuple[EventProcessing, str | None, Payment | None, Refund | None]:
        kind = PaymentEventType(event.event_type)
        refund = self._find_refund(event)
        payment = self._find_payment(event, refund)
        if payment is None:
            self._audit(event, "payment_event.unmatched", {"event_type": event.event_type})
            return EventProcessing.UNMATCHED, "no payment of ours matches this event", None, refund

        order = self._lock_order(payment.order_id)
        self._db.refresh(payment)
        if refund is not None:
            self._db.refresh(refund)
        if refund is not None and refund.payment_id != payment.id:
            self._audit(event, "payment_event.refund_of_another_payment", {"refund_id": refund.id}, payment)
            return EventProcessing.CONFLICT, "the refund belongs to another payment", payment, refund
        self._attach_provider_ref(event, payment)
        if refund is not None:
            self._attach_provider_refund_ref(event, refund)

        if kind is PaymentEventType.PAYMENT_ATTEMPT_FAILED:
            outcome, note = self._attempt_failed(event, payment)
        elif kind is PaymentEventType.PAYMENT_FAILED:
            outcome, note = self._close(event, payment, PaymentStatus.FAILED)
        elif kind is PaymentEventType.PAYMENT_EXPIRED:
            outcome, note = self._close(event, payment, PaymentStatus.EXPIRED)
        elif kind is PaymentEventType.PAYMENT_SUCCEEDED:
            outcome, note = self._capture(event, payment, order)
        elif kind is PaymentEventType.REFUND_SUCCEEDED:
            outcome, note, refund = self._refund_succeeded(event, payment, refund)
        else:
            outcome, note = self._refund_failed(event, payment, refund)
        self._touch(payment, event)
        return outcome, note, payment, refund

    # --- Emparejar --------------------------------------------------------------------------------

    def _find_refund(self, event: PaymentEvent) -> Refund | None:
        if event.provider_refund_ref:
            found = self._db.scalars(
                select(Refund).where(
                    Refund.provider == event.provider, Refund.provider_refund_ref == event.provider_refund_ref
                )
            ).one_or_none()
            if found is not None:
                return found
        if event.client_reference and PaymentEventType(event.event_type) in _REFUND_EVENTS:
            # Nuestro `refund_id`, que le enviamos al pedir la devolución: empareja el evento aunque la respuesta de
            # pedirla se perdiera y no guardáramos la referencia del proveedor.
            candidate = self._db.get(Refund, event.client_reference)
            if candidate is not None and candidate.provider == event.provider:
                return candidate
        return None

    def _find_payment(self, event: PaymentEvent, refund: Refund | None) -> Payment | None:
        if refund is not None:
            return self._db.get(Payment, refund.payment_id)
        if event.provider_payment_ref:
            found = self._db.scalars(
                select(Payment).where(
                    Payment.provider == event.provider, Payment.provider_payment_ref == event.provider_payment_ref
                )
            ).one_or_none()
            if found is not None:
                return found
        if event.client_reference:
            candidate = self._db.get(Payment, event.client_reference)
            if candidate is not None and candidate.provider == event.provider:
                return candidate
        return None

    def _attach_provider_ref(self, event: PaymentEvent, payment: Payment) -> None:
        """Si el cobro no guardó la referencia del proveedor (la respuesta de abrirlo se perdió) y el evento la trae,
        se enlaza: así los siguientes eventos ya se emparejan por ella."""
        if payment.provider_payment_ref is None and event.provider_payment_ref:
            try:
                with self._db.begin_nested():
                    self._execute(
                        update(Payment)
                        .where(Payment.id == payment.id, Payment.provider_payment_ref.is_(None))
                        .values(provider_payment_ref=event.provider_payment_ref)
                    )
                self._db.refresh(payment)
            except IntegrityError:
                pass  # la referencia ya es de otro cobro: no se enlaza, y el evento se tratará por su cuenta

    def _attach_provider_refund_ref(self, event: PaymentEvent, refund: Refund) -> None:
        """Lo mismo para un reembolso cuya respuesta se perdió: el evento trae la referencia y se enlaza."""
        if refund.provider_refund_ref is None and event.provider_refund_ref:
            try:
                with self._db.begin_nested():
                    self._execute(
                        update(Refund)
                        .where(Refund.id == refund.id, Refund.provider_refund_ref.is_(None))
                        .values(provider_refund_ref=event.provider_refund_ref)
                    )
                self._db.refresh(refund)
            except IntegrityError:
                pass  # la referencia ya es de otro reembolso: no se enlaza

    def _lock_order(self, order_id: str) -> Order:
        return self._db.scalars(
            select(Order)
            .where(Order.id == order_id)
            .with_for_update(key_share=True)
            .execution_options(populate_existing=True)
        ).one()

    # --- Eventos de cobro -------------------------------------------------------------------------

    def _attempt_failed(self, event: PaymentEvent, payment: Payment) -> tuple[EventProcessing, str | None]:
        if payment.status in CAPTURED_PAYMENT_STATUSES or payment.status in (
            PaymentStatus.FAILED.value,
            PaymentStatus.EXPIRED.value,
        ):
            return EventProcessing.STALE, "the payment is already settled"
        self._execute(
            update(Payment).where(Payment.id == payment.id).values(last_failure_code=self._failure_code(event))
        )
        return EventProcessing.APPLIED, "an attempt failed; the payment stays open"

    def _close(
        self, event: PaymentEvent, payment: Payment, target: PaymentStatus
    ) -> tuple[EventProcessing, str | None]:
        if payment.status in CLOSABLE_PAYMENT_STATUSES:
            self._execute(
                update(Payment)
                .where(Payment.id == payment.id, Payment.status.in_(CLOSABLE_PAYMENT_STATUSES))
                .values(status=target.value, closed_at=self._clock(), last_failure_code=self._failure_code(event))
            )
            self._audit(event, f"payment.{target.value.lower()}", {"payment_id": payment.id}, payment)
            return EventProcessing.APPLIED, None
        if payment.status in (PaymentStatus.FAILED.value, PaymentStatus.EXPIRED.value):
            return EventProcessing.STALE, "the payment was already closed"
        if payment.status == PaymentStatus.REQUESTED.value:
            return EventProcessing.CONFLICT, "nothing had been sent for this payment"
        self._audit(event, "payment.closing_event_after_capture", {"payment_id": payment.id}, payment)
        return EventProcessing.CONFLICT, "the event contradicts a capture already recorded"

    def _capture(self, event: PaymentEvent, payment: Payment, order: Order) -> tuple[EventProcessing, str | None]:
        if event.amount is None or event.currency != payment.currency:
            return (
                EventProcessing.CONFLICT,
                "a capture without an amount, or in another currency, cannot be recorded as money; the event is kept",
            )
        amount = _dec(event.amount)
        if payment.status == PaymentStatus.REQUESTED.value:
            return EventProcessing.CONFLICT, "nothing had been sent for this payment"
        if payment.status in CAPTURED_PAYMENT_STATUSES:
            if _dec(payment.captured_amount) == amount:
                return EventProcessing.STALE, "this capture was already recorded for the payment"
            self._audit(event, "payment.second_capture_event_with_another_amount", {"payment_id": payment.id}, payment)
            return EventProcessing.CONFLICT, "a second capture event with another amount for the same payment"
        assert payment.status in CAPTURE_ACCEPTING_STATUSES

        if amount != _dec(payment.amount):
            self._record_capture(payment, event, PaymentStatus.CAPTURE_MISMATCH, amount)
            self._audit(
                event,
                "payment.capture_mismatch",
                {"payment_id": payment.id, "expected": str(payment.amount), "captured": str(amount)},
                payment,
            )
            return EventProcessing.APPLIED, "a capture of a different amount was recorded; nothing else changed"

        canonical = self._canonical_payment(payment)
        status = PaymentStatus.SUCCEEDED
        if canonical is None:
            try:
                with self._db.begin_nested():
                    self._record_capture(payment, event, PaymentStatus.SUCCEEDED, amount)
            except IntegrityError:
                # Otro cobro del pedido se hizo canónico entre medias: la evidencia no se descarta, se registra aquí.
                canonical = self._canonical_payment(payment)
        if canonical is not None:
            status = PaymentStatus.DUPLICATE_CAPTURE
            self._record_capture(payment, event, status, amount, duplicate_of=canonical.id)
            self._audit(
                event,
                "payment.duplicate_capture",
                {"payment_id": payment.id, "canonical_payment_id": canonical.id, "captured": str(amount)},
                payment,
            )
            return EventProcessing.APPLIED, "an additional real capture was recorded; the order is unchanged"

        return self._mark_order_paid(event, payment, order)

    def _mark_order_paid(
        self, event: PaymentEvent, payment: Payment, order: Order
    ) -> tuple[EventProcessing, str | None]:
        self._audit(event, "payment.captured", {"payment_id": payment.id, "order_id": order.id}, payment)
        if order.status == OrderStatus.AWAITING_PAYMENT.value:
            self._execute(
                update(Order)
                .where(Order.id == order.id, Order.status == OrderStatus.AWAITING_PAYMENT.value)
                .values(status=OrderStatus.PAID.value, paid_at=self._clock())
            )
            return EventProcessing.APPLIED, None
        if order.status == OrderStatus.CANCELLED.value:
            self._audit(event, "payment.late_capture_on_cancelled_order", {"payment_id": payment.id}, payment)
            return EventProcessing.APPLIED, "the money was recorded; the cancelled order was not reopened"
        return EventProcessing.APPLIED, "the money was recorded; the order was already past payment"

    def _canonical_payment(self, payment: Payment) -> Payment | None:
        return self._db.scalars(
            select(Payment).where(
                Payment.order_id == payment.order_id,
                Payment.id != payment.id,
                Payment.status == PaymentStatus.SUCCEEDED.value,
            )
        ).first()

    def _record_capture(
        self,
        payment: Payment,
        event: PaymentEvent,
        status: PaymentStatus,
        amount: Decimal,
        *,
        duplicate_of: str | None = None,
    ) -> None:
        now = self._clock()
        result = self._execute(
            update(Payment)
            .where(Payment.id == payment.id, Payment.status.in_(CAPTURE_ACCEPTING_STATUSES))
            .values(
                status=status.value,
                captured_amount=amount,
                succeeded_at=event.occurred_at,
                closed_at=now,
                duplicate_of_payment_id=duplicate_of,
            )
        )
        if result.rowcount != 1:
            raise RuntimeError(f"payment {payment.id} changed while its capture was being recorded")
        self._db.flush()
        self._db.refresh(payment)

    # --- Eventos de reembolso ---------------------------------------------------------------------

    def _refund_succeeded(
        self, event: PaymentEvent, payment: Payment, refund: Refund | None
    ) -> tuple[EventProcessing, str | None, Refund | None]:
        if event.amount is None or event.currency != payment.currency:
            return EventProcessing.CONFLICT, "a refund without an amount, or in another currency, is only kept", refund
        amount = _dec(event.amount)
        if refund is None:
            return self._provider_refund(event, payment, amount)
        if refund.status == RefundStatus.SUCCEEDED.value:
            return EventProcessing.STALE, "this refund was already recorded", refund
        if refund.status == RefundStatus.FAILED.value:
            self._audit(event, "refund.success_after_failure", {"refund_id": refund.id}, payment)
            return EventProcessing.CONFLICT, "the provider says it refunded what was recorded as failed", refund
        if amount != _dec(refund.amount):
            return EventProcessing.CONFLICT, "the refunded amount differs from the one requested", refund
        moved = self._execute(
            update(Refund)
            .where(Refund.id == refund.id, Refund.status != RefundStatus.SUCCEEDED.value)
            .values(status=RefundStatus.SUCCEEDED.value, finished_at=self._clock())
        )
        if moved.rowcount == 1 and ledger.settle(self._db, payment.id, amount):
            self._audit(event, "refund.succeeded", {"refund_id": refund.id, "amount": str(amount)}, payment)
            return EventProcessing.APPLIED, None, refund
        raise RuntimeError(f"refund {refund.id} could not be settled against payment {payment.id}")

    def _provider_refund(
        self, event: PaymentEvent, payment: Payment, amount: Decimal
    ) -> tuple[EventProcessing, str | None, Refund | None]:
        """Un reembolso que el proveedor hizo y que no iniciamos nosotros (por ejemplo, desde su panel)."""
        if not ledger.reserve_and_settle(self._db, payment.id, amount):
            self._audit(event, "refund.provider_refund_does_not_fit", {"amount": str(amount)}, payment)
            return (
                EventProcessing.CONFLICT,
                "a refund by the provider that does not fit within what was captured: the event is kept as evidence",
                None,
            )
        refund = Refund(
            payment_id=payment.id,
            provider=event.provider,
            origin=REFUND_ORIGIN_PROVIDER,
            status=RefundStatus.SUCCEEDED.value,
            amount=amount,
            currency=payment.currency,
            reason="provider_initiated",
            provider_refund_ref=event.provider_refund_ref,
            correlation_id=payment.correlation_id,
            requested_at=event.occurred_at,
            finished_at=self._clock(),
        )
        self._db.add(refund)
        self._db.flush()
        self._audit(event, "refund.provider_initiated", {"refund_id": refund.id, "amount": str(amount)}, payment)
        return EventProcessing.APPLIED, "a refund started by the provider was recorded", refund

    def _refund_failed(
        self, event: PaymentEvent, payment: Payment, refund: Refund | None
    ) -> tuple[EventProcessing, str | None]:
        if refund is None:
            return EventProcessing.UNMATCHED, "no refund of ours matches this event"
        if refund.status == RefundStatus.FAILED.value:
            return EventProcessing.STALE, "this refund was already recorded as failed"
        if refund.status == RefundStatus.SUCCEEDED.value:
            self._audit(event, "refund.failure_after_success", {"refund_id": refund.id}, payment)
            return EventProcessing.CONFLICT, "the event contradicts a refund already recorded as done"
        moved = self._execute(
            update(Refund)
            .where(
                Refund.id == refund.id,
                Refund.status.in_(
                    [RefundStatus.REQUESTED.value, RefundStatus.SENDING.value, RefundStatus.UNKNOWN_OUTCOME.value]
                ),
            )
            .values(status=RefundStatus.FAILED.value, finished_at=self._clock(), failure_code=self._failure_code(event))
        )
        if moved.rowcount == 1 and ledger.release(self._db, payment.id, _dec(refund.amount)):
            self._audit(event, "refund.failed", {"refund_id": refund.id}, payment)
            return EventProcessing.APPLIED, None
        raise RuntimeError(f"refund {refund.id} could not be released from payment {payment.id}")

    # --- Interno ------------------------------------------------------------------------------------

    @staticmethod
    def _failure_code(event: PaymentEvent) -> str | None:
        code = (event.data or {}).get("failure_code")
        return str(code)[:64] if code else None

    def _touch(self, payment: Payment, event: PaymentEvent) -> None:
        """`last_event_at` = el hecho más reciente que se ha visto (no el último que llegó)."""
        self._db.refresh(payment)
        latest = payment.last_event_at
        if latest is None or _aware(event.occurred_at) > _aware(latest):
            self._execute(update(Payment).where(Payment.id == payment.id).values(last_event_at=event.occurred_at))

    def _finish(
        self,
        event: PaymentEvent,
        outcome: EventProcessing,
        note: str | None,
        payment: Payment | None,
        refund: Refund | None,
    ) -> None:
        self._execute(
            update(PaymentEvent)
            .where(PaymentEvent.id == event.id)
            .values(
                processing_status=outcome.value,
                processed_at=self._clock(),
                note=(note or None) and note[:500],
                payment_id=payment.id if payment is not None else None,
                refund_id=refund.id if refund is not None else None,
            )
        )
        self._audit(
            event,
            f"payment_event.{outcome.value.lower()}",
            {"event_type": event.event_type, "payment_id": payment.id if payment else None, "note": note},
            payment,
        )

    def _audit(self, event: PaymentEvent, action: str, after: dict, payment: Payment | None = None) -> None:
        self._db.add(
            AuditLog(
                actor=PAYMENTS_ACTOR,
                action=action,
                resource=f"payment_event:{event.id}",
                before=None,
                after={**after, "provider": event.provider, "provider_event_id": event.provider_event_id},
                correlation_id=payment.correlation_id if payment is not None else event.id,
            )
        )

    def _execute(self, statement) -> CursorResult:
        result = self._db.execute(statement.execution_options(synchronize_session=False))
        assert isinstance(result, CursorResult)
        return result
