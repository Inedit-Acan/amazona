"""`PaymentProvider.kind`: el origen del dinero es un atributo estructurado y obligatorio (Milestone 46, ADR 0031 §4).

Lo que se prueba, sin base de datos:

- el simulador **declara** `mock` por sí mismo, y sus subclases lo heredan explícitamente;
- solo `mock`, `sandbox` y `real` valen: ni `composite`, ni una cadena suelta, ni nada;
- el registro de proveedores comprueba, al cargar y al resolver, que el `kind` de cada adaptador de pagos coincide con
  la
  clave bajo la que se registra;
- el tipo **no se deduce** del nombre, de `Order.is_simulated` ni del entorno.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.core.config import Settings
from app.integrations.ports import IntegrationDomain, ProviderKind
from app.integrations.registry import (
    IMPLEMENTATIONS,
    ProviderRegistry,
    validate_payment_implementations,
)
from app.payments.port import (
    PAYMENT_PROVIDER_KINDS,
    PaymentProvider,
    PaymentProviderKindError,
    require_payment_kind,
)
from app.payments.providers.simulated import PROVIDER_NAME, SimulatedPaymentProvider

PAYMENTS = IntegrationDomain.PAYMENTS
BACKEND = Path(__file__).resolve().parents[2]


def provider_of(kind, *, name: str = PROVIDER_NAME) -> SimulatedPaymentProvider:
    """Un simulador que declara `kind` (lo que sea), con el nombre que se quiera."""
    cls = type("Declared", (SimulatedPaymentProvider,), {"kind": kind, "name": name})
    return cls(operations={})


def test_the_simulator_declares_mock_by_itself():
    assert SimulatedPaymentProvider.kind is ProviderKind.MOCK
    assert require_payment_kind(SimulatedPaymentProvider(operations={})) is ProviderKind.MOCK


def test_a_subclass_inherits_the_declared_kind_and_may_declare_another_explicitly():
    class Inherits(SimulatedPaymentProvider):
        pass

    assert require_payment_kind(Inherits(operations={})) is ProviderKind.MOCK
    assert require_payment_kind(provider_of(ProviderKind.SANDBOX)) is ProviderKind.SANDBOX
    assert require_payment_kind(provider_of(ProviderKind.REAL)) is ProviderKind.REAL


def test_the_allowed_kinds_are_exactly_mock_sandbox_and_real():
    assert PAYMENT_PROVIDER_KINDS == {ProviderKind.MOCK, ProviderKind.SANDBOX, ProviderKind.REAL}
    assert ProviderKind.COMPOSITE not in PAYMENT_PROVIDER_KINDS, (
        "a composite may fill in with fixtures: it is not an origin"
    )


@pytest.mark.parametrize(
    "bad",
    [ProviderKind.COMPOSITE, "mock", "sandbox", "real", "MOCK", None, 0, True, object()],
    ids=lambda v: repr(v)[:30],
)
def test_anything_else_is_refused_and_a_loose_string_is_not_a_kind(bad):
    with pytest.raises(PaymentProviderKindError):
        require_payment_kind(provider_of(bad))


def test_a_provider_that_declares_nothing_is_refused():
    class Silent:
        name = "silent"

    with pytest.raises(PaymentProviderKindError, match="Silent does not declare"):
        require_payment_kind(Silent())


def test_the_kind_is_part_of_the_port():
    assert "kind" in PaymentProvider.__annotations__
    assert isinstance(SimulatedPaymentProvider(operations={}), PaymentProvider)


@pytest.mark.parametrize("name", ["simulated-payments", "stripe-live", "sandbox-gateway", "mock", "real-money", ""])
def test_the_kind_does_not_depend_on_the_name(name):
    """Un proveedor llamado «real-money» que declara `mock` es `mock`; uno llamado «simulated-payments» que declara
    `real` es `real`: el nombre no clasifica nada."""
    assert require_payment_kind(provider_of(ProviderKind.MOCK, name=name)) is ProviderKind.MOCK
    assert require_payment_kind(provider_of(ProviderKind.REAL, name=name)) is ProviderKind.REAL
    assert require_payment_kind(provider_of(ProviderKind.SANDBOX, name=name)) is ProviderKind.SANDBOX


# --- El registro
# --------------------------------------------------------------------------------------------------------


def test_every_registered_payment_provider_declares_the_kind_it_is_registered_under():
    for key, factory in IMPLEMENTATIONS[PAYMENTS].items():
        assert key in PAYMENT_PROVIDER_KINDS
        assert factory.kind is key, f"{factory.__name__} is registered as {key} but declares {factory.kind}"
    validate_payment_implementations()  # no lanza


def test_the_registry_refuses_at_load_time_a_provider_that_declares_another_kind_than_its_key(tmp_path):
    """La validación corre al **cargar** el módulo, no solo al resolver: un adaptador mal etiquetado no llega a existir.
    En un subproceso, para no recargar módulos dentro del proceso de las pruebas."""
    code = """
