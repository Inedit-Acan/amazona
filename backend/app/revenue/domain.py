"""El vocabulario del registro de ingresos verificados (ADR 0030 §3 y §4)."""

from enum import StrEnum

from app.payments.domain import PaymentStatus


class EntryKind(StrEnum):
    CAPTURE = "CAPTURE"
    REFUND = "REFUND"


class Classification(StrEnum):
    """Qué es el dinero que entró. La clasificación **la dicta el estado del cobro**, no una lógica aparte."""

    #: El ingreso válido del pedido (la captura canónica).
    ORDER_PAYMENT = "ORDER_PAYMENT"
    #: Un segundo cobro real del mismo pedido: dinero recibido que requiere revisión, fuera del titular de ingresos.
    DUPLICATE_RECEIPT = "DUPLICATE_RECEIPT"
    #: Una captura de un importe distinto del esperado: dinero en revisión, fuera del titular de ingresos.
    MISMATCH_RECEIPT = "MISMATCH_RECEIPT"


_BY_PAYMENT_STATUS = {
    PaymentStatus.SUCCEEDED.value: Classification.ORDER_PAYMENT,
    PaymentStatus.DUPLICATE_CAPTURE.value: Classification.DUPLICATE_RECEIPT,
    PaymentStatus.CAPTURE_MISMATCH.value: Classification.MISMATCH_RECEIPT,
}

#: Los tipos de evento que producen una entrada, y la clase de entrada que producen (ADR 0030 §6).
CAPTURE_EVENT_TYPE = "payment.succeeded"
REFUND_EVENT_TYPE = "refund.succeeded"
EVENT_TYPE_OF_KIND = {EntryKind.CAPTURE.value: CAPTURE_EVENT_TYPE, EntryKind.REFUND.value: REFUND_EVENT_TYPE}


def classify_capture(payment_status: str) -> Classification:
    """La clasificación de una captura según el estado del cobro en que quedó. Un estado que no es de captura es un
    error de programación, no un dato."""
    try:
        return _BY_PAYMENT_STATUS[payment_status]
    except KeyError:
        raise ValueError(f"a payment in {payment_status!r} holds no capture to classify") from None
