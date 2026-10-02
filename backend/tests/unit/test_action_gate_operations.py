"""El gate gobierna por operación, no solo por tipo de acción (Milestone 44, ADR 0028 §5 y §7).

Tres cosas nuevas, todas sobre la función pura:

- `COLLECT_PAYMENT`: abrir un cobro no gasta, pero no queda fuera del gate;
- `REFUND`: devolver dinero cobrado no gasta del presupuesto operativo y no se juzga por el producto;
- `ActionCost`: lo que cuesta una operación concreta. **Desconocido nunca es cero.**
"""

import pytest

from app.budgets.engine import BudgetStatus
from app.core.config import Environment
from app.gates.action_gate import (
    SPENDING_ACTIONS,
    ActionCost,
    BudgetSignal,
    CostKind,
    GateInput,
    GateOutcome,
    HumanApproval,
    SideEffectAction,
    evaluate_action,
)
from app.permissions.policies import PermissionResult

COLLECT = SideEffectAction.COLLECT_PAYMENT
REFUND = SideEffectAction.REFUND
SHIP = SideEffectAction.SHIP_ORDER
PURCHASE = SideEffectAction.PURCHASE_SUPPLIER

AVAILABLE = BudgetSignal(approved=True, status=BudgetStatus.AVAILABLE)
EXHAUSTED = BudgetSignal(approved=False, status=BudgetStatus.EXHAUSTED, reason="the budget does not cover this")
UNKNOWN_COST = BudgetSignal(approved=False, status=BudgetStatus.UNKNOWN_COST, reason="the cost is unknown")


def gate(**overrides) -> GateInput:
    base = {
        "action": SHIP,
        "legal_recommendation": "GO",
        "economics_recommendation": "GO",
        "kill_switch_enabled": True,
        "budget": BudgetSignal(approved=True, status=BudgetStatus.NOT_APPLICABLE),
        "human_approval": HumanApproval.NONE,
        "permission": None,
        "environment": Environment.DEVELOPMENT,
    }
    base.update(overrides)
    return GateInput(**base)


# --- El coste de una operación --------------------------------------------------------


def test_a_cost_kind_carries_exactly_what_it_means():
    assert ActionCost.zero("simulated").as_amount() == 0.0
    assert ActionCost.known(12.5).as_amount() == 12.5
    assert ActionCost.unknown().as_amount() is None, "an unknown cost is not zero"


def test_a_known_cost_must_be_positive_and_a_zero_must_be_declared_as_zero():
    with pytest.raises(ValueError):
        ActionCost.known(0.0)
    with pytest.raises(ValueError):
        ActionCost.known(-1.0)
    with pytest.raises(ValueError):
        ActionCost(kind=CostKind.UNKNOWN, amount=3.0)


@pytest.mark.parametrize(
    "cost, spends",
    [
        (ActionCost.zero("simulated"), False),
        (ActionCost.known(5.0), True),
        (ActionCost.unknown(), True),
    ],
)
def test_only_a_known_positive_or_unknown_cost_makes_an_operation_spend(cost, spends):
    assert cost.spends is spends
    assert gate(action=SHIP, cost=cost).is_spending is spends


def test_a_shipment_with_a_declared_zero_cost_does_not_ask_the_budget():
    decision = evaluate_action(gate(action=SHIP, cost=ActionCost.zero("simulated")))

    assert decision.outcome is GateOutcome.ALLOW


def test_a_shipment_with_a_known_cost_that_the_budget_cannot_cover_is_denied():
    decision = evaluate_action(gate(action=SHIP, cost=ActionCost.known(40.0), budget=EXHAUSTED))

    assert decision.outcome is GateOutcome.DENY
    assert any("does not cover" in reason for reason in decision.reasons)


def test_a_shipment_with_an_unknown_cost_is_denied_not_treated_as_free():
    decision = evaluate_action(gate(action=SHIP, cost=ActionCost.unknown(), budget=UNKNOWN_COST))

    assert decision.outcome is GateOutcome.DENY
    assert any("unknown" in reason for reason in decision.reasons)


def test_an_economics_no_go_vetoes_a_shipment_only_when_the_shipment_costs_money():
    free = evaluate_action(gate(action=SHIP, cost=ActionCost.zero("simulated"), economics_recommendation="NO_GO"))
    paid = evaluate_action(
        gate(action=SHIP, cost=ActionCost.known(9.0), budget=AVAILABLE, economics_recommendation="NO_GO")
    )

    assert free.outcome is GateOutcome.REQUIRE_APPROVAL, "it does not spend, so it is a doubt, not a veto"
    assert paid.outcome is GateOutcome.DENY


