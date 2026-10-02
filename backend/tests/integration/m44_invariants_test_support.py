"""Los invariantes de M44 como una función: `check_invariants(db)` devuelve lo que está roto (Milestone 44, ADR 0028).

Módulo auxiliar de tests, **no** un test. Lo usan la caminata aleatoria, la matriz de caídas y las carreras: después de
**cada** paso miran el estado persistente entero y exigen que sea coherente, sea cual sea el camino que llevó hasta él.

Cada comprobación sale de algo escrito, no de memoria:

- una restricción de la base de datos que el código no debe poder incumplir (`CHECK`, índices únicos parciales);
- una promesa del ADR 0028 (§3 la frontera de lo enviado, §4 la evidencia financiera, §5 la aritmética del reembolso, §6
  la asignación);
- una proyección: el dominio sigue a su `ExternalAction` **en la misma transacción**, así que ambos no pueden contar
  historias distintas.

Vacío = todo en orden. Los mensajes dicen qué entidad y qué cifra, para que un fallo de una semilla se pueda reproducir.
"""

import re
from collections import defaultdict
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.audit import AuditLog
from app.db.models.external_action import ExternalAction
from app.db.models.fulfillment import Fulfillment, FulfillmentItem
from app.db.models.order import Order, OrderItem
from app.db.models.payment import Payment, PaymentEvent, Refund
from app.orders.fulfilment_domain import LIVE_FULFILLMENT_STATUSES, UNITS_COMMITTED_STATUSES
from app.payments.domain import ACTIVE_PAYMENT_STATUSES, CAPTURED_PAYMENT_STATUSES, RESERVING_REFUND_STATUSES

ZERO = Decimal(0)
CUSTOMER_REF = re.compile(r"^[A-Za-z0-9._:\-]{1,64}$")

PAYMENT_PREFIX = "order_payment:"
REFUND_PREFIX = "order_refund:"
FULFILMENT_PREFIX = "order_fulfilment:"

#: Estados de un cobro/reembolso/fulfillment que dicen «posiblemente enviado»: la frontera de durabilidad se cruzó.
SENT_PAYMENT = {"OPENING"}
SENT_REFUND = {"SENDING"}
SENT_FULFILMENT = {"PURCHASING", "SHIPPING"}


def _dec(value: object) -> Decimal:
    return Decimal(str(value))


def _latest_actions(db: Session) -> dict[str, ExternalAction]:
    """La operación vigente de cada sitio: la de mayor `sequence`."""
    latest: dict[str, ExternalAction] = {}
    for action in db.scalars(select(ExternalAction).order_by(ExternalAction.reference, ExternalAction.sequence)):
        latest[action.reference] = action
    return latest


def check_invariants(db: Session) -> list[str]:
    db.expire_all()
    broken: list[str] = []
    orders = {o.id: o for o in db.scalars(select(Order))}
    items = list(db.scalars(select(OrderItem)))
    payments = list(db.scalars(select(Payment)))
    refunds = list(db.scalars(select(Refund)))
    fulfillments = list(db.scalars(select(Fulfillment)))
    fulfilment_items = list(db.scalars(select(FulfillmentItem)))
    events = list(db.scalars(select(PaymentEvent)))
    actions = _latest_actions(db)
    anomalies = {log.resource for log in db.scalars(select(AuditLog).where(AuditLog.action.like("%.anomaly.%")))}

    broken += _orders(orders, items, payments, fulfillments, fulfilment_items)
    broken += _payments(orders, payments, events)
    broken += _refunds(payments, refunds)
    broken += _fulfilment(items, fulfillments, fulfilment_items)
    broken += _actions_and_domain(payments, refunds, fulfillments, actions, anomalies)
    return broken


# --- Pedidos ------------------------------------------------------------------------------------------------------


