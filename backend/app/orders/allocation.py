"""La asignación de unidades de un pedido a sus fulfillments (Milestone 44, ADR 0028 §6).

Mismo patrón que el libro de presupuesto y el de reembolsos: **comprobar y escribir en una sola sentencia**.
`order_items.allocated_quantity` solo sube y baja aquí, con un `UPDATE … WHERE` cuya condición *es* el límite, y el
`CHECK 0 ≤ allocated ≤ quantity` de la tabla es el respaldo si alguien se saltara este módulo.

- `allocate`: aparta unidades de una línea si caben (`quantity - allocated_quantity >= q`);
- `release_allocation`: **la única** forma de devolver unidades al pool. Una unidad ya comprada no vuelve: por eso la
  función es un compare-and-set sobre el propio fulfillment (`status = 'READY' AND purchased_at IS NULL AND
  unknown_phase IS NULL`) en la misma transacción que la devolución. Si la compra pudo salir (`PURCHASING`), se
  compró (`PURCHASED` en adelante) o no se sabe qué pasó (`UNKNOWN_OUTCOME`), el CAS no gana y nada se libera.

Devolver unidades de un fulfillment comprado permitiría asignarlas a otro y comprarlas dos veces.
"""

import datetime

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from app.db.models.fulfillment import Fulfillment, FulfillmentItem
from app.db.models.order import OrderItem
from app.orders.fulfilment_domain import FulfillmentStatus


def _execute(db: Session, statement) -> CursorResult:
    result = db.execute(statement.execution_options(synchronize_session=False))
    assert isinstance(result, CursorResult)
    return result


def allocate(db: Session, order_item_id: str, quantity: int) -> bool:
    """Aparta `quantity` unidades de la línea. `False` si no caben (o la cantidad no es positiva)."""
    if quantity <= 0:
        return False
    result = _execute(
        db,
        update(OrderItem)
        .where(OrderItem.id == order_item_id, OrderItem.quantity - OrderItem.allocated_quantity >= quantity)
        .values(allocated_quantity=OrderItem.allocated_quantity + quantity),
    )
    return result.rowcount == 1


def release_allocation(
    db: Session,
    fulfillment_id: str,
    *,
    to: FulfillmentStatus,
    require_failed_attempt: bool = False,
    now: datetime.datetime | None = None,
) -> bool:
    """Cierra un fulfillment que **nunca compró** (`CANCELLED` o `FAILED`) y devuelve sus unidades al pool.

    El compare-and-set exige `READY`, sin compra y sin resultado desconocido. Si no gana (`False`), no se toca ni el
    fulfillment ni la asignación. `require_failed_attempt` añade la condición de `FAILED`: haber fallado de forma
    confirmada al menos una vez."""
    if to not in (FulfillmentStatus.CANCELLED, FulfillmentStatus.FAILED):
        raise ValueError(f"a fulfillment closes as CANCELLED or FAILED, not {to}")
    closed_at = now or datetime.datetime.now(datetime.UTC)
    conditions = [
        Fulfillment.id == fulfillment_id,
        Fulfillment.status == FulfillmentStatus.READY.value,
        Fulfillment.purchased_at.is_(None),
        Fulfillment.unknown_phase.is_(None),
    ]
    if require_failed_attempt:
        conditions.append(Fulfillment.failed_attempts >= 1)
    claimed = _execute(db, update(Fulfillment).where(*conditions).values(status=to.value, closed_at=closed_at))
    if claimed.rowcount != 1:
        return False
    for item in db.execute(
        select(FulfillmentItem.order_item_id, FulfillmentItem.quantity).where(
            FulfillmentItem.fulfillment_id == fulfillment_id
        )
    ).all():
        order_item_id, quantity = item
        freed = _execute(
            db,
            update(OrderItem)
            .where(OrderItem.id == order_item_id, OrderItem.allocated_quantity >= quantity)
            .values(allocated_quantity=OrderItem.allocated_quantity - quantity),
        )
        if freed.rowcount != 1:
            # La asignación no cuadra con los fulfillments: es un defecto, no algo que ignorar. La excepción deshace
            # el cierre del fulfillment y todo lo liberado hasta aquí.
            raise RuntimeError(f"order item {order_item_id} holds fewer units than fulfillment {fulfillment_id} owns")
    return True
