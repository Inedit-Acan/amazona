"""El vocabulario del dinero cobrado y devuelto (Milestone 44, ADR 0028 §2–§5).

Estados y conjuntos en un solo sitio. Las pruebas recorren las tablas: lo que no figura aquí es una transición que
no existe.
"""

from enum import StrEnum


class PaymentStatus(StrEnum):
    #: Existe la fila y la operación `payment.open` está abierta, pero **no ha salido nada**.
    REQUESTED = "REQUESTED"
    #: La frontera de durabilidad se cruzó: la petición pudo salir.
    OPENING = "OPENING"
    #: Pudo ejecutarse y no se sabe el resultado. Bloquea nuevos intentos.
    UNKNOWN_OUTCOME = "UNKNOWN_OUTCOME"
    #: El proveedor creó el cobro y espera al cliente.
    OPEN = "OPEN"
    #: Captura confirmada y canónica: la que cuenta como el cobro del pedido.
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"
    #: Una captura real válida **adicional** para un pedido que ya tenía otra (ADR 0028 §4).
    DUPLICATE_CAPTURE = "DUPLICATE_CAPTURE"
    #: Una captura real de un importe **distinto** del esperado (ADR 0028 §4).
    CAPTURE_MISMATCH = "CAPTURE_MISMATCH"


#: Un intento «vivo»: un pedido tiene como máximo uno, y un `UNKNOWN_OUTCOME` cuenta (bloquea nuevos intentos).
ACTIVE_PAYMENT_STATUSES: tuple[str, ...] = (
    PaymentStatus.REQUESTED.value,
    PaymentStatus.OPENING.value,
    PaymentStatus.UNKNOWN_OUTCOME.value,
    PaymentStatus.OPEN.value,
)

#: Estados que sostienen dinero realmente capturado. Solo ellos admiten un reembolso.
CAPTURED_PAYMENT_STATUSES: tuple[str, ...] = (
    PaymentStatus.SUCCEEDED.value,
    PaymentStatus.DUPLICATE_CAPTURE.value,
    PaymentStatus.CAPTURE_MISMATCH.value,
)

#: Desde estos estados puede llegar una captura (incluso tardía). Desde `REQUESTED` no: de ahí no pudo salir nada.
CAPTURE_ACCEPTING_STATUSES: tuple[str, ...] = (
    PaymentStatus.OPENING.value,
    PaymentStatus.UNKNOWN_OUTCOME.value,
    PaymentStatus.OPEN.value,
    PaymentStatus.FAILED.value,
    PaymentStatus.EXPIRED.value,
)

#: Desde estos estados un `payment.failed` / `payment.expired` cierra el intento.
CLOSABLE_PAYMENT_STATUSES: tuple[str, ...] = (
    PaymentStatus.OPENING.value,
    PaymentStatus.UNKNOWN_OUTCOME.value,
    PaymentStatus.OPEN.value,
)


class RefundStatus(StrEnum):
    #: Existe y tiene su importe reservado, pero **no ha salido nada**.
    REQUESTED = "REQUESTED"
    SENDING = "SENDING"
    UNKNOWN_OUTCOME = "UNKNOWN_OUTCOME"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


#: Reembolsos cuyo importe sigue reservado sobre el cobro (`refund_committed_amount`): los que aún pueden ocurrir
#: y los que ya ocurrieron. Un `FAILED` lo libera; un `UNKNOWN_OUTCOME` **no**.
RESERVING_REFUND_STATUSES: tuple[str, ...] = (
    RefundStatus.REQUESTED.value,
    RefundStatus.SENDING.value,
    RefundStatus.UNKNOWN_OUTCOME.value,
    RefundStatus.SUCCEEDED.value,
)

REFUND_ORIGIN_OPERATOR = "OPERATOR"
REFUND_ORIGIN_PROVIDER = "PROVIDER"


class EventProcessing(StrEnum):
    """Qué pasó con un evento verificado. `RECEIVED` es lo único que no es definitivo."""

    RECEIVED = "RECEIVED"
    APPLIED = "APPLIED"
    #: Describe algo que ya no cambia nada (una etapa anterior a la actual, o ya aplicado).
    STALE = "STALE"
    #: Contradice un hecho ya registrado, o no se puede aplicar sin inventar. **La evidencia se conserva entera.**
    CONFLICT = "CONFLICT"
    #: No se pudo emparejar con ningún cobro nuestro.
    UNMATCHED = "UNMATCHED"
    REJECTED = "REJECTED"
