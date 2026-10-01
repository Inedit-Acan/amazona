"""La clave hacia el proveedor, dentro del pipeline (hardening pre-M44, ADR 0024).

Una clave estable es la que no cambia cuando el intento cambia: sobrevive a un reintento, a un reinicio y a una
reanudación de **la misma** operación, y es otra para una operación nueva, otro paso y otra ejecución. Y un proveedor
que no la respeta (`supports_idempotency = False`) nunca recibe un reintento ciego: su resultado desconocido espera a
una consulta o a una persona.
"""

import pytest
from action_test_support import FakeLookupProviderAdapter, FakeProviderAdapter
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.actions.contract import ActionStatus
from app.actions.service import ExternalActionService
from app.budgets.service import BudgetLedgerService
from app.core.errors import PipelineOutcomeUnknownError
from app.db.base import Base
from app.db.models.budget import BudgetAllocation
from app.db.models.external_action import ExternalAction
from app.db.models.job import Job
from app.db.models.pipeline_run import PipelineRun
from app.gates.action_gate import SideEffectAction
from app.jobs.worker import Worker
from app.pipeline.schemas import PipelineRunStatus
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


def request(amount: float = 60_000.0) -> PipelineRequest:
    return PipelineRequest(
        category="home", sale_price=50.0, destination_region="mexico", market="us", daily_budget=amount
    )


def drain(db: Session, rounds: int = 12) -> None:
    worker = Worker(name="test-worker")
    for _ in range(rounds):
        if worker.run_once(db) is None:
            break


def use_provider(monkeypatch, *behaviors: str, **kwargs) -> FakeProviderAdapter:
    fake = FakeProviderAdapter(behaviors=list(behaviors), only_operation=ADS, **kwargs)
    monkeypatch.setattr("app.pipeline.service.SimulatedAdapter", lambda: fake)
    return fake


def ads_actions(db: Session) -> list[ExternalAction]:
    db.expire_all()
    return (
        db.query(ExternalAction)
        .filter_by(operation=ADS)
        .order_by(ExternalAction.created_at, ExternalAction.sequence)
        .all()
    )


def ledger(db: Session) -> tuple[float, float]:
    db.expire_all()
    row = db.query(BudgetAllocation).one()
    return float(row.reserved), float(row.committed)


def resume(db: Session, run: PipelineRun) -> None:
    PipelineOrchestrator(db).resume_run(db.get(PipelineRun, run.id), actor=OWNER)
    drain(db)


def expire_lease(db: Session, run: PipelineRun) -> None:
    import datetime

    job = db.get(Job, run.job_id)
    job.lease_expires_at = datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=1)
    db.commit()


# --- La clave es estable ---------------------------------------------------------------


def test_a_retry_after_a_crash_before_the_call_sends_the_same_key_the_first_attempt_would_have(db, monkeypatch):
    fake = use_provider(monkeypatch)
    run = PipelineOrchestrator(db).enqueue_run(request())
    real_begin = ExternalActionService.begin_call

    def dies_before_the_ads_call(self, action):
        if action.operation == ADS:
            raise KeyboardInterrupt("the process died before the request left")
        return real_begin(self, action)

    monkeypatch.setattr(ExternalActionService, "begin_call", dies_before_the_ads_call)
    with pytest.raises(KeyboardInterrupt):
        Worker(name="worker-1").run_once(db)
    db.rollback()
    [first] = ads_actions(db)
    key_before_the_crash = first.idempotency_key
    assert fake.effects_of(ADS) == 0

    expire_lease(db, run)
    monkeypatch.setattr(ExternalActionService, "begin_call", real_begin)
    drain(db)

    [only] = ads_actions(db)
    assert only.id == first.id
    assert only.idempotency_key == key_before_the_crash
    sent = [r.idempotency_key for r in fake.requests if r.operation == ADS]
    assert sent == [key_before_the_crash]


def test_a_new_session_after_a_restart_finds_the_same_operation_and_the_same_key(db, monkeypatch):
    use_provider(monkeypatch, "timeout_after")
    run = PipelineOrchestrator(db).enqueue_run(request())
    drain(db)
    [before] = ads_actions(db)
    key, action_id, correlation_id = before.idempotency_key, before.id, run.correlation_id
    db.close()  # el proceso termina; la base es lo único que sobrevive

    with Session(db.get_bind()) as reborn:
        service = ExternalActionService(reborn)
        again = service.open(
            reference=before.reference,
            adapter=FakeProviderAdapter(),
            operation=ADS,
            amount=60_000.0,
            payload={"market": "us", "platform": "meta", "daily_budget": 60_000.0},
            correlation_id=correlation_id,
        )

        assert (again.id, again.idempotency_key) == (action_id, key)


def test_every_step_and_every_run_has_its_own_key(db, monkeypatch):
    fake = use_provider(monkeypatch)
    first = PipelineOrchestrator(db).enqueue_run(request(1_000.0))
    second = PipelineOrchestrator(db).enqueue_run(request(1_000.0))
    drain(db)

    db.expire_all()
    actions = db.query(ExternalAction).all()
    keys = [a.idempotency_key for a in actions]

    assert len(actions) == 6  # ecommerce, marketplace y marketing, de cada ejecución
    assert len(set(keys)) == 6
    assert {first.correlation_id, second.correlation_id} == {a.reference.split(":")[1] for a in actions}
    assert fake.effect_count == 6


