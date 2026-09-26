"""Las entradas reales del ActionGate (Milestone 33).

La regla se prueba aparte, en `tests/unit/test_action_gate.py`. Aquí se prueba
que el servicio le da lo que hay de verdad: el kill switch de la base, el
presupuesto con su matemática, el permiso del rol, el entorno configurado — y
que cada decisión deja rastro en la auditoría.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Environment, Settings
from app.db.base import Base
from app.db.models.audit import AuditLog
from app.db.models.budget import Budget, BudgetAllocation
from app.gates.action_gate import GateOutcome, HumanApproval, SideEffectAction
from app.gates.service import ActionGateService
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


def service(db: Session, environment: Environment = Environment.DEVELOPMENT) -> ActionGateService:
    return ActionGateService(db, settings=Settings(environment=environment))


def budget(db: Session, *, hard_limit: float, reserved: float = 0.0) -> None:
    row = Budget(name="orchestrator-default", hard_limit=hard_limit, soft_limit=None)
    db.add(row)
    db.flush()
    db.add(BudgetAllocation(budget_id=row.id, reserved=reserved, committed=0.0, spent=0.0))
    db.commit()


def test_without_a_budget_row_there_is_no_limit_to_oppose(db_session: Session):
    """No es lo mismo «nadie ha fijado presupuesto» que «el presupuesto está a
    cero»: inventar un límite que nadie puso sería tan malo como ignorarlo."""
    decision = service(db_session).evaluate(SideEffectAction.ACTIVATE_ADS, amount=500.0)

    assert decision.outcome is GateOutcome.ALLOW


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
    PipelineKillSwitchService(db_session).disable(
        reason="drill", actor="owner@amazona.local", correlation_id="cid-1"
    )

    decision = service(db_session).evaluate(SideEffectAction.PUBLISH_PRODUCT)

    assert decision.outcome is GateOutcome.DENY
    assert any("kill switch" in reason for reason in decision.reasons)


def test_a_viewer_cannot_authorise_external_spend(db_session: Session):
    decision = service(db_session).evaluate(SideEffectAction.ACTIVATE_ADS, actor_role="viewer", amount=10.0)

    assert decision.outcome is GateOutcome.REQUIRE_APPROVAL


def test_without_a_role_there_is_nothing_to_consult(db_session: Session):
    """Una ejecución encolada sin identidad en desarrollo no es un rol sin
    permiso: son cosas distintas y el gate no las confunde."""
    decision = service(db_session).evaluate(SideEffectAction.PUBLISH_PRODUCT, actor_role=None)

    assert decision.outcome is GateOutcome.ALLOW


def test_the_configured_environment_reaches_the_gate(db_session: Session):
    decision = service(db_session, Environment.PRODUCTION).evaluate(
        SideEffectAction.ACTIVATE_ADS, amount=10.0
    )

    assert decision.outcome is GateOutcome.REQUIRE_APPROVAL
    assert any("production" in reason for reason in decision.reasons)


def test_a_human_approval_is_carried_through(db_session: Session):
    decision = service(db_session, Environment.PRODUCTION).evaluate(
        SideEffectAction.ACTIVATE_ADS, amount=10.0, human_approval=HumanApproval.GRANTED
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
