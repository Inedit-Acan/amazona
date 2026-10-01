"""Los doce invariantes de la fase 2 del hardening pre-M44 (fase 9).

Cada test fija **una frase**, no un caso: si algún día alguien cambia el código y una de estas frases deja de ser
cierta, el nombre del test dice cuál. Los escenarios concretos (crashes, carreras, timeouts) están en
`test_chaos_scenarios.py`; aquí está lo que tiene que valer siempre, sea cual sea el escenario.

    I1  una autorización humana produce como máximo un efecto
    I2  un evento económico se contabiliza como máximo una vez
    I3  una solicitud idempotente produce como máximo una ejecución lógica
    I4  un retry nunca crea gasto adicional por sí solo
    I5  UNKNOWN_OUTCOME nunca se transforma automáticamente en FAILED seguro
    I6  un presupuesto no puede reservarse por encima del límite mediante concurrencia
    I7  CEO y pipeline ven la misma disponibilidad
    I8  la ausencia de presupuesto no equivale a permiso
    I9  la ausencia de rol no equivale a permiso fuera de simulación
    I10 una lectura no produce escritura salvo contrato explícito
    I11 el kill switch no puede crearse accidentalmente leyendo
    I12 ningún proveedor real puede ser llamado durante los tests   (tests/unit/test_network_is_blocked_in_tests.py)
"""

import datetime
import re

import pytest
from action_test_support import FakeProviderAdapter
from chaos_test_support import (
    ADS,
    OWNER,
    ads_actions,
    drain,
    expire_lease,
    ledger,
    request,
    resume,
    run_together,
    scalar,
    use_provider,
)
from fastapi.testclient import TestClient
from pg_test_support import ephemeral_postgres
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.actions.contract import ActionStatus
from app.actions.service import ExternalActionService
from app.budgets.engine import BudgetStatus
from app.budgets.service import BudgetLedgerService
from app.ceo.orchestrator import CEOOrchestrator
from app.ceo.schemas import DecisionStatus
from app.core.config import Settings
from app.core.ids import new_id
from app.db.base import Base
from app.db.models.budget import Budget, FinancialEvent
from app.db.models.objective import Objective
from app.db.models.pipeline_kill_switch import PipelineKillSwitch
from app.db.models.pipeline_review import PipelineReview
from app.db.models.pipeline_run import PipelineRun
from app.db.session import get_db
from app.gates.action_gate import GateOutcome, SideEffectAction
from app.gates.service import ActionGateService
from app.integrations.ports import ProviderKind
from app.jobs.worker import Worker
from app.main import app
from app.pipeline.kill_switch import PipelineKillSwitchService
from app.pipeline.schemas import PipelineRunStatus
from app.pipeline.service import PipelineOrchestrator, PipelineRequest

