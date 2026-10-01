"""Las veinte pruebas de caos controlado (hardening pre-M44, fase 8).

Deterministas: un proveedor falso que se comporta como se le dice y cuenta los efectos que habría tenido «en el
mundo real», PostgreSQL efímero para las carreras y **barreras explícitas** para que arranquen a la vez; ningún test
es probabilístico (si una carrera se pierde, lo que se afirma es un invariante que vale en cualquier orden).

Cada test lleva el número de su escenario:

     1 veinte solicitudes idénticas a la vez                11 el CEO y el pipeline compiten por el saldo
     2 misma clave, otro contenido                          12 el kill switch se activa entre autorizar y ejecutar
     3 el worker cae después de reservar                    13 la aprobación caduca entre la reserva y la ejecución
     4 el worker cae antes de llamar                        14 la misma petición tras reiniciar el proceso
     5 el proveedor ejecuta y da timeout                    15 un adaptador sin idempotencia
     6 el proveedor no ejecuta y da timeout                 16 coste declarado 0
     7 la respuesta llega tarde                             17 coste desconocido
     8 reintento en otro worker                             18 ausencia de presupuesto
     9 dos workers consumen la misma aprobación             19 permisos desconocidos
    10 presupuesto casi agotado y dos acciones compiten     20 recuperación de un resultado desconocido
"""

import collections
import datetime
import threading

import pytest
from action_test_support import FakeLookupProviderAdapter, FakeProviderAdapter
from chaos_test_support import (
    ADS,
    OWNER,
    SlowProvider,
    ads_actions,
    drain,
    errors,
    expire_lease,
    ledger,
    marketing_step,
    request,
    resume,
    run_together,
    scalar,
    use_provider,
)
from fastapi.testclient import TestClient
from pg_test_support import ephemeral_postgres
from pydantic import BaseModel
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.responses import Response

from app.actions.contract import ActionStatus
from app.actions.service import ExternalActionService, ExternalActionStateError
from app.auth.actor import Actor, ActorSource, RoleName
from app.budgets.service import BudgetLedgerService
from app.ceo.orchestrator import CEOOrchestrator
from app.core.config import Settings
from app.core.errors import IdempotencyInProgressError, PipelineRunStateError
from app.core.ids import new_id
from app.db.base import Base
from app.db.models.approval import Approval
from app.db.models.budget import FinancialEvent
from app.db.models.objective import Objective
from app.db.models.pipeline_review import PipelineReview
from app.db.models.pipeline_run import PipelineRun
from app.db.models.pipeline_step import PipelineStep
from app.db.models.product_analysis import ProductAnalysis
from app.db.session import get_db
from app.gates.action_gate import GateOutcome, SideEffectAction
from app.gates.service import ActionGateService
from app.idempotency.service import run_idempotent
from app.integrations.ports import ProviderKind
from app.jobs.worker import Worker
from app.main import app
from app.pipeline.kill_switch import PipelineKillSwitchService
from app.pipeline.schemas import PipelineRunStatus, PipelineStepStatus
from app.pipeline.service import PipelineOrchestrator

PUBLISH = SideEffectAction.PUBLISH_PRODUCT
CEO_CONTEXT = {
    "product_validation": {"estimated_monthly_searches": 12000, "competition_level": "low"},
    "supplier_sourcing": {"unit_cost": 5.0, "lead_time_days": 20, "supplier_verified": True},
    "finance_validation": {
        "unit_cost": 5.0,
        "sale_price": 20.0,
        "monthly_unit_sales": 300,
        "monthly_fixed_costs": 500.0,
    },
    "legal_validation": {"restricted_category": False},
    "requests_simulated_spend": True,
    "spend_action": "launch_marketing_campaign",
    "spend_amount": 60_000.0,
}
OWNER_ACTOR = Actor(subject=OWNER, role=RoleName.OWNER, source=ActorSource.DECLARED)


@pytest.fixture()
def session_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, expire_on_commit=False)
    engine.dispose()


