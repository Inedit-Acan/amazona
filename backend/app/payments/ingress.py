"""`PaymentIngress`: la única puerta por la que entra un evento de pago (Milestone 44, ADR 0028 §1).

    CLI simulate-payment ──┐
                           ├─► receive(provider, headers, raw_body)
    webhook HTTP ──────────┘      1. el proveedor verifica la firma sobre el cuerpo bruto (no escribe nada)
                                  2. transacción 1: se guarda el evento (`RECEIVED`) y se confirma
                                  3. transacción 2: `PaymentService.apply` lo aplica

Un evento simulado y el webhook de una pasarela real recorren **este** camino y los aplica **este** servicio. El
CLI no toca pedidos ni cobros; el navegador no confirma nada.

- La verificación va **antes** de cualquier escritura funcional. Si falla, no se escribe ningún evento: solo una
  entrada de auditoría del rechazo, sin el cuerpo.
- El cuerpo bruto vive solo durante la verificación: se guarda su hash y los campos de una lista blanca.
- El mismo evento otra vez es **uno**: `(provider, provider_event_id)` es único. Si llega con otro contenido (otro
  hash), es un 409 y el original queda intacto.
- Un evento que quedó `RECEIVED` (el proceso cayó entre las dos transacciones) se **reanuda** en la reentrega.
"""

import datetime
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import ConflictError, NotFoundError
from app.core.ids import new_correlation_id
from app.db.models.audit import AuditLog
from app.db.models.payment import PaymentEvent
from app.integrations.ports import IntegrationDomain
from app.integrations.registry import ProviderRegistry
from app.payments.domain import EventProcessing
from app.payments.port import PaymentProvider, VerifiedPaymentEvent, WebhookVerificationError
from app.payments.service import PAYMENTS_ACTOR, PaymentService

#: Más de esto no es un webhook: se rechaza antes de calcular nada sobre él.
MAX_WEBHOOK_BODY_BYTES = 64 * 1024


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


@dataclass(frozen=True)
class IngressResult:
    #: `applied`, `stale`, `conflict` o `unmatched` (un `EventProcessing`, en minúsculas).
    outcome: str
    event_id: str
    #: Si el evento ya estaba guardado (una reentrega). Un duplicado ya aplicado no hace nada.
    duplicate: bool


class PaymentIngress:
    def __init__(
        self,
        db: Session,
        *,
        settings: Settings | None = None,
        provider: PaymentProvider | None = None,
        clock: Callable[[], datetime.datetime] = _utcnow,
    ) -> None:
        self._db = db
        self._settings = settings or get_settings()
        self._provider = provider
        self._clock = clock

    def receive(self, provider_name: str, headers: Mapping[str, str], raw_body: bytes) -> IngressResult:
        provider = self._provider_for(provider_name)
        if len(raw_body) > MAX_WEBHOOK_BODY_BYTES:
            self._reject(provider.name, "body_too_large")
            raise WebhookVerificationError("webhook body too large", reason="body_too_large")
        try:
            verified = provider.verify_webhook(headers=headers, raw_body=raw_body, now=self._clock())
        except WebhookVerificationError as exc:
            self._reject(provider.name, exc.reason)
            raise
        event_id, duplicate = self._record(verified)
        outcome = PaymentService(self._db, clock=self._clock).apply(event_id)
        return IngressResult(outcome=outcome.lower(), event_id=event_id, duplicate=duplicate)

    # --- Interno ---------------------------------------------------------------------------------

    def _provider_for(self, name: str) -> PaymentProvider:
        candidate = self._provider
        if candidate is None:
            candidate = ProviderRegistry(self._settings).resolve(IntegrationDomain.PAYMENTS)  # type: ignore[assignment]
        assert candidate is not None
        if candidate.name != name:
            raise NotFoundError(f"payment provider {name!r} is not enabled here")
        return candidate

    def _record(self, verified: VerifiedPaymentEvent) -> tuple[str, bool]:
        """Transacción 1: guarda el evento verificado y confirma. Devuelve su id y si ya existía."""
        event = PaymentEvent(
            provider=verified.provider,
            provider_event_id=verified.provider_event_id,
            event_type=verified.event_type.value,
            provider_payment_ref=verified.provider_payment_ref,
            provider_refund_ref=verified.provider_refund_ref,
            client_reference=verified.client_reference,
            amount=verified.amount.amount if verified.amount is not None else None,
            currency=verified.amount.currency if verified.amount is not None else None,
            occurred_at=verified.occurred_at,
            received_at=self._clock(),
            payload_hash=verified.payload_hash,
            data=verified.data,
            processing_status=EventProcessing.RECEIVED.value,
        )
        try:
            with self._db.begin_nested():
                self._db.add(event)
                self._db.flush()
        except IntegrityError:
            self._db.expire_all()
            existing = self._db.scalars(
                select(PaymentEvent).where(
                    PaymentEvent.provider == verified.provider,
                    PaymentEvent.provider_event_id == verified.provider_event_id,
                )
            ).one()
            if existing.payload_hash != verified.payload_hash:
                self._db.add(
                    AuditLog(
                        actor=PAYMENTS_ACTOR,
                        action="payment_event.payload_mismatch",
                        resource=f"payment_event:{existing.id}",
                        before=None,
                        after={"provider": verified.provider, "provider_event_id": verified.provider_event_id},
                        correlation_id=new_correlation_id(),
                    )
                )
                self._db.commit()
                raise ConflictError(
                    "this provider event id was already received with different content: the original is kept"
                ) from None
            return existing.id, True
        self._db.commit()
        return event.id, False

    def _reject(self, provider: str, reason: str) -> None:
        """Una entrada de auditoría del rechazo. Sin el cuerpo, y sin decir al que llama qué comprobación falló."""
        self._db.add(
            AuditLog(
                actor=PAYMENTS_ACTOR,
                action="payment_webhook.rejected",
                resource=f"payment_provider:{provider}",
                before=None,
                after={"reason": reason},
                correlation_id=new_correlation_id(),
            )
        )
        self._db.commit()
