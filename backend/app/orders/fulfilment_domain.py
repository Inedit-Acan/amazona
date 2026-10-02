"""El vocabulario del fulfillment (Milestone 44, ADR 0028 §3 y §6): estados y conjuntos en un solo sitio.

Las pruebas recorren las tablas: lo que no figura aquí es una transición que no existe.
"""

from enum import StrEnum


class FulfillmentStatus(StrEnum):
    #: Las líneas están asignadas y **no se ha enviado nada**: antes de comprar.
    READY = "READY"
    #: La frontera de durabilidad de la compra se cruzó: la petición pudo salir.
    PURCHASING = "PURCHASING"
    #: Comprado y **nada enviado**: antes de enviar. Aquí se vuelve tras un envío fallido.
    PURCHASED = "PURCHASED"
    SHIPPING = "SHIPPING"
    SHIPPED = "SHIPPED"
    #: Entregado: una confirmación humana, con actor.
    COMPLETED = "COMPLETED"
    #: Se abandonó tras fallar de forma confirmada, **sin compra**. Libera la asignación.
    FAILED = "FAILED"
    #: Se canceló antes de comprar. Libera la asignación.
    CANCELLED = "CANCELLED"
    #: Pudo ejecutarse y no se sabe el resultado (`unknown_phase` dice de qué operación).
    UNKNOWN_OUTCOME = "UNKNOWN_OUTCOME"


#: Las transiciones válidas. `PURCHASING → READY` y `SHIPPING → PURCHASED` son los fallos **confirmados** (nada se
#: compró / nada se envió); `UNKNOWN_OUTCOME` sale solo por reconciliación, respuesta tardía o resolución humana.
FULFILLMENT_TRANSITIONS: dict[FulfillmentStatus, frozenset[FulfillmentStatus]] = {
    FulfillmentStatus.READY: frozenset(
        {FulfillmentStatus.PURCHASING, FulfillmentStatus.CANCELLED, FulfillmentStatus.FAILED}
    ),
    FulfillmentStatus.PURCHASING: frozenset(
        {FulfillmentStatus.PURCHASED, FulfillmentStatus.READY, FulfillmentStatus.UNKNOWN_OUTCOME}
    ),
    FulfillmentStatus.PURCHASED: frozenset({FulfillmentStatus.SHIPPING}),
    FulfillmentStatus.SHIPPING: frozenset(
        {FulfillmentStatus.SHIPPED, FulfillmentStatus.PURCHASED, FulfillmentStatus.UNKNOWN_OUTCOME}
    ),
    FulfillmentStatus.SHIPPED: frozenset({FulfillmentStatus.COMPLETED}),
    FulfillmentStatus.COMPLETED: frozenset(),
    FulfillmentStatus.FAILED: frozenset(),
    FulfillmentStatus.CANCELLED: frozenset(),
    FulfillmentStatus.UNKNOWN_OUTCOME: frozenset(
        {
            # purchase: comprado / no comprado; ship: enviado / no enviado
            FulfillmentStatus.PURCHASED,
            FulfillmentStatus.READY,
            FulfillmentStatus.SHIPPED,
        }
    ),
}

#: Estados con unidades asignadas que **no pueden devolverse al pool**: la compra pudo salir o ya se hizo.
UNITS_COMMITTED_STATUSES: tuple[str, ...] = (
    FulfillmentStatus.PURCHASING.value,
    FulfillmentStatus.PURCHASED.value,
    FulfillmentStatus.SHIPPING.value,
    FulfillmentStatus.SHIPPED.value,
    FulfillmentStatus.COMPLETED.value,
    FulfillmentStatus.UNKNOWN_OUTCOME.value,
)

#: Fulfillments que siguen reclamando unidades del pedido (todo menos los que las devolvieron).
LIVE_FULFILLMENT_STATUSES: tuple[str, ...] = (
    FulfillmentStatus.READY.value,
    *UNITS_COMMITTED_STATUSES,
)

#: Estados «en curso»: ya se decidió comprar y aún no se entregó ni se cerró.
IN_PROGRESS_STATUSES: tuple[str, ...] = (
    FulfillmentStatus.READY.value,
    FulfillmentStatus.PURCHASING.value,
    FulfillmentStatus.PURCHASED.value,
    FulfillmentStatus.SHIPPING.value,
    FulfillmentStatus.SHIPPED.value,
    FulfillmentStatus.UNKNOWN_OUTCOME.value,
)

PHASE_FOR_OPERATION = {"fulfillment.purchase": "purchase", "fulfillment.ship": "ship"}