@pytest.fixture()
def db(session_factory):
    """Una base con un presupuesto de 100 000 autorizado por el propietario."""
    with session_factory() as session:
        BudgetLedgerService(session).authorise_budget(hard_limit=100_000.0, actor=OWNER)
        yield session


@pytest.fixture()
def client(session_factory):
    def override_get_db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app, raise_server_exceptions=False)
    finally:
        app.dependency_overrides.pop(get_db, None)


def authorise(engine, hard_limit: float = 100_000.0) -> None:
    with Session(engine) as session:
        BudgetLedgerService(session).authorise_budget(hard_limit=hard_limit, actor=OWNER)


# --- 1. Veinte solicitudes idénticas a la vez ----------------------------------------------


class Out(BaseModel):
    value: int


def test_01_twenty_identical_simultaneous_requests_have_one_logical_execution():
    with ephemeral_postgres() as engine:
        effects: list[int] = []

        def job(session: Session):
            def work() -> Out:
                effects.append(1)
                threading.Event().wait(0.3)  # el trabajo dura: las demás lo ven en curso
                return Out(value=len(effects))

            return run_idempotent(
                session,
                scope="chaos.op",
                identity=OWNER_ACTOR,
                client_key="same-key",
                settings=Settings(_env_file=None),
                payload={"x": 1},
                response=Response(),
                status_code=201,
                response_model=Out,
                work=work,
            )

        results = run_together(engine, [job] * 20)

        assert len(effects) == 1
        assert sum(isinstance(r, Out) for r in results) == 1
        assert all(isinstance(r, (Out, dict, IdempotencyInProgressError)) for r in results)  # nadie recibe otra cosa


# --- 2. Misma clave, contenido distinto ---------------------------------------------------


def test_02_the_same_key_with_another_content_is_refused_and_runs_nothing(client: TestClient, session_factory):
    def analyses() -> int:
        with session_factory() as session:
            return session.query(ProductAnalysis).count()

    first = client.post("/api/research/runs", json={"category": "home"}, headers={"Idempotency-Key": "chaos-2"})
    rows = analyses()

    other = client.post("/api/research/runs", json={"category": "garden"}, headers={"Idempotency-Key": "chaos-2"})

    assert first.status_code == 201 and other.status_code == 409
    assert analyses() == rows


# --- 3. El worker cae después de reservar ------------------------------------------------


def test_03_a_worker_that_dies_after_reserving_leaves_a_reservation_the_sweep_releases(db: Session, monkeypatch):
    fake = use_provider(monkeypatch)
    PipelineOrchestrator(db).enqueue_run(request())
    real_begin = ExternalActionService.begin_call

    def dies_before_the_boundary(self, action):
        if action.operation == ADS:
            raise KeyboardInterrupt("the process died right after reserving")
        return real_begin(self, action)

    monkeypatch.setattr(ExternalActionService, "begin_call", dies_before_the_boundary)
    with pytest.raises(KeyboardInterrupt):
        Worker(name="worker-1").run_once(db)
    db.rollback()
    [action] = ads_actions(db)
    assert action.status == ActionStatus.PENDING.value  # nada salió: la frontera no se cruzó
    assert ledger(db) == (60_000.0, 0.0)

    swept = ExternalActionService(db).reconcile_interrupted(older_than=datetime.timedelta(seconds=-1))

    assert swept["released"] == [action.id]  # y solo por eso se puede liberar con seguridad
    assert ledger(db) == (0.0, 0.0)
    assert fake.effects_of(ADS) == 0


# --- 4. El worker cae antes de llamar (frontera cruzada) -----------------------------------


