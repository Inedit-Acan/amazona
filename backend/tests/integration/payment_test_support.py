"""Apoyo compartido de las pruebas de cobros, eventos y reembolsos (Milestone 44, ADR 0028).

Módulo auxiliar de tests, **no** un test. Un proveedor de pagos simulado **con guion** (se le dice cómo se comporta
en cada llamada: bien, rechaza, no se puede alcanzar, se agota el tiempo antes o después de ejecutar, o el proceso
muere) y los gestos que repiten todas las pruebas: abrir un intento de cobro, entregar un evento firmado por la
puerta, contar lo que quedó escrito.

Ningún test habla con un proveedor de verdad (I12) y la clave de firma es una por prueba, generada al vuelo.
"""

import datetime
import secrets
from collections import deque
from decimal import Decimal

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
from app.db.models.order import Order
from app.db.models.payment import Payment, PaymentEvent, Refund
from app.money.money import Money
from app.orders.payment_attempts import PaymentAttemptService, Requester
from app.payments.ingress import IngressResult, PaymentIngress
from app.payments.port import PaymentEventType
from app.payments.providers.simulated import SimulatedPaymentProvider

SIMULATION = Settings(_env_file=None)
REQUESTER = Requester(name="test@amazona.local", role=None)

NOW = datetime.datetime(2026, 10, 2, 12, 0, tzinfo=datetime.UTC)


class ScriptedPaymentProvider(SimulatedPaymentProvider):
    """El simulador con un guion: cada llamada a `execute` consume el siguiente comportamiento (por defecto, `ok`).

    - `ok`: ejecuta y responde. `reject`: el proveedor se niega (no hay efecto). `unreachable`: no llega a salir (no
      hay efecto). `timeout_before`: se agota el tiempo y **no** ejecutó. `timeout_after`: **ejecutó** y la respuesta
      se perdió. `die`: el proceso muere en mitad de la llamada (`KeyboardInterrupt`)."""

    def __init__(self, *behaviors: str, **kwargs) -> None:
        kwargs.setdefault("signing_key", secrets.token_bytes(32))
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


def add_order(
    db: Session, product, *, price: str = "25.00", quantity: int = 2, customer: str = "sim_customer"
) -> Order:
    from order_test_support import create_order, line

    return create_order(db, line(product, quantity=quantity, unit_price=price), customer_ref=customer)


def start_attempt(db: Session, order: Order, provider: SimulatedPaymentProvider, *, settings: Settings = SIMULATION):
    return PaymentAttemptService(db, settings=settings, provider=provider).start(order.id, requester=REQUESTER)


def ingress(db: Session, provider: SimulatedPaymentProvider, *, settings: Settings = SIMULATION) -> PaymentIngress:
    return PaymentIngress(db, settings=settings, provider=provider)


def deliver(
    db: Session,
    provider: SimulatedPaymentProvider,
    event_type: PaymentEventType,
    payment: Payment,
    *,
    amount: str | None = None,
    event_id: str | None = None,
    occurred_at: datetime.datetime | None = None,
    refund_ref: str | None = None,
    use_payment_ref: bool = True,
    currency: str | None = None,
    failure_code: str | None = None,
) -> IngressResult:
    """Entrega por la puerta un evento firmado por el proveedor, como un webhook."""
    money = None
    if event_type is PaymentEventType.PAYMENT_SUCCEEDED or amount is not None or event_type.value.startswith("refund"):
        money = Money.of(amount if amount is not None else str(payment.amount), currency or payment.currency)
    headers, raw = provider.simulate_event(
        event_type,
        provider_payment_ref=payment.provider_payment_ref if use_payment_ref else None,
        provider_refund_ref=refund_ref,
        client_reference=payment.id,
        amount=money,
        failure_code=failure_code,
        event_id=event_id,
        occurred_at=occurred_at,
    )
    return ingress(db, provider).receive(provider.name, headers, raw)


def reload(db: Session, instance):
    db.expire_all()
    return db.get(type(instance), instance.id)


def payments_of(db: Session, order: Order) -> list[Payment]:
    db.expire_all()
    return list(db.scalars(select(Payment).where(Payment.order_id == order.id).order_by(Payment.attempt_number)))


def events(db: Session) -> list[PaymentEvent]:
    db.expire_all()
    return list(db.scalars(select(PaymentEvent).order_by(PaymentEvent.received_at, PaymentEvent.id)))


def refunds(db: Session) -> list[Refund]:
    db.expire_all()
    return list(db.scalars(select(Refund).order_by(Refund.requested_at, Refund.id)))


def captured_total(db: Session, order: Order) -> Decimal:
    """El dinero realmente capturado de un pedido: auditable aunque viole la expectativa comercial."""
    return sum((Decimal(str(p.captured_amount)) for p in payments_of(db, order)), Decimal(0))


def fresh_order_status(db: Session, order: Order) -> str:
    return reload(db, order).status
