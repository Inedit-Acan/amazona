"""El pipeline con el ciclo de vida de las acciones externas (hardening pre-M44, ADR 0024).

El paso de marketing es el único que gasta. Aquí se le pone un proveedor falso y se comprueba lo que el pipeline
hace con cada resultado: el efecto sale una sola vez por operación; un resultado desconocido bloquea la ejecución sin
liberar el presupuesto, ni reintentar a ciegas, ni gastar intentos del trabajo; y una persona puede cerrarlo y
reanudar sin que nada se repita.
"""

import pytest
from action_test_support import FakeProviderAdapter
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.actions.contract import ActionStatus
from app.actions.service import ExternalActionService
from app.budgets.service import BudgetLedgerService
from app.core.errors import PipelineOutcomeUnknownError
from app.db.base import Base
from app.db.models.budget import BudgetAllocation, FinancialEvent
from app.db.models.external_action import ExternalAction
from app.db.models.job import Job
from app.db.models.pipeline_run import PipelineRun
from app.db.models.pipeline_step import PipelineStep
from app.gates.action_gate import SideEffectAction
from app.jobs.schemas import JobStatus
from app.jobs.worker import Worker
from app.pipeline.kill_switch import PipelineKillSwitchService
from app.pipeline.schemas import PipelineRunStatus, PipelineStepStatus
from app.pipeline.service import PipelineOrchestrator, PipelineRequest

OWNER = "owner@amazona.local"
ADS = SideEffectAction.ACTIVATE_ADS.value


@pytest.fixture()
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    BudgetLedgerService(session).authorise_budget(hard_limit=100_000.0, actor=OWNER)
    session.commit()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def provider(monkeypatch, *behaviors: str) -> FakeProviderAdapter:
    fake = FakeProviderAdapter(behaviors=list(behaviors), only_operation=ADS)
    monkeypatch.setattr("app.pipeline.service.SimulatedAdapter", lambda: fake)
    return fake


def drain(db: Session, rounds: int = 12) -> None:
    worker = Worker(name="test-worker")
    for _ in range(rounds):
        if worker.run_once(db) is None:
            break


def start(db: Session, amount: float = 60_000.0) -> PipelineRun:
    request = PipelineRequest(
        category="home", sale_price=50.0, destination_region="mexico", market="us", daily_budget=amount
    )
    return PipelineOrchestrator(db).enqueue_run(request)


def marketing(db: Session, run: PipelineRun) -> PipelineStep:
    db.expire_all()
    return db.query(PipelineStep).filter_by(pipeline_run_id=run.id, name="marketing").one()


def actions(db: Session) -> list[ExternalAction]:
    db.expire_all()
    return db.query(ExternalAction).filter_by(operation=ADS).order_by(ExternalAction.sequence).all()


def ledger(db: Session) -> tuple[float, float]:
    db.expire_all()
    row = db.query(BudgetAllocation).one()
    return float(row.reserved), float(row.committed)


def resume(db: Session, run: PipelineRun) -> None:
    PipelineOrchestrator(db).resume_run(db.get(PipelineRun, run.id), actor=OWNER)
    drain(db)


# --- El camino feliz ----------------------------------------------------------------


def test_a_step_with_an_effect_leaves_one_closed_operation_and_a_committed_reservation(db: Session, monkeypatch):
    fake = provider(monkeypatch)
    run = start(db)

    drain(db)

    assert marketing(db, run).status == PipelineStepStatus.COMPLETED
    [action] = actions(db)
    assert action.status == ActionStatus.SUCCEEDED.value
    assert action.applied_at is not None
    assert fake.effects_of(ADS) == 1
    assert ledger(db) == (0.0, 60_000.0)


# --- Un resultado desconocido -------------------------------------------------------


def test_a_lost_response_blocks_the_run_and_the_job_keeps_the_money_reserved(db: Session, monkeypatch):
    fake = provider(monkeypatch, "timeout_after")
    run = start(db)

    drain(db)

    db.refresh(run)
    assert run.status == PipelineRunStatus.BLOCKED
    assert marketing(db, run).status == PipelineStepStatus.FAILED
    assert "UNKNOWN_OUTCOME" in marketing(db, run).error
    job = db.get(Job, run.job_id)
    assert job.status == JobStatus.BLOCKED
    assert job.attempt == 1  # no se reintentó: esperar no lo arregla
    assert actions(db)[0].status == ActionStatus.UNKNOWN_OUTCOME.value
    assert fake.effects_of(ADS) == 1
    assert ledger(db) == (60_000.0, 0.0)  # ni liberado ni gastado


def test_resuming_an_unknown_outcome_does_not_call_the_provider_again(db: Session, monkeypatch):
    fake = provider(monkeypatch, "timeout_after")
    run = start(db)
    drain(db)

    resume(db, run)  # alguien reanuda sin haber resuelto nada

    assert marketing(db, run).status == PipelineStepStatus.DENIED
    assert "unknown outcome" in marketing(db, run).error
    assert len(fake.requests) == 1 + 2  # las de ecommerce y marketplace, y una sola para marketing
    assert fake.effects_of(ADS) == 1
    assert ledger(db) == (60_000.0, 0.0)


