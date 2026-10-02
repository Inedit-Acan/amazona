"""El proveedor de pagos simulado (Milestone 44, ADR 0028 §1): la única implementación de este milestone.

No habla con nadie y no mueve dinero. Pero **no es otra lógica**: cumple el mismo contrato que cumplirá una
pasarela real, y los eventos que emite están firmados y se verifican con el mismo `verify_webhook`. Un evento
simulado y el webhook de una pasarela futura entran por la misma puerta (`PaymentIngress`) y los aplica el mismo
`PaymentService`.

## La clave de firma es efímera

Se genera con `secrets.token_bytes` la primera vez que se necesita en el proceso, **no se guarda en ningún
sitio, no se imprime y no se versiona**. Dos consecuencias buscadas:

- una petición HTTP externa al webhook del proveedor `simulated-payments` **no puede** firmar un evento
  válido: solo el propio proceso (el CLI `simulate-payment`, las pruebas) tiene la clave;
- no hay ningún secreto que filtrar ni rotar.

## Idempotencia y consulta

Repetir `execute` con la misma clave devuelve la misma respuesta y no cuenta otro efecto; otra clave es otra
operación. `lookup` devuelve lo ejecutado o `None`. Las referencias salen de la clave (`simpay_…`, `simref_…`),
así que son estables aunque el proceso se reinicie.
"""

import datetime
import hashlib
import hmac
import json
import secrets
import threading
from collections.abc import Callable, Mapping
from decimal import InvalidOperation
from typing import Any

from app.actions.contract import ActionRequest, ActionResponse, ProviderRejectedError
from app.core.errors import ValidationError
from app.money.money import Money
from app.payments.port import (
    OPERATION_OPEN,
    OPERATION_REFUND,
    InvalidSignatureError,
    MalformedEventError,
    MissingSignatureError,
    PaymentEventType,
    PaymentProviderCapabilities,
    StaleTimestampError,
    VerifiedPaymentEvent,
)
from app.payments.verification import PROOF, payload_hash

PROVIDER_NAME = "simulated-payments"
SIGNATURE_HEADER = "Amazona-Simulated-Signature"
SIGNATURE_TOLERANCE_SECONDS = 300

_process_key: bytes | None = None
_process_key_lock = threading.Lock()


def process_signing_key() -> bytes:
    """La clave de este proceso: aleatoria, efímera, nunca persistida."""
    global _process_key  # noqa: PLW0603 - el estado del proceso es justo lo que se quiere
    with _process_key_lock:
        if _process_key is None:
            _process_key = secrets.token_bytes(32)
        return _process_key


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


def _digest(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:20]


