"""El proveedor de pagos simulado cumple el contrato, y la batería distingue a uno honesto de uno que miente.

Es la batería que pasará cualquier pasarela real con su transporte falso (ADR 0028 §1). Aquí se prueba contra el
simulador y contra tres proveedores tramposos —acepta cualquier cuerpo, ignora el sello de tiempo, firma solo la
cabecera—, para que la batería no pueda volverse permisiva sin que lo note una prueba.
"""

import datetime
import hashlib
import hmac
import secrets

import pytest
from order_provider_contract_test_support import (
    NOW,
    assert_payment_provider_honours_contract,
)

from app.core.errors import AmazonaError
from app.money.money import Money
from app.payments.port import (
    InvalidSignatureError,
    MalformedEventError,
    PaymentEventType,
    VerifiedPaymentEvent,
)
from app.payments.providers.simulated import (
    PROVIDER_NAME,
    SIGNATURE_HEADER,
    SimulatedPaymentProvider,
    process_signing_key,
)
from app.payments.verification import PROOF

FAILED = (AssertionError, pytest.fail.Exception)


class Signer:
    """Produce webhooks para un simulador: bien firmados con su clave, o con la de otro proveedor."""

    def __init__(self, provider: SimulatedPaymentProvider, stranger: SimulatedPaymentProvider) -> None:
        self._provider, self._stranger = provider, stranger

    def signed(self, event_type, *, timestamp):
        return self._provider.simulate_event(
            event_type,
            provider_payment_ref="simpay_abc",
            client_reference="pay-1",
            amount=Money.of("12.50", "EUR"),
            timestamp=timestamp,
        )

    def foreign(self, event_type, *, timestamp):
        return self._stranger.simulate_event(
            event_type,
            provider_payment_ref="simpay_abc",
            client_reference="pay-1",
            amount=Money.of("12.50", "EUR"),
            timestamp=timestamp,
        )


def providers(**kwargs):
    key = secrets.token_bytes(32)
    ops: dict = {}
    mine = SimulatedPaymentProvider(signing_key=key, operations=ops, **kwargs)
    stranger = SimulatedPaymentProvider(signing_key=secrets.token_bytes(32), operations={})
    return mine, Signer(mine, stranger), ops


# --- El simulador cumple ---------------------------------------------------------------------


def test_the_simulated_provider_honours_the_contract():
    provider, signer, ops = providers()

    assert_payment_provider_honours_contract(provider, signer, effects=lambda: len(ops))


def test_the_simulated_provider_declares_what_it_can_do():
    provider, _, _ = providers()
    caps = provider.capabilities

    assert caps.name == PROVIDER_NAME and provider.name == PROVIDER_NAME
    assert caps.supports_idempotency and caps.supports_lookup and caps.supports_partial_refund
    assert caps.supports_authorization_hold is False, "authorize/capture is not modelled in M44"
    assert caps.event_types == frozenset(PaymentEventType)


# --- Tres proveedores tramposos: la batería los distingue ------------------------------------------


class AcceptsAnything(SimulatedPaymentProvider):
    """No comprueba la firma: cualquiera puede inventarse un cobro."""

    def _authenticate(self, headers, raw_body, now):
        return None


class IgnoresTheTimestamp(SimulatedPaymentProvider):
    """Comprueba la firma pero no la ventana de tiempo: un webhook capturado se puede repetir para siempre."""

    def _authenticate(self, headers, raw_body, now):
        lowered = {k.lower(): v for k, v in headers.items()}
        header = lowered.get(SIGNATURE_HEADER.lower())
        if not header:
            from app.payments.port import MissingSignatureError

            raise MissingSignatureError()
        parts = dict(item.split("=", 1) for item in header.split(",") if "=" in item)
        expected = hmac.new(self._key, f"{parts['t']}.".encode() + raw_body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, parts["v1"]):
            raise InvalidSignatureError()


class SignsOnlyTheHeader(SimulatedPaymentProvider):
    """Firma el sello de tiempo y no el cuerpo: se puede cambiar el importe sin romper la firma."""

    def sign(self, raw_body, *, timestamp=None):
        stamp = int((timestamp or self._clock()).timestamp())
        signature = hmac.new(self._key, f"{stamp}.".encode(), hashlib.sha256).hexdigest()
        return {SIGNATURE_HEADER: f"t={stamp},v1={signature}"}

    def _authenticate(self, headers, raw_body, now):
        lowered = {k.lower(): v for k, v in headers.items()}
        header = lowered.get(SIGNATURE_HEADER.lower())
        if not header:
            from app.payments.port import MissingSignatureError

            raise MissingSignatureError()
        parts = dict(item.split("=", 1) for item in header.split(",") if "=" in item)
        expected = hmac.new(self._key, f"{parts['t']}.".encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, parts["v1"]):
            raise InvalidSignatureError()
        if abs(now.timestamp() - int(parts["t"])) > 300:
            from app.payments.port import StaleTimestampError

            raise StaleTimestampError()


