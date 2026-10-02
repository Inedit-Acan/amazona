"""El puerto de un proveedor de pagos (Milestone 44, ADR 0028 §1).

Es el contrato que cumplirá una pasarela real el día que exista, y el que cumple hoy el simulador. Dos cosas
distintas:

- **Operaciones salientes** (`execute`: abrir un cobro, reembolsar). Son un `ExternalActionAdapter` normal
  (ADR 0024): declaran `supports_idempotency`, pueden saber consultar (`lookup`) y su resultado desconocido
  nunca se resuelve a ciegas.
- **Eventos entrantes** (`verify_webhook`). Un proveedor es el único que sabe verificar a sus propios
  webhooks, y es el único que puede entregar un `VerifiedPaymentEvent`. Verificar **no escribe nada**.

Lo que este módulo no hace es decidir qué pasa con un evento: eso es de `PaymentService`, y es el mismo
servicio para un evento simulado que para el webhook de una pasarela real.
"""

import datetime
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from app.actions.contract import ExternalActionAdapter
from app.core.errors import AmazonaError
from app.money.money import Money
from app.payments.verification import PROOF

#: Las operaciones salientes que un proveedor de pagos declara (ADR 0028).
OPERATION_OPEN = "payment.open"
OPERATION_REFUND = "payment.refund"


class PaymentEventType(StrEnum):
    """El vocabulario normalizado de lo que un proveedor puede contar.

    Cada pasarela real traduce el suyo a este. Dos reglas de la traducción:

    - `payment.failed` es **terminal** para el objeto de cobro. Un proveedor cuyo objeto sigue abierto tras un
      intento fallido (reintentos internos) emite `payment.attempt_failed`, que solo informa;
    - una captura (`payment.succeeded`) es evidencia de dinero recibido y nunca se descarta."""

    PAYMENT_SUCCEEDED = "payment.succeeded"
    PAYMENT_FAILED = "payment.failed"
    PAYMENT_EXPIRED = "payment.expired"
    PAYMENT_ATTEMPT_FAILED = "payment.attempt_failed"
    REFUND_SUCCEEDED = "refund.succeeded"
    REFUND_FAILED = "refund.failed"


@dataclass(frozen=True)
class PaymentProviderCapabilities:
    """Lo que el proveedor **declara** poder hacer. Las capacidades no se infieren."""

    name: str
    supports_idempotency: bool
    supports_lookup: bool
    supports_partial_refund: bool
    #: Autorizar y capturar por separado. En M44 siempre `False`: no se modela.
    supports_authorization_hold: bool
    #: Cómo firma sus webhooks (texto libre para humanos: «hmac-sha256 sobre t.cuerpo»).
    signature_scheme: str
    #: Cuánto puede desviarse el sello de tiempo de un webhook del reloj local (anti-replay).
    signature_tolerance_seconds: int
    currencies: frozenset[str]
    event_types: frozenset[PaymentEventType]


class WebhookVerificationError(AmazonaError):
    """El webhook no es auténtico, está caducado o está mal formado. **No se escribe nada.**

    `reason` es un código estable para la auditoría y las pruebas; la respuesta HTTP no lo cuenta (un atacante no
    tiene por qué saber qué comprobación falló)."""

    reason = "invalid"

    def __init__(self, message: str = "webhook verification failed", *, reason: str | None = None) -> None:
        super().__init__(message)
        if reason is not None:
            self.reason = reason


class MissingSignatureError(WebhookVerificationError):
    reason = "missing_signature"


class InvalidSignatureError(WebhookVerificationError):
    reason = "invalid_signature"


class StaleTimestampError(WebhookVerificationError):
    reason = "stale_timestamp"


class MalformedEventError(WebhookVerificationError):
    reason = "malformed_event"


@dataclass(frozen=True)
class VerifiedPaymentEvent:
    """Un evento de un proveedor **después** de verificar su autenticidad.

    Solo `PaymentProvider.verify_webhook` puede construir uno: `_proof` es una ficha que solo importan los módulos
    de `app/payments/providers/` (un test de arquitectura lo hace cumplir). Todo lo que sigue —registrarlo,
    aplicarlo, cambiar un pago— solo acepta esto, nunca un cuerpo sin verificar.

    No lleva el cuerpo bruto: se guarda su `payload_hash` y los campos de una lista blanca (`data`). Un cuerpo real
    contendría datos personales que no necesitamos."""

    provider: str
    provider_event_id: str
    event_type: PaymentEventType
    occurred_at: datetime.datetime
    payload_hash: str
    #: Lo que el proveedor llama a nuestro cobro, si el evento habla de uno.
    provider_payment_ref: str | None = None
    provider_refund_ref: str | None = None
    #: **Nuestro** `payment_id`, que le enviamos al abrir el cobro: permite emparejar un evento aunque no
    #: guardáramos la referencia del proveedor (la respuesta de abrir se perdió).
    client_reference: str | None = None
    amount: Money | None = None
    #: Solo campos de una lista blanca (códigos de fallo, referencias). Nunca el cuerpo.
    data: dict[str, Any] = field(default_factory=dict)
    _proof: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._proof is not PROOF:
            raise AmazonaError(
                "a VerifiedPaymentEvent can only be built by a provider that verified the event: "
                "an unverified body never becomes a payment fact"
            )
        if not self.provider_event_id.strip():
            raise MalformedEventError("an event needs a provider_event_id", reason="missing_event_id")


@runtime_checkable
class PaymentProvider(ExternalActionAdapter, Protocol):
    """Quien cobra y devuelve dinero, y quien certifica lo que pasó."""

    capabilities: PaymentProviderCapabilities

    def verify_webhook(
        self, *, headers: Mapping[str, str], raw_body: bytes, now: datetime.datetime
    ) -> VerifiedPaymentEvent:
        """Comprueba la firma sobre el **cuerpo bruto**, el sello de tiempo y la forma, **antes** de interpretar
        nada. Lanza `WebhookVerificationError` si algo falla. No escribe en ningún sitio y no conserva el
        cuerpo."""
        ...
