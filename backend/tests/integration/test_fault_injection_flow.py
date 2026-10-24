"""Fault injection de ENSAYO (M51A) dentro de misiones reales: el orquestador, el reintento y la
reanudación de Commit 8 y 9.

El fallo se lanza en `AgentManager.execute`, ANTES de ejecutar al agente: el agente no corre (ni
proveedor, ni presupuesto), la
ejecución queda registrada como intento 1 FAILED y, como `InjectedFault` no se reintenta en línea,
la tarea queda FAILED con UN
solo intento (recuperable). El siguiente intento ejecuta al agente de verdad. Cualquier otro fallo
sigue la política de siempre."""

import datetime

import pytest
from mission_test_support import P1, Mission, counts
from recovery_test_support import CONTEXT, Scripted, build_manager, make_objective
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.ceo.mission import MissionState, load_mission
from app.ceo.orchestrator import CEOOrchestrator
from app.core.config import get_settings
from app.db.base import Base
from app.db.models.agent_execution_log import AgentExecutionLog
from app.db.models.audit import AuditLog
from app.db.models.project import Project
from app.fault_injection import FaultInjector, set_fault_injector
from app.tasks.recovery import TaskRecoveryService

NOW = datetime.datetime(2026, 10, 24, 12, 0, tzinfo=datetime.UTC)
FIXED_MESSAGE = "injected fault (test only)"


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime.datetime:
        return self.now


@pytest.fixture()
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def clock() -> Clock:
    return Clock()


@pytest.fixture()
def injector(monkeypatch, clock):
    """La funcionalidad ACTIVADA (como en un desarrollo con proveedores simulados) y un inyector nuevo."""
    monkeypatch.setenv("FAULT_INJECTION_ENABLED", "true")
    get_settings.cache_clear()
    fresh = set_fault_injector(FaultInjector(clock))
    yield fresh
    set_fault_injector(FaultInjector())
    get_settings.cache_clear()


def start(db: Session, injector: FaultInjector, *, arm: dict | None, script=(), max_task_retries: int = 2):
    """Crea el objetivo, arma (si se pide) y ejecuta la misión con el orquestador real y agentes guionizados."""
    product = Scripted(script)
    _, manager = build_manager({P1: product})
    objective = make_objective(db, CONTEXT)
    if arm is not None:
        injector.arm(
            objective_id=arm.get("objective_id", objective.id),
            task_name=arm.get("task_name", "product_validation"),
            attempt=arm.get("attempt", 1),
            armed_by="owner-1",
            correlation_id="armed-corr-1",
        )
    decision = CEOOrchestrator(db, agent_manager=manager, max_task_retries=max_task_retries).run_objective(objective.id)
    project = db.query(Project).filter_by(objective_id=objective.id).one()
    return Mission(db, manager, product, objective, decision, project)


def audit(db: Session, action: str) -> list[AuditLog]:
    db.expire_all()
    return db.query(AuditLog).filter_by(action=action).order_by(AuditLog.created_at, AuditLog.id).all()


# L / Q / S. coincidencia exacta: falla una vez, sin ejecutar al agente y sin reintentos en línea


def test_L_Q_S_the_armed_task_fails_once_without_running_the_agent_and_without_inline_retries(db, injector):
    mission = start(db, injector, arm={}, max_task_retries=2)  # con reintentos en línea disponibles

    task = mission.task("product_validation")
    assert mission.product.calls == 0  # el agente NO se ejecutó
    assert task.status == "FAILED"
    assert task.error == FIXED_MESSAGE
    rows = mission.executions("product_validation")
    assert [(r.attempt, r.success, r.agent_id) for r in rows] == [(1, False, P1)]  # UN intento, registrado como fallido
    assert mission.first_decision.status == "REVIEW"
    assert mission.first_decision.rationale.startswith("incomplete_mission")
    assert mission.statuses()["decision_synthesis"] == "BLOCKED"
    assert load_mission(db, mission.manager, mission.project.id).state is MissionState.RECOVERY_PENDING
    assert injector.armed() == []  # de un solo uso: ya no queda nada armado
    fired = audit(db, "fault.fired")
    assert len(fired) == 1
    assert fired[0].correlation_id == mission.first_decision.correlation_id
    assert fired[0].after["objective_id"] == mission.objective.id
    assert (fired[0].after["task"], fired[0].after["attempt"], fired[0].after["armed_by"]) == (
        "product_validation",
        1,
        "owner-1",
    )
    assert fired[0].after["armed_correlation_id"] == "armed-corr-1"
    assert {"armed_at", "fired_at"} <= set(fired[0].after)