def _orders(orders, items, payments, fulfillments, fulfilment_items) -> list[str]:
    broken: list[str] = []
    lines: dict[str, list[OrderItem]] = defaultdict(list)
    for item in items:
        lines[item.order_id].append(item)
    delivered: dict[str, int] = defaultdict(int)
    by_fulfillment = {f.id: f for f in fulfillments}
    for fi in fulfilment_items:
        if by_fulfillment[fi.fulfillment_id].status == "COMPLETED":
            delivered[fi.order_item_id] += fi.quantity
    canonical = {p.order_id for p in payments if p.status == "SUCCEEDED"}

    for order in orders.values():
        tag = f"order {order.id}"
        own = lines[order.id]
        total = sum((_dec(i.line_total) for i in own), ZERO)
        if _dec(order.amount_due) != total:
            broken.append(f"{tag}: amount_due {order.amount_due} is not the sum of its lines {total}")
        for item in own:
            if _dec(item.line_total) != _dec(item.unit_price) * item.quantity:
                broken.append(
                    f"{tag} line {item.line_number}: total {item.line_total} != {item.quantity} x {item.unit_price}"
                )
        if not CUSTOMER_REF.match(order.customer_ref) or "@" in order.customer_ref:
            broken.append(f"{tag}: customer_ref {order.customer_ref!r} can carry personal data")
        if order.is_simulated != order.customer_ref.startswith("sim_"):
            broken.append(f"{tag}: simulated={order.is_simulated} but customer_ref {order.customer_ref!r}")
        if order.status == "PAID":
            if order.paid_at is None:
                broken.append(f"{tag}: PAID without paid_at")
            if order.id not in canonical:
                broken.append(f"{tag}: PAID without a SUCCEEDED payment (only a verified capture pays an order)")
        if order.status == "AWAITING_PAYMENT" and order.paid_at is not None:
            broken.append(f"{tag}: AWAITING_PAYMENT with paid_at")
        if order.status == "CANCELLED":
            if order.paid_at is not None:
                broken.append(f"{tag}: CANCELLED yet it carries paid_at")
            if order.cancelled_at is None:
                broken.append(f"{tag}: CANCELLED without cancelled_at")
            if any(p.order_id == order.id and p.status in ACTIVE_PAYMENT_STATUSES for p in payments):
                broken.append(f"{tag}: CANCELLED with a live payment attempt")
        if order.status == "COMPLETED":
            if order.completed_at is None:
                broken.append(f"{tag}: COMPLETED without completed_at")
            for item in own:
                if delivered[item.id] < item.quantity:
                    broken.append(
                        f"{tag} line {item.line_number}: COMPLETED with {delivered[item.id]}/{item.quantity} delivered"
                    )
        if order.status != "CANCELLED" and order.cancelled_at is not None:
            broken.append(f"{tag}: {order.status} with cancelled_at")
    return broken


# --- Cobros --------------------------------------------------------------------------------------------------------


def _payments(orders, payments, events) -> list[str]:
    broken: list[str] = []
    active: dict[str, int] = defaultdict(int)
    succeeded: dict[str, int] = defaultdict(int)
    for p in payments:
        tag = f"payment {p.id}"
        captured, committed, refunded = (
            _dec(p.captured_amount),
            _dec(p.refund_committed_amount),
            _dec(p.refunded_amount),
        )
        if p.status in ACTIVE_PAYMENT_STATUSES:
            active[p.order_id] += 1
        if p.status == "SUCCEEDED":
            succeeded[p.order_id] += 1
        if not ZERO <= refunded <= committed <= captured:
            broken.append(f"{tag}: refunded {refunded} <= committed {committed} <= captured {captured} does not hold")
        if captured > ZERO and p.status not in CAPTURED_PAYMENT_STATUSES:
            broken.append(f"{tag}: {p.status} holds captured money {captured}")
        if p.status in CAPTURED_PAYMENT_STATUSES and captured <= ZERO:
            broken.append(f"{tag}: {p.status} with nothing captured")
        if p.status == "DUPLICATE_CAPTURE" and p.duplicate_of_payment_id is None:
            broken.append(f"{tag}: DUPLICATE_CAPTURE that points to no canonical payment")
        if p.status == "REQUESTED" and p.provider_payment_ref is not None and captured > ZERO:
            broken.append(f"{tag}: money captured from an attempt that never left")

    for order_id, count in active.items():
        if count > 1:
            broken.append(f"order {order_id}: {count} live payment attempts (at most one)")
    for order_id, count in succeeded.items():
        if count > 1:
            broken.append(
                f"order {order_id}: {count} SUCCEEDED payments (at most one: a second one is DUPLICATE_CAPTURE)"
            )

    applied_money: dict[str, Decimal] = defaultdict(lambda: ZERO)
    seen: set[tuple[str, str]] = set()
    for e in events:
        key = (e.provider, e.provider_event_id)
        if key in seen:
            broken.append(f"event {key}: stored twice")
        seen.add(key)
        if (
            e.processing_status == "APPLIED"
            and e.event_type == "payment.succeeded"
            and e.payment_id
            and e.amount is not None
        ):
            applied_money[e.payment_id] += _dec(e.amount)
        if e.data and any(name in e.data for name in ("raw_body", "body", "raw", "payload")):
            broken.append(f"event {e.id}: keeps a raw body in `data`")
    for p in payments:
        if p.status in CAPTURED_PAYMENT_STATUSES and applied_money[p.id] != _dec(p.captured_amount):
            broken.append(
                f"payment {p.id}: captured {p.captured_amount} but the applied capture events add up to "
                f"{applied_money[p.id]}"
            )
    return broken