PUBLISH = SideEffectAction.PUBLISH_PRODUCT.value
GATED = PipelineRequest(category="home", sale_price=0.5, destination_region="mexico", market="us")
SPEND_CONTEXT = {
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


@pytest.fixture()
def engine():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def empty_db(engine):
    with sessionmaker(bind=engine, expire_on_commit=False)() as session:
        yield session


@pytest.fixture()
def db(empty_db: Session):
    """Con un presupuesto de 100 000 autorizado por el propietario."""
    BudgetLedgerService(empty_db).authorise_budget(hard_limit=100_000.0, actor=OWNER)
    return empty_db


def approve(db: Session, review: PipelineReview) -> None:
    """Lo que hace la API al aprobar una puerta: marcar la revisión y reanudar."""
    review.status = "APPROVED"
    review.resolved_at = datetime.datetime.now(datetime.UTC)
    review.resolved_by = OWNER
    db.flush()
    PipelineOrchestrator(db).resume_run(db.get(PipelineRun, review.pipeline_run_id), actor=OWNER)
    db.commit()


def pending_gate(db: Session) -> PipelineReview:
    db.expire_all()
    return db.query(PipelineReview).filter_by(kind="ACTION_GATE", status="PENDING").one()


# --- I1 -------------------------------------------------------------------------------------


def test_i1_one_human_authorisation_produces_at_most_one_effect(db: Session, monkeypatch):
    fake = FakeProviderAdapter()
    monkeypatch.setattr("app.pipeline.service.SimulatedAdapter", lambda: fake)
    run = PipelineOrchestrator(db).enqueue_run(GATED)
    drain(db)
    approve(db, pending_gate(db))  # una firma
    drain(db)
    assert fake.effects_of(PUBLISH) == 1

    PipelineOrchestrator(db).resume_run(db.get(PipelineRun, run.id), actor=OWNER, from_step="ecommerce")  # rehacer
    drain(db)

    assert fake.effects_of(PUBLISH) == 1  # la misma firma no vale para un segundo efecto
    db.refresh(run)
    assert run.status == PipelineRunStatus.WAITING_APPROVAL  # vuelve a preguntar


# --- I2 -------------------------------------------------------------------------------------


def event_of(kind: str, reference: str) -> FinancialEvent:
    return FinancialEvent(type=kind, amount=10.0, reference=reference)


def test_i2_an_economic_event_is_counted_at_most_once(db: Session):
    db.add_all([event_of("RESERVE", "ref"), event_of("COMMIT", "ref")])
    db.commit()

    for duplicate in ("RESERVE", "COMMIT", "RELEASE"):
        with pytest.raises(IntegrityError):
            db.add(event_of(duplicate, "ref"))
            db.commit()
        db.rollback()

    assert db.query(FinancialEvent).filter_by(reference="ref").count() == 2


def test_i2_a_settled_operation_is_never_settled_again_by_the_service(db: Session):
    fake = FakeProviderAdapter(supports_idempotency=False, behaviors=["timeout_after"], only_operation=ADS)
    orchestrator = PipelineOrchestrator(db, action_adapters={"marketing": fake})
    run = orchestrator.enqueue_run(request())
    with pytest.raises(Exception, match="unknown"):
        orchestrator.execute_run(run.id)
    [action] = ads_actions(db)
    service = ExternalActionService(db)

    service.resolve(action, succeeded=True, actor=OWNER, reason="seen in the console")
    for _ in range(3):
        with pytest.raises(Exception):  # noqa: B017 - cualquier intento de repetirlo falla; lo que importa es el libro
            service.resolve(action, succeeded=True, actor=OWNER, reason="again")

    assert db.query(FinancialEvent).filter_by(type="COMMIT").count() == 1
    assert ledger(db) == (0.0, 60_000.0)


# --- I3 -------------------------------------------------------------------------------------


@pytest.fixture()
def client(engine):
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override_get_db():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app, raise_server_exceptions=False)
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_i3_an_idempotent_request_has_one_logical_execution(client: TestClient, db: Session):
    objective = Objective(id=new_id(), title="spend", created_by=OWNER, context=SPEND_CONTEXT)
    db.add(objective)
    db.commit()

    first = client.post(f"/api/objectives/{objective.id}/run", headers={"Idempotency-Key": "i3"})
    replays = [client.post(f"/api/objectives/{objective.id}/run", headers={"Idempotency-Key": "i3"}) for _ in range(3)]

    assert all(r.json() == first.json() for r in replays)
    assert db.query(FinancialEvent).filter_by(type="RESERVE").count() == 1


def test_i3_a_pipeline_run_created_twice_with_the_same_key_is_one_run(client: TestClient, db: Session):
    body = {"category": "home", "sale_price": 50.0, "destination_region": "mexico", "market": "us"}

    first = client.post("/api/pipeline/runs", json=body, headers={"Idempotency-Key": "i3-run"})
    second = client.post("/api/pipeline/runs", json=body, headers={"Idempotency-Key": "i3-run"})

    assert first.json()["correlation_id"] == second.json()["correlation_id"]
    assert db.query(PipelineRun).count() == 1


# --- I4 -------------------------------------------------------------------------------------


