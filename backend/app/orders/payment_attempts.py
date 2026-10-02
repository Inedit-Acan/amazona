"""Abrir un intento de cobro de un pedido (Milestone 44, ADR 0028 §2 y §7).

Un intento es una **acción externa** (`payment.open`): crea un cobro en el proveedor. No gasta presupuesto, pero no
es una acción sin gobierno. Antes de salir pasa por, en este orden: el estado del pedido y las reglas del dominio
(un intento activo como mucho; nunca otro cobro si ya hay dinero capturado), la política operativa del proveedor
(una operación no declarada se deniega), el ActionGate (`COLLECT_PAYMENT`: kill switch, veto legal, permiso e
identidad) y `ExternalAction` (identidad estable, frontera de durabilidad, resultado desconocido explícito).

**Misma intención o intento nuevo.** La `Idempotency-Key` de la ruta identifica la intención (misma clave, mismo
cobro). Aquí, otro intento con el anterior todavía vivo es un 409 que lo nombra; con todos los anteriores terminados,
`attempt_number + 1`. Hacia el proveedor, la clave sale de `(order_payment:{payment_id}, sequence)`: un reintento tras
una caída reutiliza la misma operación, y un intento nuevo es otra fila y otra clave.

**Un intento de resultado desconocido bloquea los nuevos** (es un intento activo) hasta que se reconcilia, llega la
respuesta tardía o una persona lo resuelve (`resolve-action`).
"""

import datetime
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.actions.service import ExternalActionService
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
from app.db.models.payment import Payment
from app.gates.action_gate import GateOutcome, SideEffectAction
from app.gates.service import ActionGateService
from app.integrations.operating_policy import require_operation
from app.integrations.ports import IntegrationDomain
from app.integrations.registry import ProviderRegistry
from app.orders.domain import OrderStatus
from app.orders.errors import OperationNotAllowedError, OutcomeUnknownBlockError
from app.orders.gate_inputs import recommendations_for, require_legal_analysis_outside_simulation
from app.payments.domain import ACTIVE_PAYMENT_STATUSES, PaymentStatus
from app.payments.port import OPERATION_OPEN, PaymentProvider
from app.payments.projection import payment_reference


@dataclass(frozen=True)
class Requester:
    """Quién pide. `role` es `None` cuando no hay identidad verificada: en una simulación no hay permisos que
    consultar; fuera de ella, no saber quién pide no es un permiso (lo decide el gate)."""

    name: str
    role: str | None = None


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


class PaymentAttemptService:
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

    def start(self, order_id: str, *, requester: Requester) -> Payment:
        provider = self._resolve_provider()
        require_operation(provider.name, OPERATION_OPEN, self._settings)

        order = self._lock_order(order_id)
        self._check_order(order, provider)
        recommendations = recommendations_for(self._db, order)
        require_legal_analysis_outside_simulation(recommendations, self._settings)

        decision = self._gate.evaluate(
            SideEffectAction.COLLECT_PAYMENT,
            legal_recommendation=recommendations.legal,
            economics_recommendation=None,
            actor_role=requester.role,
        )
        self._gate.audit(
            decision,
            action=SideEffectAction.COLLECT_PAYMENT,
            resource=f"order:{order.id}",
            correlation_id=order.correlation_id,
            actor=requester.name,
        )
        if decision.outcome is not GateOutcome.ALLOW:
            self._db.commit()  # el rastro de lo que el gate impidió
            raise OperationNotAllowedError(
                "the payment cannot be opened: " + "; ".join(decision.reasons),
                reasons=decision.reasons,
                requires_approval=decision.outcome is GateOutcome.REQUIRE_APPROVAL,
            )

        payment = Payment(
            order_id=order.id,
            attempt_number=self._next_attempt(order.id),
            provider=provider.name,
            status=PaymentStatus.REQUESTED.value,
            amount=order.amount_due,
            currency=order.currency,
            correlation_id=new_correlation_id(),
        )
        self._db.add(payment)
        self._db.flush()
        payload = {
            "payment_id": payment.id,
            "order_id": order.id,
            "amount": f"{Decimal(str(order.amount_due)):.2f}",
            "currency": order.currency,
        }
        action = self._actions.open(
            reference=payment_reference(payment.id),
            adapter=provider,
            operation=OPERATION_OPEN,
            amount=None,
            payload=payload,
            correlation_id=payment.correlation_id,
        )
        self._db.commit()  # el cobro `REQUESTED` y su acción `PENDING`: todavía no ha salido nada

        try:
            self._actions.execute(action, provider, payload)
        except ExternalActionFailedError:
            pass  # el proveedor confirmó que no hubo cobro: el observador ya dejó el intento en FAILED
        except ExternalOutcomeUnknownError:
            pass  # pudo ejecutarse: el intento queda UNKNOWN_OUTCOME y bloquea los nuevos
        except PipelineDisabledError as exc:
            self._actions.finish_unstarted(action)  # el kill switch se apagó justo antes: no salió nada
            raise OperationNotAllowedError(str(exc), reasons=["the pipeline kill switch is off"]) from exc
        self._db.refresh(payment)
        return payment

    # --- Reglas del dominio -------------------------------------------------------------------------

    def _check_order(self, order: Order, provider: PaymentProvider) -> None:
        if order.status != OrderStatus.AWAITING_PAYMENT.value:
            raise ConflictError(f"order {order.id} is {order.status}: only an order awaiting payment can be charged")
        if order.currency not in provider.capabilities.currencies:
            raise ValidationError(f"{provider.name} does not charge in {order.currency}")
        payments = list(self._db.scalars(select(Payment).where(Payment.order_id == order.id)))
        if any(Decimal(str(p.captured_amount)) > 0 for p in payments):
            raise ConflictError(
                f"order {order.id} already has money captured: refund or reconcile it before charging again"
            )
        active = [p for p in payments if p.status in ACTIVE_PAYMENT_STATUSES]
        if active:
            current = active[0]
            message = (
                f"payment attempt {current.attempt_number} of order {order.id} is still {current.status}: "
                "a new attempt waits until it ends"
            )
            if current.status == PaymentStatus.UNKNOWN_OUTCOME.value:
                raise OutcomeUnknownBlockError(
                    message + " (its outcome is unknown: reconcile it, wait for the late response, or resolve it)"
                )
            raise ConflictError(message)

    def _next_attempt(self, order_id: str) -> int:
        highest = self._db.scalar(select(func.max(Payment.attempt_number)).where(Payment.order_id == order_id))
        return (highest or 0) + 1

    def _lock_order(self, order_id: str) -> Order:
        order = self._db.scalars(
            select(Order)
            .where(Order.id == order_id)
            .with_for_update(key_share=True)
            .execution_options(populate_existing=True)
        ).one_or_none()
        if order is None:
            raise NotFoundError(f"order {order_id} not found")
        return order

    def _resolve_provider(self) -> PaymentProvider:
        if self._provider is not None:
            return self._provider
        return ProviderRegistry(self._settings).resolve(IntegrationDomain.PAYMENTS)  # type: ignore[return-value]