def test_04_a_worker_that_dies_after_the_boundary_but_before_any_effect_is_still_unknown(db: Session, monkeypatch):
    fake = use_provider(monkeypatch, "die")
    run = PipelineOrchestrator(db).enqueue_run(request())
    with pytest.raises(KeyboardInterrupt):
        Worker(name="worker-1").run_once(db)
    db.rollback()
    [action] = ads_actions(db)
    assert action.status == ActionStatus.CALLING.value  # la frontera quedó confirmada antes de salir

    swept = ExternalActionService(db).reconcile_interrupted(older_than=datetime.timedelta(seconds=-1))
    assert swept == {"released": [], "unknown": [action.id]}  # el barrido no «arregla» lo que no sabe
    expire_lease(db, run)

    drain(db)

    assert fake.effects_of(ADS) == 0  # no se ejecutó nada, y aun así no se puede saber desde fuera
    [action] = ads_actions(db)
    assert action.status == ActionStatus.UNKNOWN_OUTCOME.value
    assert marketing_step(db, run).status == PipelineStepStatus.DENIED
    assert ledger(db) == (60_000.0, 0.0)  # ni liberado ni gastado


# --- 5 y 6. El proveedor da timeout, hubiera ejecutado o no ------------------------------------


def test_05_a_provider_that_executes_and_times_out_is_unknown_and_keeps_the_money_reserved(db: Session, monkeypatch):
    fake = use_provider(monkeypatch, "timeout_after")
    run = PipelineOrchestrator(db).enqueue_run(request())

    drain(db)

    [action] = ads_actions(db)
    assert action.status == ActionStatus.UNKNOWN_OUTCOME.value
    assert fake.effects_of(ADS) == 1  # en el mundo real sí ocurrió
    assert ledger(db) == (60_000.0, 0.0)
    db.refresh(run)
    assert run.status == PipelineRunStatus.BLOCKED


def test_06_a_provider_that_did_not_execute_and_times_out_is_released_only_when_asked(db: Session, monkeypatch):
    fake = FakeLookupProviderAdapter(behaviors=["timeout_before"], only_operation=ADS)
    monkeypatch.setattr("app.pipeline.service.SimulatedAdapter", lambda: fake)
    PipelineOrchestrator(db).enqueue_run(request())
    drain(db)
    [action] = ads_actions(db)
    assert action.status == ActionStatus.UNKNOWN_OUTCOME.value  # desde fuera, igual que el caso 5
    assert ledger(db) == (60_000.0, 0.0)

    status = ExternalActionService(db).reconcile(action, fake, {})

    assert status is ActionStatus.FAILED_CONFIRMED  # solo la consulta lo afirma
    assert ledger(db) == (0.0, 0.0)
    assert fake.effects_of(ADS) == 0


# --- 7. La respuesta llega tarde ---------------------------------------------------------------


def test_07_a_late_response_settles_the_operation_once_and_a_second_delivery_changes_nothing(db: Session, monkeypatch):
    fake = FakeLookupProviderAdapter(behaviors=["timeout_after"], only_operation=ADS)
    monkeypatch.setattr("app.pipeline.service.SimulatedAdapter", lambda: fake)
    PipelineOrchestrator(db).enqueue_run(request())
    drain(db)
    [action] = ads_actions(db)
    service = ExternalActionService(db)

    assert service.reconcile(action, fake, {}) is ActionStatus.SUCCEEDED  # la respuesta tardía: el proveedor lo tiene
    assert service.reconcile(action, fake, {}) is ActionStatus.SUCCEEDED  # llega otra vez
    with pytest.raises(ExternalActionStateError):
        service.resolve(action, succeeded=False, actor=OWNER, reason="a person disagreeing with a settled outcome")

    assert ledger(db) == (0.0, 60_000.0)
    assert db.query(FinancialEvent).filter_by(type="COMMIT").count() == 1  # se comprometió una sola vez


# --- 8. Reintento en otro worker -------------------------------------------------------------


