"""Operaciones aleatorias sobre M44, compartidas por la caminata y por la tormenta concurrente (Milestone 44, ADR 0028).

Módulo auxiliar de tests, **no** un test. Las pruebas que lo usan están en `test_m44_random_walk.py` (un hilo, SQLite) y
`test_m44_concurrency.py` (varios hilos, PostgreSQL).

Original:

Caminatas aleatorias sobre M44: el estado persistente es coherente pase lo que pase.

Las pruebas de ejemplo comprueban los caminos que alguien imaginó. Esta recorre los que nadie imaginó: con una semilla,
elige operaciones al azar (abrir cobros, entregar eventos —repetidos, alterados, antiguos, de importes distintos—, pedir
reembolsos, repartir, comprar, enviar, cancelar, barrer, reconciliar, resolver a mano y **morir en mitad de una
llamada**), con proveedores que fallan de todas las formas que declara el contrato, y después de **cada** paso exige:

1. `check_invariants`: el estado entero es coherente (pedidos, cobros, reembolsos, asignación, y el dominio y su
   `ExternalAction` cuentan la misma historia);
2. ningún proveedor recibió más llamadas que operaciones cruzaron la frontera de durabilidad;
3. **ningún error escapa sin ser una respuesta limpia**: lo que no es 404, 409, 422 o 423 sería un 500 en la API.

Al final, una recuperación con las herramientas que existen (barrido, resolución humana, reconciliación de eventos)
tiene que dejar **todo** en un estado que no esté a medias. Si una semilla falla, el mensaje trae la semilla y la
secuencia de operaciones: se reproduce tal cual.
"""

import datetime
import random
from dataclasses import dataclass, field

from fulfilment_test_support import ScriptedFulfilmentProvider
from m44_invariants_test_support import check_invariants, provider_calls_never_exceed_the_frontier
from order_test_support import add_product, add_quote, add_supplier, create_order, line, make_engine, session_factory
from payment_test_support import REQUESTER, SIMULATION, ScriptedPaymentProvider
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.actions.service import ExternalActionService, ExternalActionStateError
from app.cli import reconcile_payment_events
from app.core.errors import ConflictError, NotFoundError, PipelineDisabledError, ValidationError
from app.db.models.external_action import ExternalAction
from app.db.models.fulfillment import Fulfillment
from app.db.models.order import Order, OrderItem
from app.db.models.payment import Payment, PaymentEvent, Refund
from app.money.money import Money
from app.orders.fulfilment import FulfilmentRequestLine, FulfilmentService
from app.orders.payment_attempts import PaymentAttemptService
from app.orders.refunds import RefundService
from app.orders.service import OrderService
from app.payments.ingress import PaymentIngress
from app.payments.port import PaymentEventType, WebhookVerificationError
from app.payments.service import PaymentService

#: Lo que la API traduce a una respuesta limpia: 404, 409, 422, 423, y 400 con mensaje fijo para un webhook que no se
#: puede verificar. Cualquier otra cosa sería un 500.
CLEAN = (NotFoundError, ValidationError, ConflictError, PipelineDisabledError, WebhookVerificationError)

BEHAVIORS = (
    ["ok"] * 60 + ["reject"] * 6 + ["unreachable"] * 5 + ["timeout_before"] * 8 + ["timeout_after"] * 10 + ["die"] * 4
)
STEPS = 60


@dataclass
class World:
    factory: object
    rnd: random.Random
    pay: ScriptedPaymentProvider
    ful: ScriptedFulfilmentProvider
    product: object
    quote: object
    log: list[str] = field(default_factory=list)
    leaks: list[str] = field(default_factory=list)
    delivered: list[tuple[dict, bytes]] = field(default_factory=list)
    #: Cuánto tiene que llevar una operación abierta para que el barrido la dé por huérfana. Con un solo hilo, `-1 s`
    #: barre todo; con varios hilos tiene que superar lo que tarda una petición viva (regla del barrido, ADR 0024).
    sweep_after: datetime.timedelta = datetime.timedelta(seconds=-1)

    def session(self) -> Session:
        return self.factory()  # type: ignore[operator]

    def script(self, provider) -> None:
        provider.behaviors.clear()
        provider.behaviors.append(self.rnd.choice(BEHAVIORS))

    def pick(self, db: Session, model, where=None):
        rows = list(db.scalars(select(model).where(where) if where is not None else select(model)))
        return self.rnd.choice(rows) if rows else None

    def pick_that_can_advance(self, db: Session, model, advancing, anything=None):
        """Casi siempre la entidad que puede dar el siguiente paso; a veces cualquiera (el paso inválido también se
        prueba)."""
        if self.rnd.random() < 0.8:
            chosen = self.pick(db, model, advancing)
            if chosen is not None:
                return chosen
        return self.pick(db, model, anything)


