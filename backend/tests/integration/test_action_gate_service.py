"""Las entradas reales del ActionGate (Milestone 33).

La regla se prueba aparte, en `tests/unit/test_action_gate.py`. Aquí se prueba
que el servicio le da lo que hay de verdad: el kill switch de la base, el
presupuesto con su matemática, el permiso del rol, el entorno configurado — y
que cada decisión deja rastro en la auditoría.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.budgets.engine import BudgetStatus
from app.budgets.service import BudgetLedgerService
from app.core.config import Environment, Settings
from app.db.base import Base
from app.db.models.audit import AuditLog
from app.db.models.budget import Budget, BudgetAllocation
from app.gates.action_gate import GateOutcome, HumanApproval, SideEffectAction
from app.gates.service import ActionGateService
from app.integrations.ports import ProviderKind
from app.pipeline.kill_switch import PipelineKillSwitchService


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


def service(db: Session, environment: Environment = Environment.DEVELOPMENT, **settings) -> ActionGateService:
    return ActionGateService(db, settings=Settings(environment=environment, **settings))


def budget(db: Session, *, hard_limit: float, reserved: float = 0.0) -> None:
    row = Budget(name="orchestrator-default", hard_limit=hard_limit, soft_limit=None)
    db.add(row)
    db.flush()
    db.add(BudgetAllocation(budget_id=row.id, reserved=reserved, committed=0.0, spent=0.0))
    db.commit()


# --- La ausencia de información no es un permiso (hardening pre-M44, D12) -------------


def test_without_a_budget_a_simulated_spend_passes_and_says_it_is_simulated(db_session: Session):
    """Todo el despliegue es simulado (desarrollo, todos los proveedores `MOCK`): no sale dinero
    de verdad. Pasa, pero por eso —y queda dicho—, no porque «no haya límite»."""
    assessment = BudgetLedgerService(db_session).assess(500.0, simulated=True)
    decision = service(db_session).evaluate(SideEffectAction.ACTIVATE_ADS, amount=500.0)

    assert assessment.status is BudgetStatus.SIMULATED_NO_BUDGET
    assert decision.outcome is GateOutcome.ALLOW
    assert db_session.query(Budget).count() == 0  # mirar no crea un presupuesto


def test_without_a_budget_a_real_spend_is_denied(db_session: Session):
    decision = service(db_session, ads_provider=ProviderKind.REAL).evaluate(
        SideEffectAction.ACTIVATE_ADS, amount=10.0, actor_role="owner"
    )

    assert decision.outcome is GateOutcome.DENY
    assert any("no budget has been authorised" in reason for reason in decision.reasons)


def test_without_a_budget_spending_is_denied_in_production_even_with_every_provider_mocked(db_session: Session):
    decision = service(db_session, Environment.PRODUCTION).evaluate(
        SideEffectAction.ACTIVATE_ADS, amount=10.0, actor_role="owner"
    )

    assert decision.outcome is GateOutcome.DENY
    assert any("no budget has been authorised" in reason for reason in decision.reasons)


def test_a_spend_of_unknown_cost_is_denied_even_in_simulation(db_session: Session):
    decision = service(db_session).evaluate(SideEffectAction.ACTIVATE_ADS, amount=None)

    assert decision.outcome is GateOutcome.DENY
    assert any("unknown cost is not zero" in reason for reason in decision.reasons)


def test_a_known_zero_cost_is_not_blocked_by_an_exhausted_budget(db_session: Session):
    budget(db_session, hard_limit=100.0, reserved=100.0)

    zero = service(db_session).evaluate(SideEffectAction.ACTIVATE_ADS, amount=0.0)
    paid = service(db_session).evaluate(SideEffectAction.ACTIVATE_ADS, amount=1.0)

    assert zero.outcome is GateOutcome.ALLOW
    assert paid.outcome is GateOutcome.DENY


def test_an_action_that_does_not_spend_does_not_ask_the_budget(db_session: Session):
    signal = service(db_session, Environment.PRODUCTION)._budget_signal(
        SideEffectAction.PUBLISH_PRODUCT, None, simulated=False
    )

    assert signal.approved is True
    assert signal.status is BudgetStatus.NOT_APPLICABLE


def test_the_real_budget_denies_a_spend_that_does_not_fit(db_session: Session):
    budget(db_session, hard_limit=100.0)

    decision = service(db_session).evaluate(SideEffectAction.ACTIVATE_ADS, amount=250.0)

    assert decision.outcome is GateOutcome.DENY
    assert any("exceeds hard limit" in reason for reason in decision.reasons)


def test_what_is_already_reserved_counts_against_the_next_spend(db_session: Session):
    budget(db_session, hard_limit=100.0, reserved=90.0)

    decision = service(db_session).evaluate(SideEffectAction.ACTIVATE_ADS, amount=20.0)

    assert decision.outcome is GateOutcome.DENY


def test_the_kill_switch_in_the_database_reaches_the_gate(db_session: Session):
    PipelineKillSwitchService(db_session).disable(reason="drill", actor="owner@amazona.local", correlation_id="cid-1")

    decision = service(db_session).evaluate(SideEffectAction.PUBLISH_PRODUCT)

    assert decision.outcome is GateOutcome.DENY
    assert any("kill switch" in reason for reason in decision.reasons)


def test_a_viewer_cannot_authorise_external_spend(db_session: Session):
    decision = service(db_session).evaluate(SideEffectAction.ACTIVATE_ADS, actor_role="viewer", amount=10.0)

    assert decision.outcome is GateOutcome.REQUIRE_APPROVAL


def test_without_a_role_in_a_simulation_there_is_nothing_to_consult(db_session: Session):
    """Una ejecución encolada sin identidad en una simulación no es un rol sin permiso: son cosas
    distintas y el gate no las confunde."""
    decision = service(db_session).evaluate(SideEffectAction.PUBLISH_PRODUCT, actor_role=None)

    assert decision.outcome is GateOutcome.ALLOW


def test_without_a_role_outside_a_simulation_the_permission_check_does_not_disappear(db_session: Session):
    """No saber quién pide no es un permiso: el motor de permisos ya responde DENIED a un rol
    ausente, y el gate no se lo salta cuando la acción puede ser real."""
    decision = service(db_session, marketplaces_provider=ProviderKind.REAL).evaluate(
        SideEffectAction.PUBLISH_PRODUCT, actor_role=None
    )

    assert decision.outcome is GateOutcome.DENY
    assert any("not allowed" in reason for reason in decision.reasons)


def test_the_configured_environment_reaches_the_gate(db_session: Session):
    budget(db_session, hard_limit=1000.0)

    decision = service(db_session, Environment.PRODUCTION).evaluate(
        SideEffectAction.ACTIVATE_ADS, amount=10.0, actor_role="owner"
    )

    assert decision.outcome is GateOutcome.REQUIRE_APPROVAL
    assert any("production" in reason for reason in decision.reasons)


def test_a_human_approval_is_carried_through(db_session: Session):
    budget(db_session, hard_limit=1000.0)

    decision = service(db_session, Environment.PRODUCTION).evaluate(
        SideEffectAction.ACTIVATE_ADS, amount=10.0, human_approval=HumanApproval.GRANTED, actor_role="owner"
    )

    assert decision.outcome is GateOutcome.ALLOW


@pytest.mark.parametrize(
    ("outcome_setup", "expected_action"),
    [
        ({}, "action_gate.allow"),
        ({"legal_recommendation": "NO_GO"}, "action_gate.deny"),
        ({"legal_recommendation": "REVIEW"}, "action_gate.require_approval"),
    ],
)
def test_every_decision_leaves_a_trail(db_session: Session, outcome_setup: dict, expected_action: str):
    """Un DENY sin rastro es indistinguible de un fallo. Buscar
    `action_gate.deny` en la auditoría responde qué impidió el sistema y por qué."""
    gate = service(db_session)
    decision = gate.evaluate(SideEffectAction.PUBLISH_PRODUCT, **outcome_setup)

    gate.audit(
        decision,
        action=SideEffectAction.PUBLISH_PRODUCT,
        resource="pipeline_step:cid-1:ecommerce",
        correlation_id="cid-1",
    )
    db_session.commit()

    entry = db_session.query(AuditLog).filter_by(correlation_id="cid-1").one()
    assert entry.action == expected_action
    assert entry.after["side_effect_action"] == "publish_product"
    assert entry.after["outcome"] == decision.outcome.value
    assert entry.after["reasons"] == decision.reasons