def test_08_a_retry_in_another_worker_cannot_repeat_the_effect():
    with ephemeral_postgres() as engine:
        authorise(engine)
        with Session(engine) as seed:
            run_id = PipelineOrchestrator(seed).enqueue_run(request()).id
        provider = SlowProvider(only_operation=ADS)

        def executor(session: Session):
            PipelineOrchestrator(session, action_adapters={"marketing": provider}).execute_run(run_id)
            return "finished"

        results = run_together(engine, [executor, executor])

        # Dos ejecutores del mismo paso: sale **una** petición (el compare-and-set de `begin_call`), no dos que el
        # proveedor deduplique después por la clave: ese es el segundo cerrojo, no el primero.
        assert len([r for r in provider.requests if r.operation == ADS]) == 1
        assert provider.effects_of(ADS) == 1
        assert "finished" in results  # y uno de ellos lo terminó
        assert scalar(engine, "select count(*) from financial_events where type = 'RESERVE'") == 1
        assert float(scalar(engine, "select committed from budget_allocations")) == 60_000.0


# --- 9. Dos workers consumen la misma aprobación ----------------------------------------------


def test_09_two_workers_cannot_consume_the_same_approval():
    with ephemeral_postgres() as engine:
        with Session(engine) as seed:
            run = PipelineOrchestrator(seed).enqueue_run(request(sale_price=0.5))
            review = PipelineReview(
                pipeline_run_id=run.id,
                kind="ACTION_GATE",
                step="ecommerce",
                action="publish_product",
                reasons=["test"],
                status="APPROVED",
                correlation_id=run.correlation_id,
            )
            seed.add(review)
            seed.commit()
            run_id, review_id = run.id, review.id

        def consume(session: Session):
            step = session.query(PipelineStep).filter_by(pipeline_run_id=run_id, name="ecommerce").one()
            authorisation = session.get(PipelineReview, review_id)
            PipelineOrchestrator(session)._start_step(step, None, authorisation=authorisation)
            return "consumed"

        results = run_together(engine, [consume] * 8)

        assert collections.Counter(type(r).__name__ if not isinstance(r, str) else r for r in results) == {
            "consumed": 1,
            PipelineRunStateError.__name__: 7,
        }
        assert scalar(engine, f"select status from pipeline_reviews where id = '{review_id}'") == "CONSUMED"


# --- 10. Presupuesto casi agotado y dos acciones compiten -----------------------------------


def test_10_two_pipeline_actions_competing_for_the_last_of_the_budget_cannot_both_fit():
    with ephemeral_postgres() as engine:
        authorise(engine, 100_000.0)
        with Session(engine) as seed:
            run_ids = [PipelineOrchestrator(seed).enqueue_run(request(60_000.0)).id for _ in range(2)]

        def execute(run_id: str):
            def job(session: Session):
                PipelineOrchestrator(session).execute_run(run_id)
                step = session.query(PipelineStep).filter_by(pipeline_run_id=run_id, name="marketing").one()
                return step.status

            return job

        results = run_together(engine, [execute(run_id) for run_id in run_ids])

        assert errors(results) == []
        assert collections.Counter(results) == {PipelineStepStatus.COMPLETED: 1, PipelineStepStatus.DENIED: 1}
        reserved, committed = (
            float(scalar(engine, "select reserved from budget_allocations")),
            float(scalar(engine, "select committed from budget_allocations")),
        )
        assert reserved + committed == 60_000.0


# --- 11. El CEO y el pipeline compiten por el mismo saldo -------------------------------------


def test_11_the_ceo_and_the_pipeline_competing_for_the_same_balance_cannot_both_fit():
    with ephemeral_postgres() as engine:
        authorise(engine, 100_000.0)
        with Session(engine) as seed:
            objective = Objective(id=new_id(), title="spend", created_by=OWNER, context=CEO_CONTEXT)
            seed.add(objective)
            seed.commit()
            objective_id = objective.id
            run_id = PipelineOrchestrator(seed).enqueue_run(request(60_000.0)).id

        def ceo(session: Session):
            CEOOrchestrator(session).run_objective(objective_id)
            session.commit()
            return "ceo"

        def pipeline(session: Session):
            PipelineOrchestrator(session).execute_run(run_id)
            return "pipeline"

        results = run_together(engine, [ceo, pipeline])

        assert errors(results) == []
        assert scalar(engine, "select count(*) from financial_events where type = 'RESERVE'") == 1  # una sola cabe
        reserved = float(scalar(engine, "select reserved from budget_allocations"))
        committed = float(scalar(engine, "select committed from budget_allocations"))
        assert reserved + committed == 60_000.0