def new_order(w: World, db: Session) -> None:
    lines = [
        line(
            w.product,
            quantity=w.rnd.randint(1, 4),
            unit_price=w.rnd.choice(["10.00", "12.50", "3.30", "0.99"]),
            quote=w.quote,
            declared_cost="2.00",
        )
        for _ in range(w.rnd.randint(1, 2))
    ]
    create_order(db, *lines, customer_ref=f"sim_walk_{w.rnd.randint(0, 10**6)}")


def open_payment(w: World, db: Session) -> None:
    order = w.pick_that_can_advance(db, Order, Order.status == "AWAITING_PAYMENT")
    if order is None:
        return
    w.script(w.pay)
    PaymentAttemptService(db, settings=SIMULATION, provider=w.pay).start(order.id, requester=REQUESTER)


def _event(w: World, payment: Payment, kind: PaymentEventType, *, amount: str | None, **kwargs):
    money = Money.of(amount, payment.currency) if amount is not None else None
    return w.pay.simulate_event(
        kind,
        provider_payment_ref=payment.provider_payment_ref if w.rnd.random() < 0.8 else None,
        client_reference=payment.id,
        amount=money,
        **kwargs,
    )


def deliver_capture(w: World, db: Session) -> None:
    payment = w.pick_that_can_advance(
        db, Payment, Payment.status.in_(("OPEN", "OPENING", "UNKNOWN_OUTCOME", "FAILED", "EXPIRED"))
    )
    if payment is None:
        return
    amount = str(payment.amount) if w.rnd.random() < 0.85 else w.rnd.choice(["1.00", "999.99", "0.01"])
    headers, raw = _event(w, payment, PaymentEventType.PAYMENT_SUCCEEDED, amount=amount)
    w.delivered.append((headers, raw))
    PaymentIngress(db, settings=SIMULATION, provider=w.pay).receive(w.pay.name, headers, raw)


def deliver_closing(w: World, db: Session) -> None:
    payment = w.pick(db, Payment)
    if payment is None:
        return
    kind = w.rnd.choice(
        [PaymentEventType.PAYMENT_FAILED, PaymentEventType.PAYMENT_EXPIRED, PaymentEventType.PAYMENT_ATTEMPT_FAILED]
    )
    headers, raw = _event(w, payment, kind, amount=None)
    w.delivered.append((headers, raw))
    PaymentIngress(db, settings=SIMULATION, provider=w.pay).receive(w.pay.name, headers, raw)


def replay_event(w: World, db: Session) -> None:
    if not w.delivered:
        return
    headers, raw = w.rnd.choice(w.delivered)
    PaymentIngress(db, settings=SIMULATION, provider=w.pay).receive(w.pay.name, headers, raw)


def tampered_event(w: World, db: Session) -> None:
    payment = w.pick(db, Payment)
    if payment is None:
        return
    headers, raw = _event(w, payment, PaymentEventType.PAYMENT_SUCCEEDED, amount=str(payment.amount))
    PaymentIngress(db, settings=SIMULATION, provider=w.pay).receive(
        w.pay.name, headers, raw.replace(b"payment", b"paymenX", 1)
    )


def stale_event(w: World, db: Session) -> None:
    payment = w.pick(db, Payment)
    if payment is None:
        return
    old = datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=w.rnd.randint(1, 48))
    headers, raw = _event(w, payment, PaymentEventType.PAYMENT_FAILED, amount=None, occurred_at=old)
    PaymentIngress(db, settings=SIMULATION, provider=w.pay).receive(w.pay.name, headers, raw)


def request_refund(w: World, db: Session) -> None:
    payment = w.pick_that_can_advance(
        db, Payment, Payment.status.in_(("SUCCEEDED", "DUPLICATE_CAPTURE", "CAPTURE_MISMATCH"))
    )
    if payment is None:
        return
    w.script(w.pay)
    amount = w.rnd.choice(["1.00", "5.00", "10.00", "25.00", "999.00"])
    RefundService(db, settings=SIMULATION, provider=w.pay).request(
        payment.id, amount=Money.of(amount, payment.currency), reason="customer_request", requester=REQUESTER
    )