def test_the_injected_failure_touches_nothing_outside_the_mission(db, injector):
    start(db, injector, arm={})

    now = counts(db)
    assert (now["approvals"], now["financial_events"]) == (0, 0)


# M. el siguiente intento ejecuta al agente real; el flujo completo hasta la nueva decisión


def test_M_the_retry_runs_the_real_agent_and_the_mission_can_be_resumed_to_a_new_decision(db, injector):
    mission = start(db, injector, arm={})
    v1 = mission.latest()

    task = mission.retry(after_attempt=1)

    assert mission.product.calls == 1  # ahora SÍ corre el agente de verdad
    assert task.status == "COMPLETED"
    assert [(r.attempt, r.success) for r in mission.executions("product_validation")] == [(1, False), (2, True)]
    assert task.assigned_agent_id == P1
    assert load_mission(db, mission.manager, mission.project.id).state is MissionState.READY_TO_RESUME

    v2 = mission.resume()

    assert v2.id != v1.id and v2.status != "REVIEW"
    assert set(mission.statuses().values()) == {"COMPLETED"}
    assert len(audit(db, "fault.fired")) == 1  # no se volvió a disparar


# I / J / K. lo que no es la tripleta exacta no dispara


def test_J_a_fault_armed_for_another_objective_does_not_fire(db, injector):
    mission = start(db, injector, arm={"objective_id": "another-objective"})

    assert mission.product.calls == 1
    assert set(mission.statuses().values()) == {"COMPLETED"}
    assert len(injector.armed()) == 1
    assert audit(db, "fault.fired") == []


def test_K_a_fault_armed_for_another_attempt_does_not_fire_the_first_attempt(db, injector):
    mission = start(db, injector, arm={"attempt": 2})

    assert mission.product.calls == 1
    assert set(mission.statuses().values()) == {"COMPLETED"}
    assert len(injector.armed()) == 1


def test_I_a_fault_armed_for_another_task_only_hits_that_task(db, injector):
    mission = start(db, injector, arm={"task_name": "legal_validation"})

    assert mission.product.calls == 1  # producto, intacto
    assert mission.task("legal_validation").status == "FAILED"
    assert mission.task("product_validation").status == "COMPLETED"
    assert [(r.attempt, r.success) for r in mission.executions("legal_validation")] == [(1, False)]


# retry y resume también pasan por el punto de inyección


def test_a_fault_armed_for_the_second_attempt_fires_in_the_explicit_retry_and_is_audited(db, injector):
    mission = start(db, injector, arm=None, script=[False], max_task_retries=0)  # un fallo normal en el intento 1
    injector.arm(
        objective_id=mission.objective.id,
        task_name="product_validation",
        attempt=2,
        armed_by="owner-1",
        correlation_id="c2",
    )

    TaskRecoveryService(db, mission.manager).retry(mission.task("product_validation").id, actor="ceo", after_attempt=1)
    db.commit()

    assert mission.product.calls == 1  # solo el intento 1; el 2 lo hizo fallar el inyector
    assert [(r.attempt, r.success) for r in mission.executions("product_validation")] == [(1, False), (2, False)]
    fired = audit(db, "fault.fired")
    assert len(fired) == 1 and fired[0].resource == f"task:{mission.task('product_validation').id}"
    assert fired[0].after["attempt"] == 2