# --- 12. El kill switch se activa entre la autorización y el efecto ---------------------------


def test_12_a_kill_switch_turned_on_between_authorisation_and_effect_sends_nothing(db: Session, monkeypatch):
    fake = use_provider(monkeypatch)
    run = PipelineOrchestrator(db).enqueue_run(request())
    real_begin = ExternalActionService.begin_call
    switched = {"done": False}

    def switch_off_then_begin(self, action):
        if action.operation == ADS and not switched["done"]:
            switched["done"] = True
            PipelineKillSwitchService(self._db).disable(reason="drill", actor=OWNER, correlation_id="chaos-12")
        return real_begin(self, action)

    monkeypatch.setattr(ExternalActionService, "begin_call", switch_off_then_begin)
    drain(db)

    db.refresh(run)
    assert run.status == PipelineRunStatus.BLOCKED
    assert fake.effects_of(ADS) == 0
    [action] = ads_actions(db)
    assert action.status == ActionStatus.PENDING.value
    first_key = action.idempotency_key

    PipelineKillSwitchService(db).enable(actor=OWNER, correlation_id="chaos-12b")
    resume(db, run)

    [again] = ads_actions(db)
    assert again.id == action.id and again.idempotency_key == first_key  # la misma operación, la misma clave
    assert fake.effects_of(ADS) == 1


# --- 13. La aprobación caduca entre la reserva y la ejecución -------------------------------


def test_13_an_approval_that_expires_between_reservation_and_resolution_releases_once_and_cannot_be_used(
    client: TestClient, db: Session
):
    objective = Objective(id=new_id(), title="spend", created_by=OWNER, context=CEO_CONTEXT)
    db.add(objective)
    db.commit()
    CEOOrchestrator(db).run_objective(objective.id)
    db.commit()
    approval = db.query(Approval).one()
    assert ledger(db) == (60_000.0, 0.0)  # reservado al pedir la aprobación
    approval.expires_at = datetime.datetime.now(datetime.UTC) - datetime.timedelta(minutes=1)
    db.commit()

    first = client.post(f"/api/approvals/{approval.id}/approve", json={"actor": OWNER})
    second = client.post(f"/api/approvals/{approval.id}/approve", json={"actor": OWNER})

    assert first.status_code == second.status_code == 409  # caducó: ya no autoriza nada
    db.refresh(approval)
    assert approval.status == "EXPIRED"
    assert ledger(db) == (0.0, 0.0)
    assert db.query(FinancialEvent).filter_by(type="RELEASE").count() == 1  # liberada una sola vez
    assert db.query(FinancialEvent).filter_by(type="COMMIT").count() == 0


# --- 14. La misma petición tras reiniciar el proceso ---------------------------------------


def test_14_the_same_request_after_a_restart_returns_the_original_response(session_factory):
    engine = session_factory.kw["bind"]

    def serve(factory) -> TestClient:
        def override_get_db():
            session = factory()
            try:
                yield session
            finally:
                session.close()

        app.dependency_overrides[get_db] = override_get_db
        return TestClient(app, raise_server_exceptions=False)

    try:
        before_restart = serve(session_factory).post(
            "/api/research/runs", json={"category": "home"}, headers={"Idempotency-Key": "chaos-14"}
        )
        after_restart = serve(sessionmaker(bind=engine, expire_on_commit=False)).post(  # otra «vida» del proceso
            "/api/research/runs", json={"category": "home"}, headers={"Idempotency-Key": "chaos-14"}
        )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert after_restart.json() == before_restart.json()
    assert after_restart.headers["Idempotency-Replayed"] == "true"


# --- 15. Un adaptador sin idempotencia ------------------------------------------------------