def test_confirming_the_effect_by_hand_lets_the_run_continue_without_repeating_it(db: Session, monkeypatch):
    fake = provider(monkeypatch, "timeout_after")
    run = start(db)
    drain(db)
    [action] = actions(db)

    PipelineOrchestrator(db).resolve_unknown_outcome(
        action.id, succeeded=True, actor=OWNER, reason="the campaign is live in the ads console"
    )
    assert ledger(db) == (0.0, 60_000.0)
    resume(db, run)

    assert marketing(db, run).status == PipelineStepStatus.COMPLETED
    [action] = actions(db)
    assert action.status == ActionStatus.SUCCEEDED.value
    assert action.applied_at is not None
    assert fake.effects_of(ADS) == 1  # no hubo una segunda campaña
    assert ledger(db) == (0.0, 60_000.0)  # y se gastó una sola vez
    assert db.query(FinancialEvent).filter_by(type="COMMIT").count() == 1


def test_denying_the_effect_by_hand_frees_the_money_and_opens_a_new_operation(db: Session, monkeypatch):
    fake = provider(monkeypatch, "timeout_before")
    run = start(db)
    drain(db)
    [first] = actions(db)

    PipelineOrchestrator(db).resolve_unknown_outcome(
        first.id, succeeded=False, actor=OWNER, reason="no campaign exists for this key"
    )
    assert ledger(db) == (0.0, 0.0)
    resume(db, run)

    first_key = first.idempotency_key
    first, second = actions(db)
    assert second.sequence == 2
    assert second.idempotency_key != first_key  # una operación nueva, no un reintento
    assert second.status == ActionStatus.SUCCEEDED.value
    assert marketing(db, run).status == PipelineStepStatus.COMPLETED
    assert ledger(db) == (0.0, 60_000.0)
    assert fake.effects_of(ADS) == 1  # la primera no ejecutó (timeout_before); la segunda, sí


# --- El efecto ocurrió pero no quedó registrado --------------------------------------


def test_an_effect_that_happened_but_was_not_recorded_is_not_repeated_by_the_retry(db: Session, monkeypatch):
    fake = provider(monkeypatch)
    run = start(db)
    original = PipelineOrchestrator._step_marketing
    calls = {"n": 0}

    def fails_once(self, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("the local write failed after the provider answered")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(PipelineOrchestrator, "_step_marketing", fails_once)
    drain(db)

    db.refresh(run)
    assert marketing(db, run).status == PipelineStepStatus.FAILED
    [action] = actions(db)
    assert action.status == ActionStatus.SUCCEEDED.value
    assert action.applied_at is None  # ocurrió fuera, falta registrarlo aquí
    assert fake.effects_of(ADS) == 1

    resume(db, run)

    assert marketing(db, run).status == PipelineStepStatus.COMPLETED
    assert fake.effects_of(ADS) == 1  # el reintento solo registra: no vuelve a llamar
    assert len([r for r in fake.requests if r.operation == ADS]) == 1
    assert actions(db)[0].applied_at is not None
    assert ledger(db) == (0.0, 60_000.0)
    assert db.query(FinancialEvent).filter_by(type="RESERVE").count() == 1


# --- Un rechazo confirmado ----------------------------------------------------------


def test_a_confirmed_rejection_releases_the_money_and_a_retry_is_a_new_operation(db: Session, monkeypatch):
    fake = provider(monkeypatch, "reject")
    run = start(db)

    drain(db)
    assert ledger(db) == (0.0, 0.0)
    assert marketing(db, run).status == PipelineStepStatus.FAILED
    resume(db, run)

    first, second = actions(db)
    assert (first.status, second.status) == (ActionStatus.FAILED_CONFIRMED.value, ActionStatus.SUCCEEDED.value)
    assert first.idempotency_key != second.idempotency_key
    assert fake.effects_of(ADS) == 1
    assert ledger(db) == (0.0, 60_000.0)


# --- El kill switch justo antes del efecto -------------------------------------------


def test_the_kill_switch_turned_off_right_before_the_call_sends_nothing(db: Session, monkeypatch):
    fake = provider(monkeypatch)
    real_begin = ExternalActionService.begin_call

    def switch_off_then_begin(self, action):
        if action.operation == ADS and action.provider == fake.name:
            PipelineKillSwitchService(self._db).disable(reason="drill", actor=OWNER, correlation_id="c")
        return real_begin(self, action)

    monkeypatch.setattr(ExternalActionService, "begin_call", switch_off_then_begin)
    run = start(db)

    drain(db)

    db.refresh(run)
    assert run.status == PipelineRunStatus.BLOCKED
    assert fake.effects_of(ADS) == 0
    assert actions(db)[0].status == ActionStatus.PENDING.value
    assert ledger(db) == (60_000.0, 0.0)  # reservado, listo para reanudar o para que lo libere el barrido


def test_the_orchestrator_raises_the_outcome_unknown_error_for_the_worker(db: Session, monkeypatch):
    provider(monkeypatch, "timeout_after")
    run = start(db)
    orchestrator = PipelineOrchestrator(db)

    with pytest.raises(PipelineOutcomeUnknownError):
        orchestrator.execute_run(run.id)

    db.refresh(run)
    assert run.status == PipelineRunStatus.BLOCKED
    assert run.failed_step == "marketing"