def test_a_fault_armed_for_a_pending_task_fires_when_the_mission_is_resumed(db, injector):
    mission = start(db, injector, arm=None, script=[False], max_task_retries=0)
    mission.retry()
    injector.arm(
        objective_id=mission.objective.id,
        task_name="supplier_sourcing",
        attempt=1,
        armed_by="owner-1",
        correlation_id="c3",
    )

    v3 = mission.resume()

    assert mission.task("supplier_sourcing").status == "FAILED"
    assert [(r.attempt, r.success) for r in mission.executions("supplier_sourcing")] == [(1, False)]
    assert v3.status == "REVIEW" and v3.rationale.startswith("incomplete_mission")
    assert len(audit(db, "fault.fired")) == 1
    assert len(audit(db, "mission.resume_failed")) == 1


# N / O / R. reinicio y expiración


def test_N_after_a_restart_nothing_is_armed_and_the_mission_runs_normally(db, injector):
    product = Scripted([])
    _, manager = build_manager({P1: product})
    objective = make_objective(db, CONTEXT)
    injector.arm(
        objective_id=objective.id, task_name="product_validation", attempt=1, armed_by="owner-1", correlation_id="c"
    )
    set_fault_injector(FaultInjector())  # el proceso se reinició: el estado vivía en su memoria

    CEOOrchestrator(db, agent_manager=manager).run_objective(objective.id)

    assert product.calls == 1
    assert audit(db, "fault.fired") == []


def test_the_armed_state_is_never_written_to_the_database(db, injector):
    before = counts(db)
    injector.arm(
        objective_id="obj-x", task_name="product_validation", attempt=1, armed_by="owner-1", correlation_id="c"
    )
    assert counts(db) == before
    assert db.query(AuditLog).count() == 0  # el armado en sí no escribe nada: lo audita quien lo pide (la ruta)


def test_O_R_an_expired_fault_does_not_fire_and_its_expiry_is_audited_once(db, injector, clock):
    product = Scripted([])
    _, manager = build_manager({P1: product})
    objective = make_objective(db, CONTEXT)
    injector.arm(
        objective_id=objective.id,
        task_name="product_validation",
        attempt=1,
        armed_by="owner-1",
        correlation_id="armed-c",
    )
    clock.now += datetime.timedelta(minutes=31)

    CEOOrchestrator(db, agent_manager=manager).run_objective(objective.id)

    assert product.calls == 1  # el agente real corrió
    assert audit(db, "fault.fired") == []
    expired = audit(db, "fault.expired")
    assert len(expired) == 1
    assert expired[0].correlation_id == "armed-c"
    assert expired[0].after["objective_id"] == objective.id and expired[0].after["task"] == "product_validation"
    assert "expires_at" in expired[0].after
    assert injector.armed() == []
    CEOOrchestrator(db, agent_manager=manager).run_objective(make_objective(db, CONTEXT).id)
    assert len(audit(db, "fault.expired")) == 1  # no se vuelve a informar


# la funcionalidad apagada: nada actúa


def test_with_the_feature_off_an_armed_fault_never_fires(db, monkeypatch, clock):
    monkeypatch.delenv("FAULT_INJECTION_ENABLED", raising=False)
    get_settings.cache_clear()
    injector = set_fault_injector(FaultInjector(clock))
    try:
        mission = start(db, injector, arm={})
        assert mission.product.calls == 1
        assert set(mission.statuses().values()) == {"COMPLETED"}
        assert audit(db, "fault.fired") == []
    finally:
        set_fault_injector(FaultInjector())
        get_settings.cache_clear()


# T. los fallos normales siguen con la política actual


def test_T_a_normal_failure_keeps_the_current_retry_policy(db, injector):
    mission = start(db, injector, arm=None, script=[False, False, False], max_task_retries=2)

    assert mission.product.calls == 3  # tres intentos en línea, como siempre
    assert [(r.attempt, r.success) for r in mission.executions("product_validation")] == [
        (1, False),
        (2, False),
        (3, False),
    ]
    assert mission.task("product_validation").status == "FAILED"
    assert audit(db, "fault.fired") == []


def test_T_a_normal_failure_still_recovers_inline_when_a_later_attempt_succeeds(db, injector):
    mission = start(db, injector, arm=None, script=[False], max_task_retries=2)

    assert mission.product.calls == 2
    assert set(mission.statuses().values()) == {"COMPLETED"}
    assert db.query(AgentExecutionLog).filter_by(task_id=mission.task("product_validation").id).count() == 2