def test_i4_a_retry_never_creates_extra_spend_by_itself(db: Session, monkeypatch):
    fake = use_provider(monkeypatch)
    run = PipelineOrchestrator(db).enqueue_run(request())
    real_begin = ExternalActionService.begin_call

    def dies_once(self, action):
        if action.operation == ADS:
            raise KeyboardInterrupt("died before the request left")
        return real_begin(self, action)

    monkeypatch.setattr(ExternalActionService, "begin_call", dies_once)
    with pytest.raises(KeyboardInterrupt):
        Worker(name="worker-1").run_once(db)
    db.rollback()
    expire_lease(db, run)
    monkeypatch.setattr(ExternalActionService, "begin_call", real_begin)
    drain(db)  # el reintento

    assert db.query(FinancialEvent).filter_by(type="RESERVE").count() == 1  # una reserva por gasto, no por intento
    assert ledger(db) == (0.0, 60_000.0)
    assert fake.effects_of(ADS) == 1


def test_i4_resuming_a_run_that_is_waiting_on_an_unknown_outcome_spends_nothing_more(db: Session, monkeypatch):
    fake = use_provider(monkeypatch, "timeout_after")
    run = PipelineOrchestrator(db).enqueue_run(request())
    drain(db)
    before = (ledger(db), len(fake.requests), db.query(FinancialEvent).count())

    for _ in range(3):
        resume(db, run)

    assert (ledger(db), len(fake.requests), db.query(FinancialEvent).count()) == before


# --- I5 -------------------------------------------------------------------------------------


def test_i5_an_unknown_outcome_is_never_turned_into_a_safe_failure_automatically(db: Session, monkeypatch):
    fake = use_provider(monkeypatch, "timeout_after")
    run = PipelineOrchestrator(db).enqueue_run(request())
    drain(db)
    [action] = ads_actions(db)
    service = ExternalActionService(db)

    service.reconcile_interrupted(older_than=datetime.timedelta(seconds=-1))  # el barrido
    service.mark_interrupted(action.reference)  # mirar otra vez
    service.reconcile(action, FakeProviderAdapter(supports_idempotency=False), {})  # sin consulta ni idempotencia
    resume(db, run)  # reanudar
    expire_lease(db, run)
    drain(db)  # y otro worker lo recoge

    db.refresh(action)
    assert action.status == ActionStatus.UNKNOWN_OUTCOME.value
    assert db.query(FinancialEvent).filter_by(type="RELEASE").count() == 0
    assert ledger(db) == (60_000.0, 0.0)
    assert fake.effects_of(ADS) == 1


# --- I6 -------------------------------------------------------------------------------------


def test_i6_a_budget_cannot_be_reserved_above_its_limit_by_concurrency():
    with ephemeral_postgres() as pg:
        with Session(pg) as seed:
            BudgetLedgerService(seed).authorise_budget(hard_limit=100.0, actor=OWNER)

        def reserve(amount: float, reference: str):
            def job(session: Session):
                ok = BudgetLedgerService(session).reserve(amount=amount, reference=reference)
                session.commit()
                return amount, ok

            return job

        amounts = [30.0, 30.0, 30.0, 30.0, 25.0, 25.0, 25.0, 25.0, 10.0, 10.0, 10.0, 10.0]
        results = run_together(pg, [reserve(a, f"r-{i}") for i, a in enumerate(amounts)])

        assert not [r for r in results if isinstance(r, Exception)]
        reserved = float(scalar(pg, "select reserved from budget_allocations"))
        committed = float(scalar(pg, "select committed from budget_allocations"))
        assert reserved + committed <= 100.0
        won = sum(amount for amount, ok in results if ok)
        assert reserved == won  # y lo que dijo «sí» es exactamente lo que quedó reservado


# --- I7 -------------------------------------------------------------------------------------


def test_i7_the_ceo_and_the_pipeline_see_the_same_availability(db: Session):
    ledger_service = BudgetLedgerService(db)
    gate = ActionGateService(db, settings=Settings(_env_file=None))
    objective = Objective(id=new_id(), title="spend", created_by=OWNER, context=SPEND_CONTEXT)
    db.add(objective)
    db.commit()

    CEOOrchestrator(db).run_objective(objective.id)  # el CEO reserva 60 000
    db.commit()

    for amount in (10_000.0, 40_000.0, 40_001.0, 100_000.0):
        from_the_ledger = ledger_service.assess(amount, simulated=True)
        decision = gate.evaluate(SideEffectAction.ACTIVATE_ADS, amount=amount, actor_role="owner")
        fits = from_the_ledger.status is BudgetStatus.AVAILABLE
        assert fits is (decision.outcome is not GateOutcome.DENY), amount  # la misma respuesta, venga de donde venga
    assert ledger_service.snapshot().reserved == 60_000.0