@pytest.mark.parametrize("cheat", [AcceptsAnything, IgnoresTheTimestamp, SignsOnlyTheHeader])
def test_the_battery_catches_a_provider_that_verifies_badly(cheat):
    key = secrets.token_bytes(32)
    ops: dict = {}
    provider = cheat(signing_key=key, operations=ops)
    stranger = SimulatedPaymentProvider(signing_key=secrets.token_bytes(32), operations={})

    with pytest.raises(FAILED):
        assert_payment_provider_honours_contract(provider, Signer(provider, stranger), effects=lambda: len(ops))


class RepeatsTheEffect(SimulatedPaymentProvider):
    """Dice ser idempotente y cuenta un efecto nuevo cada vez que se repite la clave."""

    def execute(self, request):
        response = super().execute(request)
        self._operations[f"{request.idempotency_key}#{len(self._operations)}"] = response
        return response


def test_the_battery_catches_a_provider_that_claims_idempotency_and_repeats_the_effect():
    key = secrets.token_bytes(32)
    ops: dict = {}
    provider = RepeatsTheEffect(signing_key=key, operations=ops)
    stranger = SimulatedPaymentProvider(signing_key=secrets.token_bytes(32), operations={})

    with pytest.raises(FAILED):
        assert_payment_provider_honours_contract(provider, Signer(provider, stranger), effects=lambda: len(ops))


# --- Lo específico del simulador ---------------------------------------------------------------------


def test_an_event_cannot_be_declared_verified_without_the_proof():
    with pytest.raises(AmazonaError, match="can only be built by a provider"):
        VerifiedPaymentEvent(
            provider=PROVIDER_NAME,
            provider_event_id="evt_1",
            event_type=PaymentEventType.PAYMENT_SUCCEEDED,
            occurred_at=NOW,
            payload_hash="0" * 64,
        )

    event = VerifiedPaymentEvent(
        provider=PROVIDER_NAME,
        provider_event_id="evt_1",
        event_type=PaymentEventType.PAYMENT_SUCCEEDED,
        occurred_at=NOW,
        payload_hash="0" * 64,
        _proof=PROOF,
    )
    assert event.provider_event_id == "evt_1"


def test_the_raw_body_is_not_kept_in_the_verified_event_only_its_hash():
    provider, signer, _ = providers()
    headers, raw = signer.signed(PaymentEventType.PAYMENT_SUCCEEDED, timestamp=NOW)

    event = provider.verify_webhook(headers=headers, raw_body=raw, now=NOW)

    assert event.payload_hash == hashlib.sha256(raw).hexdigest()
    assert raw.decode() not in repr(event)
    assert set(event.data) == {"failure_code"}, "only whitelisted fields survive"
    assert event.amount == Money.of("12.50", "EUR")
    assert event.client_reference == "pay-1" and event.provider_payment_ref == "simpay_abc"


def test_a_signed_body_that_is_not_a_valid_event_is_malformed_not_applied():
    provider, _, _ = providers()
    for raw in (b"not json", b"[]", b'{"id":"evt","type":"payment.succeeded","data":{}}', b'{"id":"","type":"x"}'):
        headers = provider.sign(raw, timestamp=NOW)
        with pytest.raises(MalformedEventError):
            provider.verify_webhook(headers=headers, raw_body=raw, now=NOW)


def test_a_json_number_is_not_an_amount_because_it_would_be_a_float():
    provider, _, _ = providers()
    raw = (
        b'{"id":"evt_9","type":"payment.succeeded","created":"2026-10-02T12:00:00+00:00",'
        b'"data":{"amount":12.5,"currency":"EUR","payment_ref":"p"}}'
    )
    headers = provider.sign(raw, timestamp=NOW)

    with pytest.raises(MalformedEventError):
        provider.verify_webhook(headers=headers, raw_body=raw, now=NOW)


def test_the_signature_is_checked_before_anything_in_the_body_is_interpreted():
    provider, _, _ = providers()
    stranger = SimulatedPaymentProvider(signing_key=secrets.token_bytes(32), operations={})
    headers = stranger.sign(b"definitely not json", timestamp=NOW)

    with pytest.raises(InvalidSignatureError):  # no «malformado»: no se aprende nada de un cuerpo sin firma válida
        provider.verify_webhook(headers=headers, raw_body=b"definitely not json", now=NOW)


def test_the_signing_key_is_ephemeral_and_not_written_anywhere():
    key = process_signing_key()

    assert len(key) == 32 and key == process_signing_key(), "one key per process"
    assert SimulatedPaymentProvider().capabilities.signature_scheme  # sin clave en las capacidades
    assert key.hex() not in repr(SimulatedPaymentProvider().capabilities)


def test_a_foreign_process_cannot_sign_for_this_provider():
    mine = SimulatedPaymentProvider()
    other_process = SimulatedPaymentProvider(signing_key=secrets.token_bytes(32), operations={})
    headers, raw = other_process.simulate_event(
        PaymentEventType.PAYMENT_SUCCEEDED, timestamp=datetime.datetime.now(datetime.UTC)
    )

    with pytest.raises(InvalidSignatureError):
        mine.verify_webhook(headers=headers, raw_body=raw, now=datetime.datetime.now(datetime.UTC))