class SimulatedPaymentProvider:
    name = PROVIDER_NAME
    supports_idempotency = True
    capabilities = PaymentProviderCapabilities(
        name=PROVIDER_NAME,
        supports_idempotency=True,
        supports_lookup=True,
        supports_partial_refund=True,
        supports_authorization_hold=False,
        signature_scheme="hmac-sha256 over '<t>.<raw body>' in the Amazona-Simulated-Signature header (t=…,v1=…)",
        signature_tolerance_seconds=SIGNATURE_TOLERANCE_SECONDS,
        currencies=frozenset({"EUR", "USD", "GBP"}),
        event_types=frozenset(PaymentEventType),
    )

    #: Lo ejecutado «en el mundo», compartido por todo el proceso: dos instancias del registro ven lo mismo.
    _shared_operations: dict[str, ActionResponse] = {}
    _shared_lock = threading.Lock()

    def __init__(
        self,
        *,
        signing_key: bytes | None = None,
        operations: dict[str, ActionResponse] | None = None,
        clock: Callable[[], datetime.datetime] = _utcnow,
    ) -> None:
        self._key = signing_key if signing_key is not None else process_signing_key()
        self._operations = operations if operations is not None else self._shared_operations
        self._clock = clock

    # --- Operaciones salientes -------------------------------------------------------------

    def execute(self, request: ActionRequest) -> ActionResponse:
        if request.operation not in (OPERATION_OPEN, OPERATION_REFUND):
            raise ProviderRejectedError(f"{PROVIDER_NAME} does not support {request.operation}")
        if not request.idempotency_key:
            raise ProviderRejectedError("this provider needs the idempotency key of the operation")
        payload = request.payload
        if request.operation == OPERATION_OPEN:
            missing = [name for name in ("payment_id", "amount", "currency") if not payload.get(name)]
            prefix = "simpay_"
        else:
            missing = [name for name in ("provider_payment_ref", "amount", "currency") if not payload.get(name)]
            prefix = "simref_"
        if missing:
            raise ProviderRejectedError(f"the request lacks {', '.join(missing)}")

        key = request.idempotency_key
        with self._shared_lock:
            existing = self._operations.get(key)
            if existing is not None:
                return existing  # la misma clave no repite el efecto
            response = ActionResponse(
                reference=f"{prefix}{_digest(key)}",
                detail={
                    "simulated": True,
                    "operation": request.operation,
                    "client_reference": payload.get("payment_id"),
                },
            )
            self._operations[key] = response
            return response

    def lookup(self, idempotency_key: str) -> ActionResponse | None:
        with self._shared_lock:
            return self._operations.get(idempotency_key)

    def effect_count(self) -> int:
        """Cuántos efectos distintos «ocurrieron»: una entrada por clave."""
        with self._shared_lock:
            return len(self._operations)

    # --- Eventos entrantes ----------------------------------------------------------------------

    def simulate_event(
        self,
        event_type: PaymentEventType,
        *,
        provider_payment_ref: str | None = None,
        provider_refund_ref: str | None = None,
        client_reference: str | None = None,
        amount: Money | None = None,
        failure_code: str | None = None,
        event_id: str | None = None,
        occurred_at: datetime.datetime | None = None,
        timestamp: datetime.datetime | None = None,
    ) -> tuple[dict[str, str], bytes]:
        """Un evento firmado como lo enviaría el proveedor: las cabeceras y el cuerpo bruto. Quien lo reciba debe
        pasarlo por `verify_webhook` como cualquier otro. `timestamp` es el sello de la firma (por defecto, ahora);
        `occurred_at`, cuándo ocurrió lo que cuenta."""
        body: dict[str, Any] = {
            "id": event_id or f"evt_{secrets.token_hex(10)}",
            "type": event_type.value,
            "created": (occurred_at or self._clock()).astimezone(datetime.UTC).isoformat(),
            "data": {
                key: value
                for key, value in {
                    "payment_ref": provider_payment_ref,
                    "refund_ref": provider_refund_ref,
                    "client_reference": client_reference,
                    "amount": str(amount.amount) if amount is not None else None,
                    "currency": amount.currency if amount is not None else None,
                    "failure_code": failure_code,
                }.items()
                if value is not None
            },
        }
        raw = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return self.sign(raw, timestamp=timestamp), raw

    def sign(self, raw_body: bytes, *, timestamp: datetime.datetime | None = None) -> dict[str, str]:
        stamp = int((timestamp or self._clock()).timestamp())
        signature = hmac.new(self._key, f"{stamp}.".encode() + raw_body, hashlib.sha256).hexdigest()
        return {SIGNATURE_HEADER: f"t={stamp},v1={signature}"}

    def verify_webhook(
        self, *, headers: Mapping[str, str], raw_body: bytes, now: datetime.datetime
    ) -> VerifiedPaymentEvent:
        self._authenticate(headers, raw_body, now)
        return self._interpret(raw_body)

    def _authenticate(self, headers: Mapping[str, str], raw_body: bytes, now: datetime.datetime) -> None:
        """La firma sobre el cuerpo bruto y el sello de tiempo. No interpreta nada del cuerpo."""
        lowered = {name.lower(): value for name, value in headers.items()}
        header = lowered.get(SIGNATURE_HEADER.lower())
        if not header:
            raise MissingSignatureError()
        parts = dict(item.split("=", 1) for item in header.split(",") if "=" in item)
        try:
            stamp = int(parts["t"])
            presented = parts["v1"]
        except (KeyError, ValueError) as exc:
            raise InvalidSignatureError() from exc

        # La firma se comprueba ANTES que el sello de tiempo y que cualquier interpretación del cuerpo: un
        # atacante sin la clave no aprende nada sobre la forma esperada.
        expected = hmac.new(self._key, f"{stamp}.".encode() + raw_body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, presented):
            raise InvalidSignatureError()
        if abs(now.timestamp() - stamp) > SIGNATURE_TOLERANCE_SECONDS:
            raise StaleTimestampError()

    def _interpret(self, raw_body: bytes) -> VerifiedPaymentEvent:
        """Solo después de autenticar: la forma del evento y sus campos."""
        try:
            document = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise MalformedEventError() from exc
        if not isinstance(document, dict):
            raise MalformedEventError()
        data = document.get("data")
        event_id = document.get("id")
        if not isinstance(event_id, str) or not event_id.strip() or len(event_id) > 128:
            raise MalformedEventError(reason="missing_event_id")
        if not isinstance(data, dict):
            raise MalformedEventError()
        try:
            event_type = PaymentEventType(str(document.get("type")))
            created = datetime.datetime.fromisoformat(str(document.get("created")))
        except ValueError as exc:
            raise MalformedEventError() from exc
        if created.tzinfo is None or event_type not in self.capabilities.event_types:
            raise MalformedEventError()

        amount: Money | None = None
        raw_amount = data.get("amount")
        if raw_amount is not None:
            currency = data.get("currency")
            if not isinstance(raw_amount, str) or not isinstance(currency, str):
                raise MalformedEventError(reason="bad_amount")  # un número JSON sería un float
            try:
                amount = Money.of(raw_amount, currency)
            except (ValidationError, InvalidOperation) as exc:
                raise MalformedEventError(reason="bad_amount") from exc

        return VerifiedPaymentEvent(
            provider=self.name,
            provider_event_id=event_id,
            event_type=event_type,
            occurred_at=created.astimezone(datetime.UTC),
            payload_hash=payload_hash(raw_body),
            provider_payment_ref=_text(data.get("payment_ref")),
            provider_refund_ref=_text(data.get("refund_ref")),
            client_reference=_text(data.get("client_reference")),
            amount=amount,
            data={"failure_code": _text(data.get("failure_code"))},
            _proof=PROOF,
        )


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