def test_15_an_adapter_without_idempotency_gets_no_key_and_is_never_replayed(db: Session):
    fake = FakeProviderAdapter(supports_idempotency=False, behaviors=["timeout_after"], only_operation=ADS)
    orchestrator = PipelineOrchestrator(db, action_adapters={"marketing": fake})
    run = orchestrator.enqueue_run(request())
    with pytest.raises(Exception, match="unknown"):
        orchestrator.execute_run(run.id)

    resume(db, run)  # reanudar sin resolver

    assert [r.idempotency_key for r in fake.requests if r.operation == ADS] == [None]
    assert fake.effects_of(ADS) == 1  # una sola petición, jamás un reintento ciego
    assert ledger(db) == (60_000.0, 0.0)


# --- 16. Coste declarado 0 --------------------------------------------------------------------


def test_16_a_declared_zero_cost_reserves_nothing_and_completes(db: Session):
    run = PipelineOrchestrator(db).enqueue_run(request(0.0))

    drain(db)

    assert marketing_step(db, run).status == PipelineStepStatus.COMPLETED
    assert db.query(FinancialEvent).count() == 0  # coste cero conocido: no hay nada que reservar


# --- 17. Coste desconocido --------------------------------------------------------------------


def test_17_an_unknown_cost_is_denied_even_in_a_simulation(db: Session):
    decision = ActionGateService(db, settings=Settings(_env_file=None)).evaluate(
        SideEffectAction.ACTIVATE_ADS, amount=None
    )

    assert decision.outcome is GateOutcome.DENY
    assert any("unknown cost is not zero" in reason for reason in decision.reasons)


# --- 18. Ausencia de presupuesto --------------------------------------------------------------


def test_18_without_a_budget_a_real_spend_is_denied_and_a_simulated_one_moves_no_ledger(session_factory):
    with session_factory() as empty:
        real = ActionGateService(empty, settings=Settings(_env_file=None, ads_provider=ProviderKind.REAL))
        assert real.evaluate(SideEffectAction.ACTIVATE_ADS, amount=10.0, actor_role="owner").outcome is GateOutcome.DENY

        run = PipelineOrchestrator(empty).enqueue_run(request(20.0))
        drain(empty)

        assert marketing_step(empty, run).status == PipelineStepStatus.COMPLETED  # simulación declarada
        assert empty.query(FinancialEvent).count() == 0


# --- 19. Permisos desconocidos ----------------------------------------------------------------


def test_19_an_unknown_role_is_not_a_permission_outside_a_simulation(db: Session):
    real = ActionGateService(db, settings=Settings(_env_file=None, marketplaces_provider=ProviderKind.REAL))
    simulated = ActionGateService(db, settings=Settings(_env_file=None))

    assert real.evaluate(PUBLISH, actor_role=None).outcome is GateOutcome.DENY
    assert simulated.evaluate(PUBLISH, actor_role=None).outcome is GateOutcome.ALLOW


# --- 20. Recuperación de un resultado desconocido ----------------------------------------------


def test_20_an_unknown_outcome_recovers_by_lookup_and_the_run_finishes_without_repeating_the_effect(
    db: Session, monkeypatch
):
    fake = FakeLookupProviderAdapter(behaviors=["timeout_after"], only_operation=ADS)
    monkeypatch.setattr("app.pipeline.service.SimulatedAdapter", lambda: fake)
    run = PipelineOrchestrator(db).enqueue_run(request())
    drain(db)
    [action] = ads_actions(db)
    assert action.status == ActionStatus.UNKNOWN_OUTCOME.value

    assert ExternalActionService(db).reconcile(action, fake, {}) is ActionStatus.SUCCEEDED
    resume(db, run)

    db.refresh(run)
    assert run.status == PipelineRunStatus.COMPLETED
    assert fake.effects_of(ADS) == 1
    assert ledger(db) == (0.0, 60_000.0)
    assert db.get(PipelineRun, run.id).failed_step is None