# --- Reembolsos ----------------------------------------------------------------------------------------------------


def _refunds(payments, refunds) -> list[str]:
    broken: list[str] = []
    reserved: dict[str, Decimal] = defaultdict(lambda: ZERO)
    settled: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for r in refunds:
        if r.status in RESERVING_REFUND_STATUSES:
            reserved[r.payment_id] += _dec(r.amount)
        if r.status == "SUCCEEDED":
            settled[r.payment_id] += _dec(r.amount)
        if _dec(r.amount) <= ZERO:
            broken.append(f"refund {r.id}: amount {r.amount} is not positive")
    for p in payments:
        if _dec(p.refund_committed_amount) != reserved[p.id]:
            broken.append(
                f"payment {p.id}: refund_committed {p.refund_committed_amount} != what its refunds reserve "
                f"{reserved[p.id]} (UNKNOWN_OUTCOME keeps the reservation, FAILED releases it)"
            )
        if _dec(p.refunded_amount) != settled[p.id]:
            broken.append(f"payment {p.id}: refunded {p.refunded_amount} != its SUCCEEDED refunds {settled[p.id]}")
    return broken


# --- Fulfillment y asignación -----------------------------------------------------------------------------------------


def _fulfilment(items, fulfillments, fulfilment_items) -> list[str]:
    broken: list[str] = []
    by_fulfillment = {f.id: f for f in fulfillments}
    held: dict[str, int] = defaultdict(int)
    for fi in fulfilment_items:
        if by_fulfillment[fi.fulfillment_id].status in LIVE_FULFILLMENT_STATUSES:
            held[fi.order_item_id] += fi.quantity
    for item in items:
        tag = f"order item {item.id} (line {item.line_number})"
        if not 0 <= item.allocated_quantity <= item.quantity:
            broken.append(f"{tag}: allocated {item.allocated_quantity} outside 0..{item.quantity}")
        if item.allocated_quantity != held[item.id]:
            broken.append(
                f"{tag}: allocated {item.allocated_quantity} but live fulfillments hold {held[item.id]} "
                "(an abandoned fulfillment gives units back; a bought one never does)"
            )
    for f in fulfillments:
        tag = f"fulfillment {f.id}"
        if (f.status == "UNKNOWN_OUTCOME") != (f.unknown_phase is not None):
            broken.append(f"{tag}: status {f.status} with unknown_phase {f.unknown_phase}")
        if f.status in UNITS_COMMITTED_STATUSES and f.status != "PURCHASING" and f.status != "UNKNOWN_OUTCOME":
            if f.purchased_at is None:
                broken.append(f"{tag}: {f.status} without purchased_at")
        if f.status in ("SHIPPED", "COMPLETED") and f.shipped_at is None:
            broken.append(f"{tag}: {f.status} without shipped_at")
        if f.status == "COMPLETED" and not f.completed_by:
            broken.append(f"{tag}: COMPLETED without a person who confirmed the delivery")
        if f.status in ("CANCELLED", "FAILED") and f.purchased_at is not None:
            broken.append(f"{tag}: {f.status} after buying: its units would return to the pool")
        if f.failed_attempts < 0:
            broken.append(f"{tag}: failed_attempts {f.failed_attempts}")
        if f.tracking_reference and f.shipped_at is None:
            broken.append(f"{tag}: a tracking reference invented before anything shipped")
    return broken


# --- ExternalAction y dominio: la frontera de lo enviado --------------------------------------------------------------


