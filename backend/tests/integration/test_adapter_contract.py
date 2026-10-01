"""El contrato de un adaptador con efecto, y que la batería de conformidad distingue a uno honesto de uno que miente.

La batería (`adapter_contract_test_support.py`) es lo que pasará cada adaptador real de M44 con su transporte
falso. Aquí se prueba contra los adaptadores que ya existen —el simulado y los falsos de las pruebas— y contra tres
que incumplen el contrato, para que la batería no pueda volverse permisiva sin que lo note una prueba.
"""

import pytest
from action_test_support import FakeLookupProviderAdapter, FakeProviderAdapter
from adapter_contract_test_support import assert_adapter_honours_contract, request_for

from app.actions.contract import (
    ActionRequest,
    ActionResponse,
    ExternalActionAdapter,
    LookupCapableAdapter,
    SimulatedAdapter,
)

# --- Los adaptadores que cumplen ------------------------------------------------------


def test_the_simulated_adapter_honours_the_contract():
    assert_adapter_honours_contract(SimulatedAdapter())


def test_an_idempotent_provider_honours_the_contract():
    fake = FakeProviderAdapter()

    assert_adapter_honours_contract(fake, effects=lambda: fake.effect_count)


def test_an_idempotent_provider_that_can_be_asked_honours_the_contract():
    fake = FakeLookupProviderAdapter()

    assert_adapter_honours_contract(fake, effects=lambda: fake.effect_count)
    assert isinstance(fake, LookupCapableAdapter)


def test_a_provider_that_declares_no_idempotency_honours_the_contract_by_saying_so():
    fake = FakeProviderAdapter(supports_idempotency=False)

    assert_adapter_honours_contract(fake, effects=lambda: fake.effect_count)

    assert request_for(fake).idempotency_key is None  # no se le manda una clave que no respetaría


def test_the_simulated_adapter_is_a_valid_external_action_adapter():
    assert isinstance(SimulatedAdapter(), ExternalActionAdapter)
    assert not isinstance(SimulatedAdapter(), LookupCapableAdapter)  # no sabe consultar, y lo dice no teniéndolo


# --- Los que incumplen: la batería tiene que notarlo ------------------------------------


class LyingAdapter:
    """Dice ser idempotente y repite el efecto cada vez que se le llama con la misma clave."""

    name = "liar"
    supports_idempotency = True

    def __init__(self) -> None:
        self.effects = 0

    def execute(self, request: ActionRequest) -> ActionResponse:
        self.effects += 1
        return ActionResponse(reference=f"liar:{request.idempotency_key}")


class SameReferenceForEverything:
    """Idempotente de verdad, pero responde lo mismo a claves distintas: no distingue las operaciones."""

    name = "lumpy"
    supports_idempotency = True

    def __init__(self) -> None:
        self.effects = 0

    def execute(self, request: ActionRequest) -> ActionResponse:
        self.effects += 1
        return ActionResponse(reference="one-reference-for-all")


class LookupThatInventsThings(FakeLookupProviderAdapter):
    """Una consulta que «encuentra» operaciones que nunca ejecutó: confirmaría un efecto que no ocurrió."""

    def lookup(self, idempotency_key):
        return self._by_key.get(idempotency_key) or ActionResponse(reference="made-up")


def test_the_battery_catches_an_adapter_that_claims_idempotency_and_repeats_the_effect():
    liar = LyingAdapter()

    with pytest.raises(AssertionError, match="repeated the effect"):
        assert_adapter_honours_contract(liar, effects=lambda: liar.effects)


def test_the_battery_catches_an_adapter_that_cannot_tell_two_operations_apart():
    lumpy = SameReferenceForEverything()

    with pytest.raises(AssertionError, match="different key must be a different operation"):
        assert_adapter_honours_contract(lumpy)


def test_the_battery_catches_a_lookup_that_finds_what_never_happened():
    with pytest.raises(AssertionError, match="lookup must answer None"):
        assert_adapter_honours_contract(LookupThatInventsThings())


def test_the_battery_catches_an_adapter_that_does_not_declare_its_capability():
    class Undeclared:
        name = "undeclared"

        def execute(self, request):
            return ActionResponse()

    with pytest.raises(AssertionError):
        assert_adapter_honours_contract(Undeclared())
