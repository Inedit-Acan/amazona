"""Apoyo compartido de las pruebas de fulfillment (Milestone 44, ADR 0028 §6).

Módulo auxiliar de tests, **no** un test. Un proveedor de fulfillment simulado **con guion** (bien, rechaza, no se puede
alcanzar, se agota el tiempo antes o después de ejecutar, o el proceso muere) y los gestos que repiten las pruebas:
tener un pedido pagado de dos líneas, repartirlo en fulfillments y leer lo que quedó escrito.

Ningún test habla con un proveedor de verdad (I12).
"""

from collections import deque

from order_test_support import add_product, add_quote, add_supplier, create_order, line
from payment_test_support import ScriptedPaymentProvider, deliver, start_attempt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.actions.contract import (
    ActionRequest,
    ActionResponse,
    ProviderRejectedError,
    ProviderTimeoutError,
    ProviderUnreachableError,
)
from app.core.config import Settings
from app.db.models.fulfillment import Fulfillment
from app.db.models.order import Order, OrderItem
from app.orders.fulfilment import FulfilmentRequestLine, FulfilmentService
from app.orders.payment_attempts import Requester
from app.orders.simulated_fulfilment import SimulatedFulfilmentAdapter
from app.payments.port import PaymentEventType

SIMULATION = Settings(_env_file=None)
REQUESTER = Requester(name="test@amazona.local", role=None)


class ScriptedFulfilmentProvider(SimulatedFulfilmentAdapter):
    """El simulador con un guion: cada llamada a `execute` consume el siguiente comportamiento (por defecto, `ok`).

    - `ok`: ejecuta y responde. `reject`: el proveedor se niega (no hay efecto). `unreachable`: no llega a salir.
      `timeout_before`: se agota el tiempo y **no** ejecutó. `timeout_after`: **ejecutó** y la respuesta se perdió.
      `die`: el proceso muere en mitad de la llamada (`KeyboardInterrupt`)."""

    def __init__(self, *behaviors: str, **kwargs) -> None:
        kwargs.setdefault("operations", {})
        super().__init__(**kwargs)
        self.behaviors = deque(behaviors)
        self.calls: list[ActionRequest] = []

    def execute(self, request: ActionRequest) -> ActionResponse:
        self.calls.append(request)
        behavior = self.behaviors.popleft() if self.behaviors else "ok"
        if behavior == "reject":
            raise ProviderRejectedError("the provider refused the request")
        if behavior == "unreachable":
            raise ProviderUnreachableError("could not connect to the provider")
        if behavior == "timeout_before":
            raise ProviderTimeoutError("timed out before the provider executed anything")
        if behavior == "die":
            raise KeyboardInterrupt("the process died in the middle of the call")
        response = super().execute(request)
        if behavior == "timeout_after":
            raise ProviderTimeoutError("the provider executed and the answer was lost")
        return response


def paid_order(db: Session, *, with_cost: bool = True, customer: str = "sim_customer") -> Order:
    """Un pedido **pagado** por un evento verificado, de dos líneas (4 × 10.00 y 2 × 5.00 = 50.00), del mismo proveedor.

    `with_cost=False` deja el coste de proveedor desconocido (`NULL`: nunca cero)."""
    supplier = add_supplier(db)
    first, second = add_product(db, name=f"Alpha {customer}"), add_product(db, name=f"Beta {customer}")
    cost_a = cost_b = None
    if with_cost:
        cost_a, cost_b = "6.00", "2.50"
    if with_cost:
        quote_a, quote_b = add_quote(db, first, supplier), add_quote(db, second, supplier)
    else:  # una cotización sin precio: el coste de proveedor es desconocido, no cero
        quote_a = add_quote(db, first, supplier, unit_price=None, currency=None, provenance=None)
        quote_b = add_quote(db, second, supplier, unit_price=None, currency=None, provenance=None)
    order = create_order(
        db,
        line(first, quantity=4, unit_price="10.00", quote=quote_a, declared_cost=cost_a),
        line(second, quantity=2, unit_price="5.00", quote=quote_b, declared_cost=cost_b),
        customer_ref=customer,
    )
    provider = ScriptedPaymentProvider()
    payment = start_attempt(db, order, provider)
    deliver(db, provider, PaymentEventType.PAYMENT_SUCCEEDED, payment)
    db.refresh(order)
    assert order.status == "PAID", order.status
    return order


def items_of(db: Session, order: Order) -> list[OrderItem]:
    db.expire_all()
    return list(db.scalars(select(OrderItem).where(OrderItem.order_id == order.id).order_by(OrderItem.line_number)))


def allocated(db: Session, order: Order) -> list[int]:
    return [item.allocated_quantity for item in items_of(db, order)]


def service(db: Session, provider: ScriptedFulfilmentProvider, *, settings: Settings = SIMULATION) -> FulfilmentService:
    return FulfilmentService(db, settings=settings, provider=provider)


def create_fulfillment(
    db: Session, order: Order, provider: ScriptedFulfilmentProvider, quantities: tuple[int, ...] = (4, 2)
) -> Fulfillment:
    """Un fulfillment `READY` que cubre las unidades indicadas de cada línea (0 = esa línea no entra)."""
    items = items_of(db, order)
    lines = [FulfilmentRequestLine(item.id, q) for item, q in zip(items, quantities, strict=True) if q > 0]
    return service(db, provider).create(order.id, lines, actor="owner@amazona.local")


def reload(db: Session, fulfillment: Fulfillment) -> Fulfillment:
    db.expire_all()
    return db.get(Fulfillment, fulfillment.id)  # type: ignore[return-value]