def test_spending_in_an_enforcing_environment_is_never_automatic_also_for_a_costed_operation():
    decision = evaluate_action(
        gate(action=SHIP, cost=ActionCost.known(9.0), budget=AVAILABLE, environment=Environment.PRODUCTION)
    )

    assert decision.outcome is GateOutcome.REQUIRE_APPROVAL


# --- Devolver dinero cobrado ---------------------------------------------------------------


def test_a_refund_is_not_budget_spend():
    assert REFUND not in SPENDING_ACTIONS
    assert gate(action=REFUND).is_spending is False


def test_a_legal_or_economic_no_go_of_the_product_cannot_veto_a_refund():
    decision = evaluate_action(gate(action=REFUND, legal_recommendation="NO_GO", economics_recommendation="NO_GO"))

    assert decision.outcome is GateOutcome.ALLOW, "returning a customer's money is an obligation, not a commercial call"


def test_a_review_of_the_product_does_not_ask_for_approval_to_refund():
    decision = evaluate_action(gate(action=REFUND, legal_recommendation="REVIEW", economics_recommendation="REVIEW"))

    assert decision.outcome is GateOutcome.ALLOW


def test_the_kill_switch_still_stops_a_refund():
    decision = evaluate_action(gate(action=REFUND, kill_switch_enabled=False))

    assert decision.outcome is GateOutcome.DENY
    assert any("kill switch" in reason for reason in decision.reasons)


def test_an_unresolved_outcome_still_stops_a_refund():
    decision = evaluate_action(gate(action=REFUND, unresolved_outcome=True))

    assert decision.outcome is GateOutcome.DENY
    assert any("unknown outcome" in reason for reason in decision.reasons)


def test_a_denied_permission_still_stops_a_refund():
    decision = evaluate_action(gate(action=REFUND, permission=PermissionResult.DENIED))

    assert decision.outcome is GateOutcome.DENY


def test_a_refund_never_asks_the_operating_budget_even_in_production():
    decision = evaluate_action(
        gate(action=REFUND, environment=Environment.PRODUCTION, budget=EXHAUSTED, permission=PermissionResult.ALLOWED)
    )

    assert decision.outcome is GateOutcome.ALLOW, "an exhausted advertising budget cannot block an owed refund"


# --- Abrir un cobro ----------------------------------------------------------------------------


def test_collecting_a_payment_does_not_spend():
    assert COLLECT not in SPENDING_ACTIONS
    assert gate(action=COLLECT).is_spending is False


def test_a_legal_no_go_denies_opening_a_charge_for_the_product():
    decision = evaluate_action(gate(action=COLLECT, legal_recommendation="NO_GO"))

    assert decision.outcome is GateOutcome.DENY
    assert any("legal" in reason for reason in decision.reasons)


def test_the_economics_of_the_product_is_not_re_judged_when_collecting_an_order_already_placed():
    decision = evaluate_action(gate(action=COLLECT, economics_recommendation="NO_GO"))

    assert decision.outcome is GateOutcome.ALLOW


def test_the_kill_switch_and_an_unresolved_outcome_stop_a_collection():
    assert evaluate_action(gate(action=COLLECT, kill_switch_enabled=False)).outcome is GateOutcome.DENY
    assert evaluate_action(gate(action=COLLECT, unresolved_outcome=True)).outcome is GateOutcome.DENY


def test_collecting_in_production_is_not_blocked_by_the_spending_rule():
    decision = evaluate_action(gate(action=COLLECT, environment=Environment.PRODUCTION))

    assert decision.outcome is GateOutcome.ALLOW


# --- Lo de siempre no cambia ----------------------------------------------------------------------


@pytest.mark.parametrize("action", sorted(SPENDING_ACTIONS))
def test_a_purchase_or_an_ad_spend_keeps_the_same_rules_by_action_type(action):
    assert evaluate_action(gate(action=action, budget=EXHAUSTED)).outcome is GateOutcome.DENY
    assert evaluate_action(gate(action=action, budget=AVAILABLE)).outcome is GateOutcome.ALLOW
    assert evaluate_action(gate(action=action, budget=AVAILABLE, legal_recommendation="NO_GO")).outcome is (
        GateOutcome.DENY
    )


def test_a_purchase_with_an_unknown_cost_is_denied_by_the_budget_signal():
    decision = evaluate_action(gate(action=PURCHASE, cost=ActionCost.unknown(), budget=UNKNOWN_COST))

    assert decision.outcome is GateOutcome.DENY
