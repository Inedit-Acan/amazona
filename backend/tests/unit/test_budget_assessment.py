"""¿Cabe este gasto? — la ausencia de información nunca es un permiso (hardening pre-M44, D12).

Antes, sin fila de presupuesto, y con un importe ausente, el ActionGate aprobaba el gasto
(`BudgetSignal()` valía `approved=True`): «no hay límite que oponer». Es la misma confusión que
M37 ya había descartado para los costes de las APIs: el presupuesto no se hereda de ninguna parte.

La función es pura, como `evaluate_action` y `evaluate_api_call`: aquí es una tabla.
"""

import pytest

from app.budgets.engine import BudgetSnapshot, BudgetStatus, assess_spend


def snapshot(*, hard: float = 100_000.0, reserved: float = 0.0, committed: float = 0.0) -> BudgetSnapshot:
    return BudgetSnapshot(hard_limit=hard, soft_limit=None, reserved=reserved, committed=committed, spent=committed)


# --- Sin presupuesto autorizado -------------------------------------------------------


def test_with_no_budget_a_real_spend_is_denied():
    result = assess_spend(amount=10.0, snapshot=None, simulated=False)

    assert (result.approved, result.status) == (False, BudgetStatus.NO_BUDGET_RECORD)
    assert "authorised" in result.reason


def test_with_no_budget_a_simulated_spend_passes_and_says_so():
    result = assess_spend(amount=10.0, snapshot=None, simulated=True)

    assert (result.approved, result.status) == (True, BudgetStatus.SIMULATED_NO_BUDGET)
    assert "simulated" in result.reason


def test_no_budget_in_a_simulation_is_not_the_same_as_no_limit():
    """Quedan estados distintos: uno dice «se deja pasar porque es simulado», nunca «no hay límite»."""
    assert assess_spend(amount=1.0, snapshot=None, simulated=True).status is not BudgetStatus.AVAILABLE


# --- Importe desconocido y cero conocido ----------------------------------------------


@pytest.mark.parametrize("simulated", [True, False])
@pytest.mark.parametrize("budget", [None, snapshot()])
def test_an_unknown_cost_is_always_denied_because_unknown_is_not_zero(simulated, budget):
    result = assess_spend(amount=None, snapshot=budget, simulated=simulated)

    assert (result.approved, result.status) == (False, BudgetStatus.UNKNOWN_COST)


def test_a_negative_amount_is_not_a_cost():
    result = assess_spend(amount=-5.0, snapshot=snapshot(), simulated=True)

    assert (result.approved, result.status) == (False, BudgetStatus.UNKNOWN_COST)


@pytest.mark.parametrize("budget", [None, snapshot(), snapshot(hard=100.0, reserved=100.0)])
@pytest.mark.parametrize("simulated", [True, False])
def test_a_known_zero_cost_passes_whatever_the_budget_looks_like(budget, simulated):
    """Cero conocido consume cero presupuesto: no lo frena que falte ni que esté agotado."""
    result = assess_spend(amount=0.0, snapshot=budget, simulated=simulated)

    assert (result.approved, result.status) == (True, BudgetStatus.ZERO_COST)


# --- Con presupuesto autorizado: manda el presupuesto, también en simulación ----------


@pytest.mark.parametrize("simulated", [True, False])
def test_an_amount_that_fits_is_available(simulated):
    result = assess_spend(amount=60_000.0, snapshot=snapshot(), simulated=simulated)

    assert (result.approved, result.status) == (True, BudgetStatus.AVAILABLE)


@pytest.mark.parametrize("simulated", [True, False])
def test_an_amount_that_does_not_fit_is_exhausted_even_in_a_simulation(simulated):
    """La simulación solo relaja la **ausencia** de presupuesto, nunca un techo que sí existe."""
    result = assess_spend(amount=60_000.0, snapshot=snapshot(reserved=60_000.0), simulated=simulated)

    assert (result.approved, result.status) == (False, BudgetStatus.EXHAUSTED)
    assert "exceeds hard limit" in result.reason


def test_what_is_reserved_and_what_is_committed_both_count():
    assert assess_spend(
        amount=40_000.0, snapshot=snapshot(reserved=30_000.0, committed=30_000.0), simulated=False
    ).approved
    assert not assess_spend(
        amount=40_001.0, snapshot=snapshot(reserved=30_000.0, committed=30_000.0), simulated=False
    ).approved


def test_the_soft_limit_warns_and_does_not_deny():
    budget = BudgetSnapshot(hard_limit=100.0, soft_limit=50.0, reserved=0.0, committed=0.0, spent=0.0)

    result = assess_spend(amount=70.0, snapshot=budget, simulated=False)

    assert result.approved is True
    assert "soft limit" in result.warning