def refund_event(w: World, db: Session) -> None:
    refund = w.pick(db, Refund)
    if refund is None:
        return
    payment = db.get(Payment, refund.payment_id)
    kind = w.rnd.choice(
        [PaymentEventType.REFUND_SUCCEEDED, PaymentEventType.REFUND_SUCCEEDED, PaymentEventType.REFUND_FAILED]
    )
    amount = str(refund.amount) if w.rnd.random() < 0.9 else "0.50"
    headers, raw = w.pay.simulate_event(
        kind,
        provider_payment_ref=payment.provider_payment_ref,
        provider_refund_ref=refund.provider_refund_ref,
        client_reference=refund.id,
        amount=Money.of(amount, refund.currency),
    )
    w.delivered.append((headers, raw))
    PaymentIngress(db, settings=SIMULATION, provider=w.pay).receive(w.pay.name, headers, raw)


def create_fulfillment(w: World, db: Session) -> None:
    order = w.pick_that_can_advance(db, Order, Order.status == "PAID")
    if order is None:
        return
    items = list(db.scalars(select(OrderItem).where(OrderItem.order_id == order.id)))
    chosen = [FulfilmentRequestLine(i.id, w.rnd.randint(1, i.quantity)) for i in items if w.rnd.random() < 0.7] or [
        FulfilmentRequestLine(items[0].id, 1)
    ]
    FulfilmentService(db, settings=SIMULATION, provider=w.ful).create(order.id, chosen, actor="owner@amazona.local")


NEXT_STEP = {
    "purchase": ("READY",),
    "ship": ("PURCHASED",),
    "complete": ("SHIPPED",),
    "cancel": ("READY",),
    "fail": ("READY",),
}


def _fulfilment_op(w: World, db: Session, name: str, statuses: tuple[str, ...] | None = None) -> None:
    fulfillment = w.pick_that_can_advance(db, Fulfillment, Fulfillment.status.in_(NEXT_STEP[name]))
    if fulfillment is None:
        return
    w.script(w.ful)
    service = FulfilmentService(db, settings=SIMULATION, provider=w.ful)
    if name == "purchase":
        service.purchase(fulfillment.id, requester=REQUESTER)
    elif name == "ship":
        service.ship(fulfillment.id, requester=REQUESTER)
    elif name == "complete":
        service.complete(fulfillment.id, actor="owner@amazona.local")
    elif name == "cancel":
        service.cancel(fulfillment.id, actor="owner@amazona.local")
    elif name == "fail":
        service.fail(fulfillment.id, actor="owner@amazona.local")


def cancel_order(w: World, db: Session) -> None:
    order = w.pick(db, Order)
    if order is not None:
        OrderService(db, settings=SIMULATION).cancel(order.id, actor="owner@amazona.local")


def sweep(w: World, db: Session) -> None:
    ExternalActionService(db).reconcile_interrupted(older_than=w.sweep_after)


def reconcile_lookup(w: World, db: Session) -> None:
    action = w.pick(db, ExternalAction, ExternalAction.status == "UNKNOWN_OUTCOME")
    if action is None:
        return
    adapter = w.ful if action.reference.startswith("order_fulfilment:") else w.pay
    ExternalActionService(db).reconcile(action, adapter, {})


def resolve_by_hand(w: World, db: Session) -> None:
    action = w.pick(db, ExternalAction, ExternalAction.status == "UNKNOWN_OUTCOME")
    if action is None:
        return
    ExternalActionService(db).resolve(
        action, succeeded=w.rnd.random() < 0.5, actor="owner@amazona.local", reason="checked"
    )


def deliver_then_die(w: World, db: Session) -> None:
    """El proceso muere **entre** guardar el evento verificado y aplicarlo (ADR 0028 §1): el evento queda `RECEIVED`.
    Parchea `PaymentService.apply`: solo es seguro con un hilo (la tormenta concurrente no la usa)."""
    payment = w.pick_that_can_advance(
        db, Payment, Payment.status.in_(("OPEN", "OPENING", "UNKNOWN_OUTCOME", "FAILED", "EXPIRED"))
    )
    if payment is None:
        return
    headers, raw = _event(w, payment, PaymentEventType.PAYMENT_SUCCEEDED, amount=str(payment.amount))
    real_apply = PaymentService.apply

    def died(self, event_id):
        raise KeyboardInterrupt("died between the two transactions")

    PaymentService.apply = died  # type: ignore[method-assign]
    try:
        PaymentIngress(db, settings=SIMULATION, provider=w.pay).receive(w.pay.name, headers, raw)
    finally:
        PaymentService.apply = real_apply  # type: ignore[method-assign]