def _actions_and_domain(payments, refunds, fulfillments, actions, anomalies) -> list[str]:
    """El dominio sigue a su acción en la misma transacción: «nada enviado» ⇔ acción `PENDING`; «posiblemente
    enviado» ⇔ `CALLING`; «desconocido» ⇔ `UNKNOWN_OUTCOME`. Un hecho verificado del proveedor (una captura) puede
    cerrar el cobro por delante de su acción, y eso es lo único que se tolera."""
    broken: list[str] = []
    verified_ahead = {"SUCCEEDED", "DUPLICATE_CAPTURE", "CAPTURE_MISMATCH", "FAILED", "EXPIRED"}

    for p in payments:
        action = actions.get(f"{PAYMENT_PREFIX}{p.id}")
        status = action.status if action else None
        tag = f"payment {p.id} ({p.status})"
        if p.status == "REQUESTED" and status not in (None, "PENDING"):
            broken.append(f"{tag}: nothing sent but its action is {status}")
        if status == "PENDING" and p.status != "REQUESTED":
            broken.append(f"{tag}: its action is PENDING (nothing sent) but the payment says {p.status}")
        if p.status == "OPENING" and status != "CALLING":
            broken.append(f"{tag}: possibly sent but its action is {status}")
        if p.status == "UNKNOWN_OUTCOME" and status != "UNKNOWN_OUTCOME":
            broken.append(f"{tag}: unknown outcome but its action is {status}")
        if p.status == "OPEN" and status != "SUCCEEDED":
            broken.append(f"{tag}: open at the provider but its action is {status}")
        if status == "UNKNOWN_OUTCOME" and p.status != "UNKNOWN_OUTCOME" and p.status not in verified_ahead:
            broken.append(f"{tag}: its action is UNKNOWN_OUTCOME and nothing verified closed the payment")
        if status == "CALLING" and p.status != "OPENING" and p.status not in verified_ahead:
            broken.append(f"{tag}: its action is CALLING and nothing verified closed the payment")

    for r in refunds:
        if r.origin != "OPERATOR":
            continue  # un reembolso del proveedor es un hecho: no tiene acción nuestra
        action = actions.get(f"{REFUND_PREFIX}{r.id}")
        status = action.status if action else None
        tag = f"refund {r.id} ({r.status})"
        expected = {
            "REQUESTED": {"PENDING"},
            "SENDING": {"CALLING", "SUCCEEDED"},
            "UNKNOWN_OUTCOME": {"UNKNOWN_OUTCOME"},
            "FAILED": {"FAILED_CONFIRMED", "UNKNOWN_OUTCOME", "SUCCEEDED", "CALLING"},
            # Un hecho verificado (`refund.succeeded`) manda sobre la acción: puede llegar con la acción desconocida y
            # una persona resolverla después como fallida. El reembolso y el dinero no se tocan, y queda una anomalía.
            "SUCCEEDED": {"SUCCEEDED", "CALLING", "UNKNOWN_OUTCOME", "FAILED_CONFIRMED"},
        }[r.status]
        if status not in expected:
            broken.append(f"{tag}: its action is {status}, expected one of {sorted(expected)}")
        if r.status == "SUCCEEDED" and status == "FAILED_CONFIRMED" and f"refund:{r.id}" not in anomalies:
            broken.append(
                f"{tag}: a human closed its action as failed against a verified fact and no anomaly was audited"
            )

    for f in fulfillments:
        purchase = actions.get(f"{FULFILMENT_PREFIX}{f.id}:purchase")
        ship = actions.get(f"{FULFILMENT_PREFIX}{f.id}:ship")
        tag = f"fulfillment {f.id} ({f.status}/{f.unknown_phase})"
        p_status = purchase.status if purchase else None
        s_status = ship.status if ship else None
        if f.status == "PURCHASING" and p_status != "CALLING":
            broken.append(f"{tag}: possibly bought but the purchase action is {p_status}")
        if f.status == "SHIPPING" and s_status != "CALLING":
            broken.append(f"{tag}: possibly shipped but the ship action is {s_status}")
        if f.status == "UNKNOWN_OUTCOME":
            wanted = p_status if f.unknown_phase == "purchase" else s_status
            if wanted != "UNKNOWN_OUTCOME":
                broken.append(f"{tag}: unknown outcome but the {f.unknown_phase} action is {wanted}")
        if f.status in ("PURCHASED", "SHIPPING", "SHIPPED", "COMPLETED") and p_status != "SUCCEEDED":
            broken.append(f"{tag}: bought but the purchase action is {p_status}")
        if f.status in ("SHIPPED", "COMPLETED") and s_status != "SUCCEEDED":
            broken.append(f"{tag}: shipped but the ship action is {s_status}")
        if f.status == "READY" and p_status in ("CALLING", "UNKNOWN_OUTCOME", "SUCCEEDED"):
            broken.append(f"{tag}: nothing bought but the purchase action is {p_status}")
        if f.status == "PURCHASED" and s_status in ("CALLING", "UNKNOWN_OUTCOME", "SUCCEEDED"):
            broken.append(f"{tag}: nothing shipped but the ship action is {s_status}")
    return broken


def provider_calls_never_exceed_the_frontier(db: Session, calls: int) -> list[str]:
    """Ningún proveedor recibió más llamadas que operaciones cruzaron la frontera de durabilidad (`call_started_at`)."""
    db.expire_all()
    crossed = sum(1 for a in db.scalars(select(ExternalAction)) if a.call_started_at is not None)
    if calls > crossed:
        return [f"{calls} provider calls but only {crossed} operations crossed the durability frontier"]
    return []
