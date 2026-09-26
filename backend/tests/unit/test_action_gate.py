"""El ActionGate, como tabla de casos (Milestone 33, plan maestro §7).

La función es pura, así que aquí se prueba **la regla** —qué gana a qué— sin
base de datos ni pipeline de por medio. Las seis situaciones que el plan exige
cubrir (legal NO_GO, economics NO_GO, REVIEW, presupuesto denegado, aprobación
ausente, kill switch apagado) están todas, y además lo que no se puede permitir:
que una firma humana levante un veto.
"""

import pytest

from app.core.config import Environment
from app.gates.action_gate import (
    SPENDING_ACTIONS,
    BudgetSignal,
    GateInput,
    GateOutcome,
    HumanApproval,
    SideEffectAction,
    evaluate_action,
)
from app.permissions.policies import PermissionResult

PUBLISH = SideEffectAction.PUBLISH_PRODUCT
ADS = SideEffectAction.ACTIVATE_ADS


def gate(**overrides) -> GateInput:
    """Una entrada limpia: todo en orden, en desarrollo. Cada prueba ensucia
    exactamente una cosa, que es lo que hace legible la tabla."""
    base = {
        "action": PUBLISH,
        "legal_recommendation": "GO",
        "economics_recommendation": "GO",
        "kill_switch_enabled": True,
        "budget": BudgetSignal(),
        "human_approval": HumanApproval.NONE,
        "permission": None,
        "environment": Environment.DEVELOPMENT,
    }
    base.update(overrides)
    return GateInput(**base)


# --- ALLOW -----------------------------------------------------------------


def test_everything_in_order_is_allowed():
    decision = evaluate_action(gate())

    assert decision.outcome is GateOutcome.ALLOW
    assert decision.allowed is True
    assert decision.reasons == []


def test_spending_is_allowed_in_development_when_nothing_objects():
    decision = evaluate_action(gate(action=ADS))

    assert decision.outcome is GateOutcome.ALLOW


def test_a_step_without_analysis_yet_is_not_treated_as_a_veto():
    """Ningún paso de análisis ejecutado todavía no es lo mismo que un NO_GO."""
    decision = evaluate_action(gate(legal_recommendation=None, economics_recommendation=None))

    assert decision.outcome is GateOutcome.ALLOW


# --- DENY ------------------------------------------------------------------


def test_the_kill_switch_denies_everything():
    decision = evaluate_action(gate(kill_switch_enabled=False))

    assert decision.outcome is GateOutcome.DENY
    assert any("kill switch" in reason for reason in decision.reasons)


@pytest.mark.parametrize("action", list(SideEffectAction))
def test_a_legal_no_go_denies_every_side_effect(action: SideEffectAction):
    """El ejemplo literal del plan maestro §7: legal NO_GO deniega publicar,
    anunciar y comprar. Aquí, las nueve."""
    decision = evaluate_action(gate(action=action, legal_recommendation="NO_GO"))

    assert decision.outcome is GateOutcome.DENY
    assert any("legal" in reason for reason in decision.reasons)


@pytest.mark.parametrize("action", sorted(SPENDING_ACTIONS))
def test_an_economics_no_go_denies_spending(action: SideEffectAction):
    decision = evaluate_action(gate(action=action, economics_recommendation="NO_GO"))

    assert decision.outcome is GateOutcome.DENY
    assert any("economics" in reason for reason in decision.reasons)


def test_a_budget_that_does_not_cover_it_denies_the_spend():
    decision = evaluate_action(
        gate(action=ADS, budget=BudgetSignal(approved=False, reason="amount 900 exceeds hard limit"))
    )

    assert decision.outcome is GateOutcome.DENY
    assert any("exceeds hard limit" in reason for reason in decision.reasons)


def test_a_budget_limit_does_not_block_something_that_does_not_spend():
    decision = evaluate_action(
        gate(action=PUBLISH, budget=BudgetSignal(approved=False, reason="no budget left"))
    )

    assert decision.outcome is GateOutcome.ALLOW


def test_an_actor_without_permission_is_denied():
    decision = evaluate_action(gate(permission=PermissionResult.DENIED))

    assert decision.outcome is GateOutcome.DENY
    assert any("not allowed" in reason for reason in decision.reasons)


def test_a_human_rejection_denies_it_and_does_not_ask_again():
    decision = evaluate_action(gate(human_approval=HumanApproval.REJECTED))

    assert decision.outcome is GateOutcome.DENY
    assert any("rejected" in reason for reason in decision.reasons)


