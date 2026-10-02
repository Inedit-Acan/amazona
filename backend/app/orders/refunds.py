"""Devolver dinero cobrado (Milestone 44, ADR 0028 §5 y §7).

Un reembolso es una **acción externa** (`payment.refund`) que ordena una persona con permiso. Ningún camino crea
reembolsos por su cuenta (plan maestro §33). Antes de salir pasa por, en este orden: las reglas del dominio (solo un
cobro con dinero capturado; moneda, céntimos, un motivo cerrado), la política operativa del proveedor (una operación no
declarada se deniega), el ActionGate (`REFUND`: kill switch, permiso `MONEY_REFUND`, identidad, y el veto de un
resultado desconocido de **sus** reembolsos; no consulta ni presupuesto ni vetos legales o económicos: devolver un
cobro es una obligación, no un gasto) y `ExternalAction` (identidad estable, frontera de durabilidad, resultado
desconocido explícito).

## El límite lo pone la base de datos

El importe se **aparta** del cobro con una sola sentencia (`app/payments/ledger.py`): `refund_committed_amount +=
:a` solo si cabe en lo capturado. Dos reembolsos a la vez no pueden pasarse de lo cobrado aunque ninguno vea al otro.
Lo apartado se libera **solo** cuando se sabe que el reembolso no ocurrió (un fallo confirmado); un resultado
desconocido lo mantiene.

## Qué cambia en el pedido

Nada. Devolver dinero no cancela ni reabre un pedido: el pedido sigue siendo lo que era y el reembolso queda
registrado junto al cobro. Se puede devolver el dinero de una captura duplicada, de un importe distinto o de un cobro
tardío sobre un pedido cancelado: justo los casos en que alguien tiene que mirar.
"""

import datetime
from collections.abc import Callable
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.actions.service import ExternalActionService, ExternalActionStateError
from app.core.config import Settings, get_settings
from app.core.errors import (
    ConflictError,
    ExternalActionFailedError,
    ExternalOutcomeUnknownError,
    NotFoundError,
    PipelineDisabledError,
    ValidationError,
)
from app.core.ids import new_correlation_id
from app.db.models.order import Order
from app.db.models.payment import Payment, Refund
from app.gates.action_gate import GateOutcome, SideEffectAction
from app.gates.service import ActionGateService
from app.integrations.operating_policy import require_operation
from app.integrations.ports import IntegrationDomain
from app.integrations.registry import ProviderRegistry
from app.money.money import Money
from app.orders.domain import require_cents
from app.orders.errors import OperationNotAllowedError, OutcomeUnknownBlockError
from app.orders.payment_attempts import Requester, close_unsent_action
from app.payments import ledger
from app.payments.domain import (
    CAPTURED_PAYMENT_STATUSES,
    REFUND_ORIGIN_OPERATOR,
    REFUND_REASONS,
    RefundStatus,
)
from app.payments.port import OPERATION_REFUND, PaymentProvider
from app.payments.refund_projection import refund_reference


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


