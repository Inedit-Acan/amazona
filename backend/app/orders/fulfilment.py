"""Comprar al proveedor y enviar un pedido pagado (Milestone 44, ADR 0028 §6 y §7).

Cuatro decisiones de una persona (`create`, `complete`, `cancel`, `fail`) y dos **acciones externas** (`purchase`,
`ship`). Ninguna sale sin pasar, en este orden, por: el estado del pedido y del fulfillment (solo un pedido **pagado**
y que no se ha reembolsado; un resultado desconocido bloquea), la política operativa del proveedor, el ActionGate
(`PURCHASE_SUPPLIER` / `SHIP_ORDER`, con el **coste de esa operación** que declara el adaptador: un coste desconocido
nunca se trata como cero) y `ExternalAction` (identidad estable, frontera de durabilidad, resultado desconocido
explícito).

## Qué cuesta cada fase y cómo se gobierna

La compra suma el coste de las líneas (desconocido si falta alguno) y gasta presupuesto como cualquier compra; el envío
de un adaptador simulado es cero **declarado y simulado** (no hay transportista ni tarifa). Cuando el gate responde
`REQUIRE_APPROVAL`, M44 no tiene bandeja de aprobación de pedidos: devuelve 409 con los motivos y no ejecuta nada.

## Una unidad comprada no vuelve al pool

`cancel` y `fail` solo funcionan sobre un fulfillment `READY` sin compra y sin resultado desconocido, y devuelven las
unidades con `release_allocation()` (`app/orders/allocation.py`), un compare-and-set. Comprar y cancelar a la vez no
pueden ganar los dos: el observador que pasa el fulfillment a `PURCHASING` y la cancelación compiten por la misma
condición.

## Quién cierra el pedido

Un pedido pasa a `COMPLETED` cuando todas sus unidades están en fulfillments `COMPLETED`; esa entrega es una
confirmación humana con actor (aún no hay transportistas). Es el único sitio que lo escribe.
"""

import datetime
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.engine import CursorResult
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
from app.db.models.audit import AuditLog
from app.db.models.fulfillment import Fulfillment, FulfillmentItem
from app.db.models.order import Order, OrderItem
from app.db.models.payment import Payment
from app.gates.action_gate import CostKind, GateOutcome, SideEffectAction
from app.gates.service import ActionGateService
from app.integrations.operating_policy import require_operation
from app.integrations.ports import IntegrationDomain
from app.integrations.registry import ProviderRegistry
from app.money.money import Money
from app.orders import allocation
from app.orders.domain import OrderStatus
from app.orders.errors import OperationNotAllowedError, OutcomeUnknownBlockError
from app.orders.fulfilment_domain import FulfillmentStatus
from app.orders.fulfilment_port import (
    OPERATION_PURCHASE,
    OPERATION_SHIP,
    PHASE_PURCHASE,
    PHASE_SHIP,
    FulfilmentLine,
    FulfilmentProvider,
)
from app.orders.fulfilment_projection import FulfilmentMovedError, fulfilment_reference
from app.orders.gate_inputs import recommendations_for, require_legal_analysis_outside_simulation
from app.orders.payment_attempts import Requester

FULFILMENT_ACTOR = "fulfilment"


@dataclass(frozen=True)
class FulfilmentRequestLine:
    """Cuántas unidades de una línea del pedido cubrirá el fulfillment."""

    order_item_id: str
    quantity: int


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