def reconcile_events(w: World, db: Session) -> None:
    """`reconcile-payment-events`: aplica lo que se guardó y no se aplicó. Solo toca lo de hace más de un minuto (lo
    reciente podría estar aplicándose ahora), así que primero se envejece lo recibido, como si hubiera pasado el
    tiempo."""
    db.execute(
        update(PaymentEvent)
        .where(PaymentEvent.processing_status == "RECEIVED")
        .values(received_at=datetime.datetime.now(datetime.UTC) - datetime.timedelta(minutes=10))
    )
    db.commit()
    reconcile_payment_events(db, older_than_minutes=1)


#: Las operaciones que parchean código (solo seguras con un hilo) no entran en la tormenta concurrente.
SINGLE_THREAD_ONLY = {"deliver_then_die"}


OPERATIONS = [
    (8, "new_order", new_order),
    (14, "open_payment", open_payment),
    (14, "deliver_capture", deliver_capture),
    (7, "deliver_closing", deliver_closing),
    (6, "replay_event", replay_event),
    (3, "tampered_event", tampered_event),
    (2, "stale_event", stale_event),
    (8, "request_refund", request_refund),
    (7, "refund_event", refund_event),
    (8, "create_fulfillment", create_fulfillment),
    (10, "purchase", lambda w, db: _fulfilment_op(w, db, "purchase")),
    (9, "ship", lambda w, db: _fulfilment_op(w, db, "ship")),
    (7, "complete", lambda w, db: _fulfilment_op(w, db, "complete")),
    (4, "cancel_fulfillment", lambda w, db: _fulfilment_op(w, db, "cancel")),
    (2, "fail_fulfillment", lambda w, db: _fulfilment_op(w, db, "fail")),
    (3, "cancel_order", cancel_order),
    (5, "sweep", sweep),
    (5, "reconcile_lookup", reconcile_lookup),
    (4, "resolve_by_hand", resolve_by_hand),
    (3, "reconcile_events", reconcile_events),
    (4, "deliver_then_die", deliver_then_die),
]


# : Operaciones que solo existen en la consola (`reconcile-actions`, `resolve-action`). El CLI traduce un :
# `ExternalActionStateError` («la acción ya no está desconocida: otro la cerró antes») a un mensaje limpio y no a un
# fallo: : dos personas o dos reconciliadores sobre la misma acción son un compare-and-set, y el que pierde lo sabe.
CLI_ONLY = {"sweep", "reconcile_lookup", "resolve_by_hand", "reconcile_events"}


def run_operation(w: World, name: str, operation) -> None:
    db = w.session()
    try:
        operation(w, db)
    except CLEAN:
        pass  # una respuesta limpia: el dominio dijo que no y no cambió nada
    except ExternalActionStateError:
        if name not in CLI_ONLY:
            w.leaks.append(f"{name}: ExternalActionStateError would be a 500 on a route")
    except KeyboardInterrupt:
        pass  # el proceso murió en mitad de la llamada: la sesión se pierde con su transacción abierta
    except BaseException as exc:  # noqa: BLE001 - lo que no es limpio es el hallazgo
        w.leaks.append(f"{name}: {type(exc).__name__}: {str(exc)[:160]}")
    finally:
        db.rollback()
        db.close()


def make_world(seed: int, engine=None) -> tuple[World, object]:
    engine = engine if engine is not None else make_engine()
    factory = session_factory(engine)
    with factory() as db:
        product, supplier = add_product(db), add_supplier(db)
        quote = add_quote(db, product, supplier)
    world = World(
        factory=factory,
        rnd=random.Random(seed),
        pay=ScriptedPaymentProvider(),
        ful=ScriptedFulfilmentProvider(),
        product=product,
        quote=quote,
    )
    return world, engine


def verdict(w: World, seed: int, where: str) -> list[str]:
    with w.session() as db:
        broken = check_invariants(db)
        broken += provider_calls_never_exceed_the_frontier(db, len(w.pay.calls) + len(w.ful.calls))
    broken += w.leaks
    if broken:
        return [f"seed {seed} {where}: {item}" for item in broken] + ["operations: " + " > ".join(w.log[-20:])]
    return []


def verdict_of(w: World, label: str) -> list[str]:
    """Lo que está roto, con la etiqueta de quien lo mira."""
    return verdict(w, label, "now")


def walk(w: World, steps: int = STEPS) -> None:
    """Da `steps` pasos al azar (sin comprobar nada entre medias)."""
    weights = [weight for weight, _, _ in OPERATIONS]
    for _ in range(steps):
        _, name, operation = w.rnd.choices(OPERATIONS, weights=weights)[0]
        w.log.append(name)
        run_operation(w, name, operation)