def test_every_veto_that_applies_is_reported_not_just_the_first():
    """Quien lea el motivo tiene que ver todo lo que hay que arreglar, no
    descubrirlo de uno en uno."""
    decision = evaluate_action(
        gate(
            action=ADS,
            legal_recommendation="NO_GO",
            economics_recommendation="NO_GO",
            kill_switch_enabled=False,
            budget=BudgetSignal(approved=False, reason="no budget left"),
        )
    )

    assert decision.outcome is GateOutcome.DENY
    assert len(decision.reasons) == 4


# --- REQUIRE_APPROVAL ------------------------------------------------------


def test_a_legal_review_asks_for_a_human():
    decision = evaluate_action(gate(legal_recommendation="REVIEW"))

    assert decision.outcome is GateOutcome.REQUIRE_APPROVAL
    assert any("legal recommendation is REVIEW" in reason for reason in decision.reasons)


def test_an_economics_review_asks_for_a_human():
    decision = evaluate_action(gate(economics_recommendation="REVIEW"))

    assert decision.outcome is GateOutcome.REQUIRE_APPROVAL


def test_an_economics_no_go_on_something_that_does_not_spend_asks_instead_of_denying():
    """Publicar algo que las cuentas desaconsejan no gasta dinero, así que no es
    un veto — pero tampoco lo decide el sistema solo."""
    decision = evaluate_action(gate(action=PUBLISH, economics_recommendation="NO_GO"))

    assert decision.outcome is GateOutcome.REQUIRE_APPROVAL


def test_a_role_that_needs_approval_to_spend_gets_asked():
    decision = evaluate_action(gate(permission=PermissionResult.HUMAN_APPROVAL_REQUIRED))

    assert decision.outcome is GateOutcome.REQUIRE_APPROVAL


@pytest.mark.parametrize("environment", [Environment.STAGING, Environment.PRODUCTION])
def test_spending_is_never_automatic_where_systems_are_real(environment: Environment):
    """Plan maestro §33: no otorgar autonomía económica todavía."""
    decision = evaluate_action(gate(action=ADS, environment=environment))

    assert decision.outcome is GateOutcome.REQUIRE_APPROVAL
    assert any(environment.value in reason for reason in decision.reasons)


@pytest.mark.parametrize("environment", [Environment.STAGING, Environment.PRODUCTION])
def test_publishing_without_spending_is_not_held_back_by_the_environment_alone(
    environment: Environment,
):
    decision = evaluate_action(gate(action=PUBLISH, environment=environment))

    assert decision.outcome is GateOutcome.ALLOW


# --- La autorización humana y sus límites ----------------------------------


def test_an_approval_lets_a_doubt_through():
    decision = evaluate_action(gate(legal_recommendation="REVIEW", human_approval=HumanApproval.GRANTED))

    assert decision.outcome is GateOutcome.ALLOW
    assert decision.reasons == ["a human authorized this action"]


def test_an_approval_lets_spending_through_in_production():
    decision = evaluate_action(
        gate(action=ADS, environment=Environment.PRODUCTION, human_approval=HumanApproval.GRANTED)
    )

    assert decision.outcome is GateOutcome.ALLOW


@pytest.mark.parametrize(
    "veto",
    [
        {"kill_switch_enabled": False},
        {"legal_recommendation": "NO_GO"},
        {"permission": PermissionResult.DENIED},
        {"action": ADS, "budget": BudgetSignal(approved=False, reason="no budget left")},
        {"action": ADS, "economics_recommendation": "NO_GO"},
    ],
)
def test_no_signature_can_lift_a_veto(veto: dict):
    """Lo más importante de todo el módulo: una aprobación humana levanta dudas,
    nunca vetos. Si alguien necesita saltarse un veto, que cambie el veto."""
    decision = evaluate_action(gate(human_approval=HumanApproval.GRANTED, **veto))

    assert decision.outcome is GateOutcome.DENY


# --- El catálogo -----------------------------------------------------------


def test_the_catalogue_is_the_nine_actions_of_the_plan():
    assert {action.value for action in SideEffectAction} == {
        "publish_product",
        "activate_ads",
        "spend_money",
        "purchase_supplier",
        "make_payment",
        "ship_order",
        "refund",
        "change_price",
        "send_contract_communication",
    }


def test_only_the_actions_that_move_money_count_as_spending():
    assert SPENDING_ACTIONS == {
        SideEffectAction.ACTIVATE_ADS,
        SideEffectAction.SPEND_MONEY,
        SideEffectAction.PURCHASE_SUPPLIER,
        SideEffectAction.MAKE_PAYMENT,
        SideEffectAction.REFUND,
    }