class FulfilmentService:
    def __init__(
        self,
        db: Session,
        *,
        settings: Settings | None = None,
        provider: FulfilmentProvider | None = None,
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

    # --- Crear (una decisión local: no sale nada) -----------------------------------------------------

    def create(self, order_id: str, lines: Sequence[FulfilmentRequestLine], *, actor: str) -> Fulfillment:
        """Reparte unidades de un pedido pagado en un fulfillment `READY`. Las unidades se apartan con aritmética de
        base de datos: ninguna línea se asigna de más, ni con peticiones simultáneas."""
        if not lines:
            raise ValidationError("a fulfillment covers at least one line")
        wanted = Counter[str]()
        for line in lines:
            if line.quantity <= 0:
                raise ValidationError("a fulfillment line needs a positive quantity")
            wanted[line.order_item_id] += line.quantity
        provider = self._resolve_provider()

        order = self._lock_order(order_id)
        self._require_paid(order)
        items = {
            item.id: item
            for item in self._db.scalars(select(OrderItem).where(OrderItem.order_id == order.id)).all()
            if item.id in wanted
        }
        missing = sorted(set(wanted) - set(items))
        if missing:
            raise NotFoundError(f"order {order_id} has no line {', '.join(missing)}")
        suppliers = {item.supplier_id for item in items.values()}
        if len(suppliers) > 1:
            raise ValidationError("a fulfillment buys from a single supplier: split the lines into several")

        fulfillment = Fulfillment(
            order_id=order.id,
            provider=provider.name,
            supplier_id=suppliers.pop(),
            status=FulfillmentStatus.READY.value,
            created_by=actor,
            correlation_id=new_correlation_id(),
        )
        self._db.add(fulfillment)
        self._db.flush()
        for order_item_id, quantity in wanted.items():
            if not allocation.allocate(self._db, order_item_id, quantity):
                self._db.rollback()
                raise ConflictError(
                    f"line {items[order_item_id].line_number} of order {order_id} has fewer than {quantity} "
                    "units left to assign"
                )
            self._db.add(FulfillmentItem(fulfillment_id=fulfillment.id, order_item_id=order_item_id, quantity=quantity))
        self._audit(
            fulfillment,
            actor,
            "fulfillment.created",
            None,
            {"order_id": order.id, "lines": {k: v for k, v in sorted(wanted.items())}},
        )
        self._db.commit()
        self._db.refresh(fulfillment)
        return fulfillment

    # --- Comprar y enviar (acciones externas gobernadas) ---------------------------------------------

    def purchase(self, fulfillment_id: str, *, requester: Requester) -> Fulfillment:
        """Compra al proveedor lo que cubre el fulfillment. Devuelve el fulfillment en `PURCHASED`, en `READY` (el
        proveedor confirmó que no compró) o en `UNKNOWN_OUTCOME` (pudo comprar y no se sabe)."""
        return self._run(fulfillment_id, PHASE_PURCHASE, requester)

    def ship(self, fulfillment_id: str, *, requester: Requester) -> Fulfillment:
        """Manda el envío de lo comprado. Devuelve el fulfillment en `SHIPPED`, en `PURCHASED` (confirmado que no se
        envió: sigue comprado y asignado) o en `UNKNOWN_OUTCOME`."""
        return self._run(fulfillment_id, PHASE_SHIP, requester)

    def _run(self, fulfillment_id: str, phase: str, requester: Requester) -> Fulfillment:
        purchase = phase == PHASE_PURCHASE
        operation = OPERATION_PURCHASE if purchase else OPERATION_SHIP
        side_effect = SideEffectAction.PURCHASE_SUPPLIER if purchase else SideEffectAction.SHIP_ORDER
        provider = self._resolve_provider()
        require_operation(provider.name, operation, self._settings)

        fulfillment, order = self._lock(fulfillment_id)
        self._require_ready_for(fulfillment, phase, provider)
        self._require_paid(order)
        recommendations = recommendations_for(self._db, order)
        require_legal_analysis_outside_simulation(recommendations, self._settings)

        lines = self._lines(fulfillment)
        cost = provider.quote_cost(phase=phase, lines=lines, currency=order.currency)
        decision = self._gate.evaluate(
            side_effect,
            legal_recommendation=recommendations.legal,
            economics_recommendation=recommendations.economics,
            actor_role=requester.role,
            cost=cost,
        )
        self._gate.audit(
            decision,
            action=side_effect,
            resource=f"fulfillment:{fulfillment.id}",
            correlation_id=fulfillment.correlation_id,
            actor=requester.name,
        )
        if decision.outcome is not GateOutcome.ALLOW:
            self._db.commit()  # el rastro de lo que el gate impidió
            raise OperationNotAllowedError(
                f"the {phase} cannot be made: " + "; ".join(decision.reasons),
                reasons=decision.reasons,
                requires_approval=decision.outcome is GateOutcome.REQUIRE_APPROVAL,
            )

        payload = {
            "fulfillment_id": fulfillment.id,
            "order_id": order.id,
            "phase": phase,
            "lines": [
                {"order_item_id": line.order_item_id, "product_id": line.product_id, "quantity": line.quantity}
                for line in lines
            ],
        }
        action = self._actions.open(
            reference=fulfilment_reference(fulfillment.id, phase),
            adapter=provider,
            operation=operation,
            amount=cost.amount if cost.kind is CostKind.KNOWN else None,
            payload=payload,
            correlation_id=fulfillment.correlation_id,
        )
        if action.status == "PENDING" and not self._actions.reserve(action):
            self._db.rollback()
            raise OperationNotAllowedError(
                "the budget was used up by another request before this spend could be reserved",
                reasons=["the budget does not cover this action"],
            )
        self._db.commit()  # la operación `PENDING` y su reserva: todavía no ha salido nada

        try:
            self._actions.execute(action, provider, payload)
        except ExternalActionFailedError:
            pass  # el proveedor confirmó que no hubo efecto: el observador ya dejó el fulfillment donde estaba
        except ExternalOutcomeUnknownError:
            pass  # pudo ejecutarse: el fulfillment queda UNKNOWN_OUTCOME y bloquea nuevos intentos
        except PipelineDisabledError as exc:
            self._actions.finish_unstarted(action)  # el kill switch se apagó justo antes: no salió nada
            raise OperationNotAllowedError(str(exc), reasons=["the pipeline kill switch is off"]) from exc
        except FulfilmentMovedError:
            # Se canceló (o se movió) entre confirmar la operación y empezar la llamada: nada salió. La acción vuelve a
            # cerrarse sin efecto y su reserva se libera.
            self._db.rollback()
            self._actions.finish_unstarted(action)
            raise
        except ExternalActionStateError as exc:
            # La referencia de la acción es la del fulfillment y la fase, así que dos peticiones simultáneas comparten
            # la misma acción `PENDING`: gana quien la pasa a `CALLING` y la otra la encuentra ya movida. No es un
            # fallo ni un resultado desconocido de esta petición: otra está llevando a cabo la operación, y el estado
            # del fulfillment (no esta respuesta) cuenta lo que pasó.
            self._db.rollback()
            raise ConflictError(
                f"fulfillment {fulfillment_id}: another request is already carrying out the {phase}; "
                "look at the state of the fulfillment"
            ) from exc
        self._db.refresh(fulfillment)
        return fulfillment

    # --- Decisiones de una persona --------------------------------------------------------------------

    def complete(self, fulfillment_id: str, *, actor: str) -> Fulfillment:
        """Confirma la entrega de un envío (`SHIPPED → COMPLETED`). Si con ella todas las unidades del pedido están
        entregadas, el pedido pasa a `COMPLETED`."""
        fulfillment, order = self._lock(fulfillment_id)
        now = self._clock()
        moved = self._execute(
            update(Fulfillment)
            .where(Fulfillment.id == fulfillment.id, Fulfillment.status == FulfillmentStatus.SHIPPED.value)
            .values(status=FulfillmentStatus.COMPLETED.value, completed_at=now, completed_by=actor, closed_at=now)
        )
        if moved.rowcount != 1:
            raise ConflictError(
                f"fulfillment {fulfillment.id} is {fulfillment.status}: only a shipped one is delivered"
            )
        self._audit(
            fulfillment, actor, "fulfillment.completed", {"status": "SHIPPED"}, {"status": "COMPLETED", "by": actor}
        )
        if self._all_delivered(order):
            done = self._execute(
                update(Order)
                .where(Order.id == order.id, Order.status == OrderStatus.PAID.value)
                .values(status=OrderStatus.COMPLETED.value, completed_at=now)
            )
            if done.rowcount == 1:
                self._db.add(
                    AuditLog(
                        actor=actor,
                        action="order.completed",
                        resource=f"order:{order.id}",
                        before={"status": OrderStatus.PAID.value},
                        after={"status": OrderStatus.COMPLETED.value},
                        correlation_id=order.correlation_id,
                    )
                )
        self._db.commit()
        self._db.refresh(fulfillment)
        return fulfillment

    def cancel(self, fulfillment_id: str, *, actor: str) -> Fulfillment:
        """Cancela un fulfillment que **nunca compró** y devuelve sus unidades al pool."""
        return self._abandon(fulfillment_id, actor, FulfillmentStatus.CANCELLED)

    def fail(self, fulfillment_id: str, *, actor: str) -> Fulfillment:
        """Abandona un fulfillment cuya compra falló de forma confirmada y que nunca compró, y devuelve sus unidades."""
        return self._abandon(fulfillment_id, actor, FulfillmentStatus.FAILED)

    def _abandon(self, fulfillment_id: str, actor: str, to: FulfillmentStatus) -> Fulfillment:
        fulfillment, _ = self._lock(fulfillment_id)
        before = fulfillment.status
        failing = to is FulfillmentStatus.FAILED
        if not allocation.release_allocation(
            self._db, fulfillment.id, to=to, require_failed_attempt=failing, now=self._clock()
        ):
            self._db.rollback()
            self._db.refresh(fulfillment)
            raise self._cannot_release(fulfillment, failing)
        self._audit(fulfillment, actor, f"fulfillment.{to.value.lower()}", {"status": before}, {"status": to.value})
        self._db.commit()
        self._db.refresh(fulfillment)
        return fulfillment

    @staticmethod
    def _cannot_release(fulfillment: Fulfillment, failing: bool) -> ConflictError:
        if fulfillment.status == FulfillmentStatus.UNKNOWN_OUTCOME.value:
            return OutcomeUnknownBlockError(
                f"fulfillment {fulfillment.id} has an unknown {fulfillment.unknown_phase} outcome: its units cannot "
                "return to the pool until it is reconciled or resolved"
            )
        if fulfillment.status == FulfillmentStatus.READY.value and failing and fulfillment.failed_attempts < 1:
            return ConflictError(f"fulfillment {fulfillment.id} has not failed: cancel it instead")
        return ConflictError(
            f"fulfillment {fulfillment.id} is {fulfillment.status}: only one that never bought can give its units back"
        )

    # --- Reglas del dominio -------------------------------------------------------------------------

    def _require_paid(self, order: Order) -> None:
        if order.status != OrderStatus.PAID.value:
            raise ConflictError(f"order {order.id} is {order.status}: only a paid order is fulfilled")
        # `populate_existing`: la sesión no caduca al confirmar y los reembolsos escriben con SQL directo, así que una
        # instancia ya cargada tendría un `refund_committed_amount` viejo. El pedido ya está bloqueado: lo que se
        # lee aquí es lo último confirmado.
        payments = list(
            self._db.scalars(
                select(Payment).where(Payment.order_id == order.id).execution_options(populate_existing=True)
            )
        )
        captured = sum((Decimal(str(p.captured_amount)) for p in payments), Decimal(0))
        committed = sum((Decimal(str(p.refund_committed_amount)) for p in payments), Decimal(0))
        if captured - committed < Decimal(str(order.amount_due)):
            raise ConflictError(
                f"order {order.id} is no longer fully paid (what was refunded or is being refunded counts): "
                "it is not fulfilled until someone looks at it"
            )

    def _require_ready_for(self, fulfillment: Fulfillment, phase: str, provider: FulfilmentProvider) -> None:
        expected = FulfillmentStatus.READY if phase == PHASE_PURCHASE else FulfillmentStatus.PURCHASED
        if fulfillment.status == FulfillmentStatus.UNKNOWN_OUTCOME.value:
            raise OutcomeUnknownBlockError(
                f"fulfillment {fulfillment.id} has an unknown {fulfillment.unknown_phase} outcome: reconcile it, wait "
                "for the late response, or resolve it before acting again"
            )
        if fulfillment.status != expected.value:
            raise ConflictError(
                f"fulfillment {fulfillment.id} is {fulfillment.status}: the {phase} needs it {expected.value}"
            )
        if fulfillment.provider != provider.name:
            raise ConflictError(
                f"fulfillment {fulfillment.id} belongs to {fulfillment.provider}, not to {provider.name}"
            )

    def _lines(self, fulfillment: Fulfillment) -> list[FulfilmentLine]:
        rows = self._db.execute(
            select(FulfillmentItem.quantity, OrderItem)
            .join(OrderItem, OrderItem.id == FulfillmentItem.order_item_id)
            .where(FulfillmentItem.fulfillment_id == fulfillment.id)
            .order_by(OrderItem.line_number)
        ).all()
        order = self._db.get(Order, fulfillment.order_id)
        assert order is not None
        return [
            FulfilmentLine(
                order_item_id=item.id,
                line_number=item.line_number,
                product_id=item.product_id,
                quantity=quantity,
                unit_cost=Money.of(str(item.unit_cost), order.currency) if item.unit_cost is not None else None,
            )
            for quantity, item in rows
        ]

    def _all_delivered(self, order: Order) -> bool:
        delivered: dict[str, int] = {
            order_item_id: int(quantity)
            for order_item_id, quantity in self._db.execute(
                select(FulfillmentItem.order_item_id, func.sum(FulfillmentItem.quantity))
                .join(Fulfillment, Fulfillment.id == FulfillmentItem.fulfillment_id)
                .where(Fulfillment.order_id == order.id, Fulfillment.status == FulfillmentStatus.COMPLETED.value)
                .group_by(FulfillmentItem.order_item_id)
            ).all()
        }
        items = self._db.scalars(select(OrderItem).where(OrderItem.order_id == order.id)).all()
        return all(int(delivered.get(item.id, 0)) >= item.quantity for item in items)

    # --- Interno -------------------------------------------------------------------------------------

    def _lock_order(self, order_id: str) -> Order:
        # `FOR NO KEY UPDATE` y no `FOR UPDATE`: sigue siendo un mutex entre quienes bloquean el pedido, pero no choca
        # con el `FOR KEY SHARE` de la comprobación de clave foránea que PostgreSQL repite al actualizar dos veces, en
        # una transacción, una fila de `fulfillments` (el observador de la compra lo hace). Con `FOR UPDATE`, esa
        # comprobación esperaba a quien cancelaba, y quien cancelaba esperaba la fila: interbloqueo real.
        order = self._db.scalars(
            select(Order)
            .where(Order.id == order_id)
            .with_for_update(key_share=True)
            .execution_options(populate_existing=True)
        ).one_or_none()
        if order is None:
            raise NotFoundError(f"order {order_id} not found")
        return order

    def _lock(self, fulfillment_id: str) -> tuple[Fulfillment, Order]:
        """El mismo orden de bloqueos que el resto (pedido, luego fulfillment)."""
        found = self._db.get(Fulfillment, fulfillment_id)
        if found is None:
            raise NotFoundError(f"fulfillment {fulfillment_id} not found")
        order = self._lock_order(found.order_id)
        fulfillment = self._db.scalars(
            select(Fulfillment)
            .where(Fulfillment.id == fulfillment_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).one()
        return fulfillment, order

    def _resolve_provider(self) -> FulfilmentProvider:
        if self._provider is not None:
            return self._provider
        return ProviderRegistry(self._settings).resolve(IntegrationDomain.FULFILMENT)  # type: ignore[return-value]

    def _audit(self, fulfillment: Fulfillment, actor: str, action: str, before: dict | None, after: dict) -> None:
        self._db.add(
            AuditLog(
                actor=actor,
                action=action,
                resource=f"fulfillment:{fulfillment.id}",
                before=before,
                after=after,
                correlation_id=fulfillment.correlation_id,
            )
        )

    def _execute(self, statement) -> CursorResult:
        result = self._db.execute(statement.execution_options(synchronize_session=False))
        assert isinstance(result, CursorResult)
        return result
