"""El gate con entradas reales, por operación (Milestone 44, ADR 0028 §7).

La regla pura está en `tests/unit/test_action_gate_operations.py`. Aquí, que el servicio le da el coste de la
operación, el permiso que corresponde a cada acción y el presupuesto de verdad.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Environment, Settings
from app.db.base import Base
from app.db.models.budget import Budget, BudgetAllocation
from app.gates.action_gate import ActionCost, GateOutcome, SideEffectAction
from app.gates.service import ACTION_PERMISSION, ActionGateService
from app.integrations.ports import ProviderKind
from app.permissions.policies import ActionType, PermissionResult


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def real_deployment(db: Session) -> ActionGateService:
    """Un despliegue que no es una simulación: hay un proveedor que no es `MOCK`."""
    return ActionGateService(db, settings=Settings(environment=Environment.DEVELOPMENT, ads_provider=ProviderKind.REAL))


def simulated_deployment(db: Session) -> ActionGateService:
    return ActionGateService(db, settings=Settings(environment=Environment.DEVELOPMENT))


def budget(db: Session, *, hard_limit: float, reserved: float = 0.0) -> None:
    row = Budget(name="orchestrator-default", hard_limit=hard_limit, soft_limit=None)
    db.add(row)
    db.flush()
    db.add(BudgetAllocation(budget_id=row.id, reserved=reserved, committed=0.0, spent=0.0))
    db.commit()


def test_each_action_consults_its_own_permission_and_the_rest_keep_asking_for_external_spend():
    assert ACTION_PERMISSION[SideEffectAction.COLLECT_PAYMENT] is ActionType.PAYMENT_COLLECT
    assert ACTION_PERMISSION[SideEffectAction.REFUND] is ActionType.MONEY_REFUND
    for action in SideEffectAction:
        if action not in ACTION_PERMISSION:
            assert action not in (SideEffectAction.COLLECT_PAYMENT, SideEffectAction.REFUND)


def test_a_collection_by_an_identified_role_is_not_held_for_the_approval_that_spending_needs(db_session: Session):
    decision = real_deployment(db_session).evaluate(SideEffectAction.COLLECT_PAYMENT, actor_role="OPERATOR")

    assert decision.outcome is GateOutcome.ALLOW, "opening a charge is not external spend"


def test_a_shipment_by_an_identified_role_still_asks_for_approval_like_any_external_spend(db_session: Session):
    decision = real_deployment(db_session).evaluate(
        SideEffectAction.SHIP_ORDER, actor_role="OPERATOR", cost=ActionCost.zero("declared")
    )

    assert decision.outcome is GateOutcome.REQUIRE_APPROVAL


def test_without_an_identity_outside_a_simulation_a_collection_and_a_refund_are_denied(db_session: Session):
    gate = real_deployment(db_session)

    for action in (SideEffectAction.COLLECT_PAYMENT, SideEffectAction.REFUND):
        decision = gate.evaluate(action, actor_role=None)
        assert decision.outcome is GateOutcome.DENY, f"the absence of identity is not a permission ({action})"


def test_without_an_identity_in_a_simulation_there_is_nothing_to_consult(db_session: Session):
    gate = simulated_deployment(db_session)

    assert gate.evaluate(SideEffectAction.COLLECT_PAYMENT, actor_role=None).outcome is GateOutcome.ALLOW
    assert gate.evaluate(SideEffectAction.REFUND, actor_role=None).outcome is GateOutcome.ALLOW


def test_a_refund_is_not_held_back_by_an_exhausted_operating_budget(db_session: Session):
    budget(db_session, hard_limit=100.0, reserved=100.0)

    decision = real_deployment(db_session).evaluate(SideEffectAction.REFUND, amount=30.0, actor_role="OWNER")

    assert decision.outcome is GateOutcome.ALLOW, "the advertising budget cannot block an owed refund"


def test_a_refund_is_not_vetoed_by_the_legal_or_economic_state_of_the_product(db_session: Session):
    decision = real_deployment(db_session).evaluate(
        SideEffectAction.REFUND,
        actor_role="OWNER",
        legal_recommendation="NO_GO",
        economics_recommendation="NO_GO",
    )

    assert decision.outcome is GateOutcome.ALLOW


def test_a_refund_still_stops_with_the_kill_switch_or_an_unresolved_outcome(db_session: Session):
    gate = real_deployment(db_session)

    assert gate.evaluate(SideEffectAction.REFUND, actor_role="OWNER", unresolved_outcome=True).outcome is (
        GateOutcome.DENY
    )


def test_a_costed_shipment_goes_through_the_same_budget_discipline(db_session: Session):
    gate = real_deployment(db_session)

    without_budget = gate.evaluate(SideEffectAction.SHIP_ORDER, actor_role="OWNER", cost=ActionCost.known(12.0))
    assert without_budget.outcome is GateOutcome.DENY
    assert any("no budget has been authorised" in reason for reason in without_budget.reasons)

    budget(db_session, hard_limit=100.0)
    with_budget = gate.evaluate(SideEffectAction.SHIP_ORDER, actor_role="OWNER", cost=ActionCost.known(12.0))
    assert with_budget.outcome is GateOutcome.REQUIRE_APPROVAL, "within budget, only the approval for spending remains"
    too_much = gate.evaluate(SideEffectAction.SHIP_ORDER, actor_role="OWNER", cost=ActionCost.known(900.0))
    assert too_much.outcome is GateOutcome.DENY


def test_a_shipment_of_unknown_cost_is_denied_even_in_a_simulation(db_session: Session):
    decision = simulated_deployment(db_session).evaluate(SideEffectAction.SHIP_ORDER, cost=ActionCost.unknown())

    assert decision.outcome is GateOutcome.DENY
    assert any("unknown" in reason for reason in decision.reasons)


def test_a_declared_zero_shipment_does_not_need_a_budget(db_session: Session):
    decision = simulated_deployment(db_session).evaluate(SideEffectAction.SHIP_ORDER, cost=ActionCost.zero("simulated"))

    assert decision.outcome is GateOutcome.ALLOW


def test_a_purchase_with_an_unknown_cost_is_denied_and_with_a_known_one_is_assessed(db_session: Session):
    gate = simulated_deployment(db_session)

    assert gate.evaluate(SideEffectAction.PURCHASE_SUPPLIER, cost=ActionCost.unknown()).outcome is GateOutcome.DENY
    assert gate.evaluate(SideEffectAction.PURCHASE_SUPPLIER, cost=ActionCost.known(40.0)).outcome is GateOutcome.ALLOW


def test_the_default_policy_allows_the_two_new_permissions():
    from app.permissions.engine import PermissionEngine

    engine = PermissionEngine()
    assert engine.check(actor_role="OPERATOR", action=ActionType.PAYMENT_COLLECT) is PermissionResult.ALLOWED
    assert engine.check(actor_role="OWNER", action=ActionType.MONEY_REFUND) is PermissionResult.ALLOWED
    assert engine.check(actor_role="OPERATOR", action=ActionType.EXTERNAL_SPEND) is (
        PermissionResult.HUMAN_APPROVAL_REQUIRED
    )