class RefundService:
    def __init__(
        self,
        db: Session,
        *,
        settings: Settings | None = None,
        provider: PaymentProvider | None = None,
        gate: ActionGateService | None = None,
        actions: ExternalActionService | None = None,
        clock: Callable[[], datetime.datetime] = _utcnow,
    ) -> None:
        self._db = db
        self._settings = settings or get_settings()
        self._provider = provider
        self._gate = gate or ActionGateService(db, settings=self._settings)
        self._actions = actions or ExternalActionService(db)
        self._clock = clock

    def request(
        self, payment_id: str, *, amount: Money, reason: str, requester: Requester, order_id: str | None = None
    ) -> Refund:
        """Pide devolver `amount` de un cobro. Devuelve el reembolso: `SENDING` (aceptado por el proveedor, a la espera
        de su confirmación verificada), `UNKNOWN_OUTCOME` (pudo salir y no se sabe) o `FAILED` (confirmado: no hubo
        devolución). Lanza un error y no cambia nada si el dominio o el gate no lo permiten."""
        provider = self._resolve_provider()
        require_operation(provider.name, OPERATION_REFUND, self._settings)
        if reason not in REFUND_REASONS:
            raise ValidationError(f"reason must be one of {', '.join(sorted(REFUND_REASONS))}")
        require_cents(amount, "a refund")
        if amount.amount <= 0:
            raise ValidationError("a refund must be for more than zero")

        payment = self._lock_payment(payment_id)
        if order_id is not None and payment.order_id != order_id:
            raise NotFoundError(f"payment {payment_id} not found in order {order_id}")
        self._check_payment(payment, provider, amount)
        unresolved = self._unknown_refund(payment.id)

        decision = self._gate.evaluate(
            SideEffectAction.REFUND,
            actor_role=requester.role,
            unresolved_outcome=unresolved,
        )
        self._gate.audit(
            decision,
            action=SideEffectAction.REFUND,
            resource=f"payment:{payment.id}",
            correlation_id=payment.correlation_id,
            actor=requester.name,
        )
        if decision.outcome is not GateOutcome.ALLOW:
            self._db.commit()  # el rastro de lo que el gate impidió
            message = "the refund cannot be made: " + "; ".join(decision.reasons)
            if unresolved:
                raise OutcomeUnknownBlockError(message)
            raise OperationNotAllowedError(
                message,
                reasons=decision.reasons,
                requires_approval=decision.outcome is GateOutcome.REQUIRE_APPROVAL,
            )

        value = amount.amount
        # La reserva y el reembolso nacen juntos: o están los dos o no existe ninguno.
        if not ledger.reserve(self._db, payment.id, value):
            self._db.rollback()
            raise ConflictError(
                f"payment {payment_id} has less than {value} left to refund "
                "(what is already refunded or being refunded counts)"
            )
        refund = Refund(
            payment_id=payment.id,
            provider=provider.name,
            origin=REFUND_ORIGIN_OPERATOR,
            status=RefundStatus.REQUESTED.value,
            amount=value,
            currency=payment.currency,
            reason=reason,
            requested_by=requester.name,
            correlation_id=new_correlation_id(),
            requested_at=self._clock(),
        )
        self._db.add(refund)
        self._db.flush()
        payload = {
            "refund_id": refund.id,
            "payment_id": payment.id,
            "provider_payment_ref": payment.provider_payment_ref,
            "amount": f"{value:.2f}",
            "currency": payment.currency,
        }
        action = self._actions.open(
            reference=refund_reference(refund.id),
            adapter=provider,
            operation=OPERATION_REFUND,
            amount=None,
            payload=payload,
            correlation_id=refund.correlation_id,
        )
        self._db.commit()  # el reembolso `REQUESTED`, su importe apartado y su acción `PENDING`: no ha salido nada

        refund_id = refund.id
        try:
            self._actions.execute(action, provider, payload)
        except ExternalActionFailedError:
            pass  # el proveedor confirmó que no hubo devolución: el observador ya liberó lo apartado
        except ExternalOutcomeUnknownError:
            pass  # pudo ejecutarse: el reembolso queda UNKNOWN_OUTCOME y su importe, apartado
        except PipelineDisabledError as exc:
            close_unsent_action(self._db, self._actions, action)  # el kill switch se apagó justo antes: no salió nada
            raise OperationNotAllowedError(str(exc), reasons=["the pipeline kill switch is off"]) from exc
        except ExternalActionStateError as exc:
            # La referencia de la acción es la de **este** reembolso (`order_refund:{id}`), que solo esta petición
            # conoce: quien se la pudo mover es el barrido de huérfanas (la cerró como «nunca salió» y liberó el importe
            # apartado) o una persona. No es un fallo de esta petición ni un resultado desconocido: el estado del
            # reembolso, y no esta respuesta, cuenta lo que pasó.
            self._db.rollback()
            raise ConflictError(
                f"refund {refund_id}: another process already moved the operation that sends it "
                "(for example the reconciler released it before it was sent); look at the state of the refund"
            ) from exc
        self._db.refresh(refund)
        return refund

    # --- Reglas del dominio -------------------------------------------------------------------------

    def _check_payment(self, payment: Payment, provider: PaymentProvider, amount: Money) -> None:
        if payment.status not in CAPTURED_PAYMENT_STATUSES:
            raise ConflictError(
                f"payment {payment.id} is {payment.status}: only a payment with money captured can be refunded"
            )
        if payment.provider != provider.name:
            raise ConflictError(f"payment {payment.id} was taken by {payment.provider}, not by {provider.name}")
        if not payment.provider_payment_ref:
            raise ConflictError(f"payment {payment.id} has no provider reference: the provider cannot refund it")
        if amount.currency != payment.currency:
            raise ValidationError(f"payment {payment.id} is in {payment.currency}, not in {amount.currency}")
        free = Decimal(str(payment.captured_amount)) - Decimal(str(payment.refund_committed_amount))
        if amount.amount > free:
            raise ConflictError(
                f"payment {payment.id} has {free} left to refund (what is already refunded or being refunded counts), "
                f"not {amount.amount}"
            )

    def _unknown_refund(self, payment_id: str) -> bool:
        return (
            self._db.scalar(
                select(Refund.id)
                .where(Refund.payment_id == payment_id, Refund.status == RefundStatus.UNKNOWN_OUTCOME.value)
                .limit(1)
            )
            is not None
        )

    def _lock_payment(self, payment_id: str) -> Payment:
        found = self._db.get(Payment, payment_id)
        if found is None:
            raise NotFoundError(f"payment {payment_id} not found")
        # El mismo orden de bloqueos que el resto (pedido, luego cobro): un evento y un reembolso a la vez no se cruzan.
        self._db.scalars(
            select(Order)
            .where(Order.id == found.order_id)
            .with_for_update(key_share=True)
            .execution_options(populate_existing=True)
        ).one()
        return self._db.scalars(
            select(Payment).where(Payment.id == payment_id).with_for_update().execution_options(populate_existing=True)
        ).one()

    def _resolve_provider(self) -> PaymentProvider:
        if self._provider is not None:
            return self._provider
        return ProviderRegistry(self._settings).resolve(IntegrationDomain.PAYMENTS)  # type: ignore[return-value]