# --- I8 -------------------------------------------------------------------------------------


def test_i8_the_absence_of_a_budget_is_not_a_permission(empty_db: Session):
    real = ActionGateService(empty_db, settings=Settings(_env_file=None, ads_provider=ProviderKind.REAL))

    decision = real.evaluate(SideEffectAction.ACTIVATE_ADS, amount=10.0, actor_role="owner")

    assert decision.outcome is GateOutcome.DENY
    assert any("no budget has been authorised" in reason for reason in decision.reasons)
    assert empty_db.query(Budget).count() == 0  # y preguntar no lo crea


def test_i8_the_ceo_does_not_approve_a_real_spend_without_a_budget(empty_db: Session):
    objective = Objective(id=new_id(), title="spend", created_by=OWNER, context=SPEND_CONTEXT)
    empty_db.add(objective)
    empty_db.commit()
    settings = Settings(_env_file=None, ads_provider=ProviderKind.REAL)

    decision = CEOOrchestrator(empty_db, settings=settings).run_objective(objective.id)

    assert decision.status == DecisionStatus.NO_GO.value
    assert empty_db.query(FinancialEvent).count() == 0


# --- I9 -------------------------------------------------------------------------------------


def test_i9_the_absence_of_a_role_is_not_a_permission_outside_a_simulation(db: Session):
    real = ActionGateService(db, settings=Settings(_env_file=None, marketplaces_provider=ProviderKind.REAL))

    decision = real.evaluate(SideEffectAction.PUBLISH_PRODUCT, actor_role=None)

    assert decision.outcome is GateOutcome.DENY


# --- I10 -------------------------------------------------------------------------------------


def test_i10_a_read_produces_no_write_on_any_get_route(engine, client: TestClient):
    """Sobre una base **vacía**, el peor caso para un «get-or-create al leer» (el interruptor, el presupuesto): ninguna
    ruta `GET` escribe. Una que tenga que hacerlo habría de declararse aquí, con su motivo."""
    writes: list[str] = []

    @event.listens_for(engine, "before_cursor_execute")
    def capture(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().split(None, 1)[0].upper() in ("INSERT", "UPDATE", "DELETE"):
            writes.append(statement[:90])

    paths = sorted(path for path, item in app.openapi()["paths"].items() if "get" in item)
    assert len(paths) >= 24
    offenders: dict[str, list[str]] = {}
    for path in paths:
        writes.clear()
        client.get(_fill(path))
        if writes:
            offenders[path] = list(writes)

    assert offenders == {}, "a GET route wrote to the database"


def _fill(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "does-not-exist", path)


# --- I11 -------------------------------------------------------------------------------------


def test_i11_the_kill_switch_is_never_created_by_reading(engine, empty_db: Session, client: TestClient):
    switch = PipelineKillSwitchService(empty_db)

    assert switch.is_enabled() is True
    assert switch.get_state().persisted is False
    ActionGateService(empty_db, settings=Settings(_env_file=None)).evaluate(SideEffectAction.PUBLISH_PRODUCT)
    assert client.get("/api/pipeline/kill-switch").status_code == 200
    PipelineOrchestrator(empty_db).enqueue_run(request())

    assert empty_db.query(PipelineKillSwitch).count() == 0  # ni mirando, ni evaluando, ni encolando

    switch.disable(reason="drill", actor=OWNER, correlation_id="i11")  # solo un acto explícito lo crea
    assert empty_db.query(PipelineKillSwitch).count() == 1
    assert switch.is_enabled() is False


def test_i11_the_default_state_is_enabled_and_not_persisted(empty_db: Session):
    state = PipelineKillSwitchService(empty_db).get_state()

    assert (state.enabled, state.persisted) == (True, False)
