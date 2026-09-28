"""¿Cabe esta llamada? (Milestone 37, plan maestro §25)

Función pura, así que estas pruebas no tienen base de datos ni red ni reloj. La
propiedad que protegen es la que el propietario puso por escrito: **presupuesto
0 € y denegar por defecto cuando no hay límite autorizado**.
"""

import pytest

from app.costs.decision import Usage, evaluate_api_call
from app.costs.policy import CostPolicy, Pricing, SpendLimit, policy_for

FREE = CostPolicy(
    provider="gratis",
    pricing=Pricing.FREE,
    unit="requests",
    cost_per_unit=0.0,
    currency="EUR",
    quota_units_per_day=100,
    max_units_per_run=8,
)

PAID = CostPolicy(
    provider="de-pago",
    pricing=Pricing.PAID,
    unit="requests",
    cost_per_unit=0.05,
    currency="EUR",
    max_units_per_run=8,
)


def decide(policy=FREE, limit=None, units=1, usage=Usage()):
    return evaluate_api_call(policy=policy, limit=limit, units=units, usage=usage)


# --- El presupuesto ---------------------------------------------------------


def test_a_paid_provider_without_an_authorised_limit_is_denied():
    """La regla del milestone: el presupuesto no se hereda de ninguna parte."""
    decision = decide(policy=PAID)

    assert not decision.allowed
    assert "límite de gasto autorizado" in (decision.reason or "")


def test_a_free_provider_needs_no_authorisation():
    assert decide(policy=FREE).allowed


def test_a_paid_provider_with_a_limit_may_spend_inside_it():
    limit = SpendLimit(provider="de-pago", currency="EUR", max_cost_per_day=1.0)

    decision = decide(policy=PAID, limit=limit, units=2)

    assert decision.allowed
    assert decision.estimated_cost == 0.1


def test_the_daily_cost_limit_counts_what_was_already_spent():
    limit = SpendLimit(provider="de-pago", currency="EUR", max_cost_per_day=1.0)

    decision = decide(policy=PAID, limit=limit, units=1, usage=Usage(cost_today=0.98))

    assert not decision.allowed
    assert "por día" in (decision.reason or "")


def test_the_per_run_cost_limit_is_separate_from_the_daily_one():
    limit = SpendLimit(provider="de-pago", currency="EUR", max_cost_per_run=0.1)

    decision = decide(policy=PAID, limit=limit, units=1, usage=Usage(cost_this_run=0.08))

    assert not decision.allowed
    assert "en esta ejecución" in (decision.reason or "")


def test_a_limit_in_another_currency_is_not_converted_by_us():
    """Sumar euros con dólares es peor que no sumar."""
    limit = SpendLimit(provider="de-pago", currency="USD", max_cost_per_day=100.0)

    decision = decide(policy=PAID, limit=limit)

    assert not decision.allowed
    assert "moneda" in (decision.reason or "")


# --- Las cuotas -------------------------------------------------------------


def test_free_is_not_the_same_as_unlimited():
    """eBay publica 5.000 llamadas al día; Wikimedia pide no pasar de 200/s."""
    decision = decide(policy=FREE, units=1, usage=Usage(units_today=100))

    assert not decision.allowed
    assert "cuota" in (decision.reason or "")


def test_the_owner_can_tighten_a_quota_further_than_the_provider_does():
    limit = SpendLimit(provider="gratis", currency="EUR", max_units_per_day=10)

    decision = decide(policy=FREE, limit=limit, usage=Usage(units_today=10))

    assert not decision.allowed
    assert "cuota de 10" in (decision.reason or "")


def test_the_per_run_cap_protects_the_job_lease():
    """El tope por ejecución no es del proveedor: es nuestro, por el arriendo de
    60 s (ADR 0009)."""
    decision = decide(policy=FREE, units=1, usage=Usage(units_this_run=8))

    assert not decision.allowed
    assert "esta ejecución" in (decision.reason or "")


def test_asking_for_several_units_at_once_is_checked_as_a_whole():
    decision = decide(policy=FREE, units=5, usage=Usage(units_this_run=5))

    assert not decision.allowed


# --- El motivo --------------------------------------------------------------


def test_a_permission_carries_no_reason():
    """Un motivo de permiso no aporta nada y se confundiría con un aviso."""
    assert decide().reason is None


def test_a_denial_always_says_which_limit_stopped_it():
    for decision in (
        decide(policy=PAID),
        decide(policy=FREE, usage=Usage(units_today=100)),
        decide(policy=FREE, usage=Usage(units_this_run=8)),
    ):
        assert decision.reason


def test_the_estimated_cost_is_reported_even_when_denied():
    """Para poder anotar en el libro lo que se habría gastado."""
    limit = SpendLimit(provider="de-pago", currency="EUR", max_cost_per_day=0.01)

    decision = decide(policy=PAID, limit=limit, units=4)

    assert not decision.allowed
    assert decision.estimated_cost == 0.2


# --- Las políticas declaradas ----------------------------------------------


def test_an_unwritten_policy_is_treated_as_paid_and_therefore_denied():
    """Si nadie ha averiguado lo que cuesta, no se llama hasta que alguien lo
    averigüe."""
    policy = policy_for("un-proveedor-sin-politica")

    assert policy.pricing is Pricing.PAID
    assert not decide(policy=policy).allowed


@pytest.mark.parametrize("provider", ["wikimedia-pageviews", "ebay-browse", "fixtures"])
def test_the_declared_policies_are_free_and_say_where_that_was_checked(provider):
    policy = policy_for(provider)

    assert policy.pricing is Pricing.FREE
    assert policy.cost_per_unit == 0.0
    assert policy.source


def test_wikimedia_keeps_working_without_any_authorised_budget():
    """Es la fuente real ya conectada: si el default-deny la alcanzara, el
    Milestone 34 se quedaría sin medir nada."""
    assert decide(policy=policy_for("wikimedia-pageviews")).allowed


def test_ebay_carries_the_quota_its_documentation_publishes():
    policy = policy_for("ebay-browse")

    assert policy.quota_units_per_day == 5000
    decision = decide(policy=policy, usage=Usage(units_today=5000))
    assert not decision.allowed