def test_a_new_operation_after_a_confirmed_failure_has_a_new_key(db, monkeypatch):
    fake = use_provider(monkeypatch, "reject")
    run = PipelineOrchestrator(db).enqueue_run(request())
    drain(db)

    resume(db, run)

    first, second = ads_actions(db)
    assert first.status == ActionStatus.FAILED_CONFIRMED.value
    assert second.idempotency_key != first.idempotency_key
    assert [r.idempotency_key for r in fake.requests if r.operation == ADS] == [
        first.idempotency_key,
        second.idempotency_key,
    ]


# --- Reconciliar con la misma clave ----------------------------------------------------


def test_an_idempotent_provider_is_reconciled_by_the_same_key_and_the_run_continues(db, monkeypatch):
    fake = use_provider(monkeypatch, "timeout_after")
    run = PipelineOrchestrator(db).enqueue_run(request())
    drain(db)
    [action] = ads_actions(db)
    assert action.status == ActionStatus.UNKNOWN_OUTCOME.value

    status = ExternalActionService(db).reconcile(action, fake, {"market": "us"})
    resume(db, run)

    assert status is ActionStatus.SUCCEEDED
    assert {r.idempotency_key for r in fake.requests if r.operation == ADS} == {action.idempotency_key}
    assert fake.effects_of(ADS) == 1  # la misma clave, el mismo efecto
    db.refresh(run)
    assert run.status == PipelineRunStatus.COMPLETED
    assert ledger(db) == (0.0, 60_000.0)


def test_a_provider_that_can_be_asked_says_a_timeout_before_execution_never_happened(db, monkeypatch):
    fake = FakeLookupProviderAdapter(behaviors=["timeout_before"], only_operation=ADS)
    monkeypatch.setattr("app.pipeline.service.SimulatedAdapter", lambda: fake)
    run = PipelineOrchestrator(db).enqueue_run(request())
    drain(db)
    [first] = ads_actions(db)

    status = ExternalActionService(db).reconcile(first, fake, {"market": "us"})
    assert status is ActionStatus.FAILED_CONFIRMED
    assert ledger(db) == (0.0, 0.0)
    resume(db, run)

    first, second = ads_actions(db)
    assert second.status == ActionStatus.SUCCEEDED.value
    assert second.idempotency_key != first.idempotency_key
    assert fake.effects_of(ADS) == 1
    assert ledger(db) == (0.0, 60_000.0)


# --- Un proveedor sin idempotencia -------------------------------------------------------


def test_a_provider_without_idempotency_gets_no_key_and_is_never_replayed(db):
    fake = FakeProviderAdapter(supports_idempotency=False, behaviors=["timeout_after"], only_operation=ADS)
    orchestrator = PipelineOrchestrator(db, action_adapters={"marketing": fake})
    run = orchestrator.enqueue_run(request())

    with pytest.raises(PipelineOutcomeUnknownError):
        orchestrator.execute_run(run.id)
    [action] = ads_actions(db)
    assert action.provider_idempotent is False
    assert [r.idempotency_key for r in fake.requests if r.operation == ADS] == [None]  # no se manda lo que no respeta

    assert ExternalActionService(db).reconcile(action, fake, {"market": "us"}) is ActionStatus.UNKNOWN_OUTCOME
    resume(db, run)  # alguien reanuda sin resolver: el worker usa el adaptador por defecto, pero ni siquiera llega

    assert [r for r in fake.requests if r.operation == ADS] == [fake.requests[-1]]
    assert len([r for r in fake.requests if r.operation == ADS]) == 1  # ni una petición más
    assert fake.effects_of(ADS) == 1
    assert ledger(db) == (60_000.0, 0.0)  # sigue reservado: hace falta una persona


def test_a_person_confirming_the_effect_of_a_provider_without_idempotency_lets_the_run_finish(db):
    fake = FakeProviderAdapter(supports_idempotency=False, behaviors=["timeout_after"], only_operation=ADS)
    orchestrator = PipelineOrchestrator(db, action_adapters={"marketing": fake})
    run = orchestrator.enqueue_run(request())
    with pytest.raises(PipelineOutcomeUnknownError):
        orchestrator.execute_run(run.id)
    [action] = ads_actions(db)

    orchestrator.resolve_unknown_outcome(action.id, succeeded=True, actor=OWNER, reason="campaign seen in the console")
    orchestrator.resume_run(db.get(PipelineRun, run.id), actor=OWNER)
    orchestrator.execute_run(run.id)  # el mismo adaptador: cambiar de proveedor entre intentos cambia la huella

    db.refresh(run)
    assert run.status == PipelineRunStatus.COMPLETED
    assert fake.effects_of(ADS) == 1
    assert ledger(db) == (0.0, 60_000.0)