from app.integrations.ports import ProviderKind
from app.payments.providers.simulated import SimulatedPaymentProvider

SimulatedPaymentProvider.kind = ProviderKind.SANDBOX
try:
    import app.integrations.registry
except Exception as exc:
    print(type(exc).__name__ + ": " + str(exc))
"""
    env = {**os.environ, "PYTHONPATH": str(BACKEND), "ENVIRONMENT": "development"}
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120
    )

    assert "PaymentProviderKindError: " in result.stdout, result.stdout + result.stderr
    assert "registered as 'mock' but declares kind 'sandbox'" in result.stdout


def test_the_registry_refuses_a_provider_registered_under_a_kind_it_does_not_declare():
    mislabelled = {PAYMENTS: {ProviderKind.SANDBOX: SimulatedPaymentProvider}}

    with pytest.raises(PaymentProviderKindError, match="registered as 'sandbox' but declares kind 'mock'"):
        validate_payment_implementations(mislabelled)  # type: ignore[arg-type]


def test_the_registry_refuses_a_provider_with_no_kind_or_registered_as_composite():
    no_kind = type("NoKind", (), {})
    with pytest.raises(PaymentProviderKindError):
        validate_payment_implementations({PAYMENTS: {ProviderKind.MOCK: no_kind}})  # type: ignore[arg-type]
    with pytest.raises(PaymentProviderKindError, match="cannot be registered under 'composite'"):
        validate_payment_implementations(
            {PAYMENTS: {ProviderKind.COMPOSITE: SimulatedPaymentProvider}}  # type: ignore[arg-type]
        )


def test_resolving_returns_a_provider_whose_kind_matches_what_was_asked(monkeypatch):
    resolved = ProviderRegistry(Settings(payments_provider=ProviderKind.MOCK)).resolve(PAYMENTS)

    assert require_payment_kind(resolved) is ProviderKind.MOCK


def test_resolving_refuses_an_adapter_that_declares_another_kind_than_the_one_asked(monkeypatch):
    liar = type("Liar", (SimulatedPaymentProvider,), {"kind": ProviderKind.REAL})
    monkeypatch.setitem(IMPLEMENTATIONS[PAYMENTS], ProviderKind.SANDBOX, liar)
    registry = ProviderRegistry(Settings(payments_provider=ProviderKind.SANDBOX))

    with pytest.raises(PaymentProviderKindError, match="resolved for 'sandbox' declares kind 'real'"):
        registry.resolve(PAYMENTS)


def test_resolving_refuses_an_adapter_without_a_kind(monkeypatch):
    class NoKind(SimulatedPaymentProvider):
        kind = None  # type: ignore[assignment]

    monkeypatch.setitem(IMPLEMENTATIONS[PAYMENTS], ProviderKind.SANDBOX, NoKind)
    registry = ProviderRegistry(Settings(payments_provider=ProviderKind.SANDBOX))

    with pytest.raises(PaymentProviderKindError):
        registry.resolve(PAYMENTS)
