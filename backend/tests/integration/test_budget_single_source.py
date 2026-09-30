"""Una sola verdad presupuestaria antes de cualquier efecto (hardening pre-M44, D12 + D14).

Antes, el CEO aprobaba cada solicitud contra un `BudgetState` **en memoria**, nuevo en cada
petición y con un techo de 100 000 escrito en el código, mientras el ActionGate leía el libro de
la base de datos. Medido: tres solicitudes de 60 000 contra un techo de 100 000 fueron aprobadas
por el CEO, el libro acabó con 180 000 reservados y el gate vio −80 000 disponibles y denegó todo
gasto: el CEO decía sí y el gate decía no.

Ahora los dos preguntan al mismo libro (`BudgetLedgerService`), que solo tiene presupuesto si el
propietario lo autorizó, y reservan comprobando el límite en la misma sentencia que escribe. El
pipeline también reserva el gasto de su paso, así que una reserva hecha por cualquiera de las
vías cuenta contra las demás.
"""

import datetime
import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app import cli
from app.budgets.engine import BudgetStatus
from app.budgets.service import BudgetLedgerService
from app.ceo.orchestrator import CEOOrchestrator
from app.ceo.schemas import DecisionStatus
from app.core.config import Settings
from app.core.ids import new_id
from app.db.base import Base
from app.db.models.approval import Approval
from app.db.models.audit import AuditLog
from app.db.models.budget import BudgetAllocation, FinancialEvent
from app.db.models.objective import Objective
from app.db.models.pipeline_run import PipelineRun
from app.db.models.pipeline_step import PipelineStep
from app.gates.action_gate import GateOutcome, SideEffectAction
from app.gates.service import ActionGateService
from app.integrations.ports import ProviderKind
from app.jobs.worker import Worker
from app.pipeline.schemas import PipelineStepStatus
from app.pipeline.service import PipelineOrchestrator, PipelineRequest

OWNER = "owner@amazona.local"


def context(amount: float | None) -> dict:
    base = {
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
    }
    if amount is not None:
        base["spend_amount"] = amount
    return base


@pytest.fixture()
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def authorise(db: Session, hard_limit: float = 100_000.0) -> BudgetLedgerService:
    ledger = BudgetLedgerService(db)
    ledger.authorise_budget(hard_limit=hard_limit, actor=OWNER)
    return ledger


def ceo_request(db: Session, amount: float | None, settings: Settings | None = None):
    objective = Objective(id=new_id(), title="spend", created_by=OWNER, context=context(amount))
    db.add(objective)
    db.commit()
    decision = CEOOrchestrator(db, settings=settings).run_objective(objective.id)
    db.commit()
    return decision


def gate(db: Session, **settings) -> ActionGateService:
    return ActionGateService(db, settings=Settings(_env_file=None, **settings))


def allocation(db: Session) -> tuple[float, float, float]:
    db.expire_all()
    row = db.query(BudgetAllocation).one()
    return float(row.reserved), float(row.committed), float(row.spent)


def drain(db: Session, rounds: int = 12) -> None:
    worker = Worker(name="test-worker")
    for _ in range(rounds):
        if worker.run_once(db) is None:
            break


def pipeline_spend(db: Session, amount: float, settings: Settings | None = None) -> PipelineRun:
    """Una ejecución del pipeline cuyo paso de marketing gasta `amount`."""
    orchestrator = PipelineOrchestrator(
        db, gate=ActionGateService(db, settings=settings) if settings is not None else None
    )
    request = PipelineRequest(
        category="home", sale_price=50.0, destination_region="mexico", market="us", daily_budget=amount
    )
    run = orchestrator.enqueue_run(request)
    if settings is None:
        drain(db)
    else:
        # El worker construye su propio orquestador con la configuración por defecto: para probar
        # otra configuración, la ejecución se lanza directamente con este.
        orchestrator.execute_run(run.id)
    db.refresh(run)
    return run


def marketing_step(db: Session, run: PipelineRun) -> PipelineStep:
    return db.query(PipelineStep).filter_by(pipeline_run_id=run.id, name="marketing").one()


# --- D14: no existe un universo donde el CEO diga sí y el gate diga no -----------------


def test_the_ceo_and_the_gate_agree_a_second_60000_does_not_fit_in_100000(db: Session):
    authorise(db, 100_000.0)

    first = ceo_request(db, 60_000.0)
    second = ceo_request(db, 60_000.0)

    assert first.status == DecisionStatus.HUMAN_APPROVAL.value
    assert second.status == DecisionStatus.NO_GO.value
    assert "budget denied" in second.rationale
    assert db.query(Approval).count() == 1  # la denegada no deja una aprobación pendiente
    assert allocation(db) == (60_000.0, 0.0, 0.0)
    # El gate, por su lado, dice lo mismo sobre lo que queda.
    assert gate(db).evaluate(SideEffectAction.ACTIVATE_ADS, amount=60_000.0).outcome is GateOutcome.DENY
    assert gate(db).evaluate(SideEffectAction.ACTIVATE_ADS, amount=40_000.0).outcome is GateOutcome.ALLOW


def test_the_old_divergence_three_requests_of_60000_cannot_reserve_180000(db: Session):
    authorise(db, 100_000.0)

    statuses = [ceo_request(db, 60_000.0).status for _ in range(3)]

    assert statuses == ["HUMAN_APPROVAL", "NO_GO", "NO_GO"]
    assert allocation(db)[0] == 60_000.0  # nunca por encima del techo


def test_a_pipeline_spend_counts_against_a_later_ceo_request(db: Session):
    authorise(db, 100_000.0)

    run = pipeline_spend(db, 60_000.0)

    assert marketing_step(db, run).status == PipelineStepStatus.COMPLETED
    assert allocation(db) == (0.0, 60_000.0, 60_000.0)  # gastado al completar el paso
    assert ceo_request(db, 60_000.0).status == DecisionStatus.NO_GO.value
    assert ceo_request(db, 40_000.0).status == DecisionStatus.HUMAN_APPROVAL.value


def test_a_ceo_reservation_counts_against_a_later_pipeline_spend(db: Session):
    authorise(db, 100_000.0)
    assert ceo_request(db, 60_000.0).status == DecisionStatus.HUMAN_APPROVAL.value

    run = pipeline_spend(db, 60_000.0)

    step = marketing_step(db, run)
    assert step.status == PipelineStepStatus.DENIED
    assert "exceeds hard limit" in step.error
    assert allocation(db) == (60_000.0, 0.0, 0.0)  # el pipeline no reservó nada


def test_two_pipeline_runs_cannot_spend_more_than_fits_between_them(db: Session):
    authorise(db, 100_000.0)

    first = pipeline_spend(db, 60_000.0)
    second = pipeline_spend(db, 60_000.0)

    assert marketing_step(db, first).status == PipelineStepStatus.COMPLETED
    assert marketing_step(db, second).status == PipelineStepStatus.DENIED
    assert allocation(db) == (0.0, 60_000.0, 60_000.0)


def test_approving_a_ceo_request_commits_what_the_shared_ledger_reserved(db: Session):
    from app.api import approvals as approvals_api
    from app.auth.actor import Actor, ActorSource, RoleName

    authorise(db, 100_000.0)
    ceo_request(db, 60_000.0)
    approval = db.query(Approval).one()

    approvals_api._resolve(
        approval.id,
        "APPROVED",
        db,
        Actor(subject=OWNER, role=RoleName.OWNER, source=ActorSource.DECLARED),
        None,
        Settings(_env_file=None),
    )

    assert allocation(db) == (0.0, 60_000.0, 60_000.0)
    assert ceo_request(db, 60_000.0).status == DecisionStatus.NO_GO.value


# --- D12: la ausencia no es un permiso ------------------------------------------------


def test_without_a_budget_a_simulated_ceo_spend_passes_declared_as_simulated_and_moves_no_ledger(db: Session):
    decision = ceo_request(db, 500.0)

    assert decision.status == DecisionStatus.HUMAN_APPROVAL.value
    requested = db.query(AuditLog).filter_by(action="approval.requested").one()
    assert requested.after["budget"] == BudgetStatus.SIMULATED_NO_BUDGET.value
    assert db.query(BudgetAllocation).count() == 0
    assert db.query(FinancialEvent).count() == 0  # no hay libro que mover, y no se inventa uno


def test_without_a_budget_a_real_ceo_spend_is_denied(db: Session):
    real = Settings(_env_file=None, ads_provider=ProviderKind.REAL)

    decision = ceo_request(db, 500.0, settings=real)

    assert decision.status == DecisionStatus.NO_GO.value
    assert "no budget has been authorised" in decision.rationale
    denied = db.query(AuditLog).filter_by(action="decision.budget_denied").one()
    assert denied.after["budget"] == BudgetStatus.NO_BUDGET_RECORD.value
    assert db.query(Approval).count() == 0


def test_a_ceo_spend_without_an_amount_is_denied_because_unknown_is_not_zero(db: Session):
    authorise(db)

    decision = ceo_request(db, None)

    assert decision.status == DecisionStatus.NO_GO.value
    assert "unknown cost is not zero" in decision.rationale
    assert db.query(Approval).count() == 0


def test_the_pipeline_spends_in_a_simulation_without_a_budget_and_moves_no_ledger(db: Session):
    run = pipeline_spend(db, 20.0)

    assert marketing_step(db, run).status == PipelineStepStatus.COMPLETED
    assert db.query(FinancialEvent).count() == 0


def test_the_pipeline_denies_a_real_spend_without_a_budget(db: Session):
    run = pipeline_spend(db, 20.0, settings=Settings(_env_file=None, ads_provider=ProviderKind.REAL))

    step = marketing_step(db, run)
    assert step.status == PipelineStepStatus.DENIED
    assert "no budget has been authorised" in step.error


# --- El ciclo de reserva del paso ---------------------------------------------------


def test_a_step_that_fails_keeps_its_reservation_because_a_failure_is_not_a_zero(db: Session, monkeypatch):
    authorise(db, 100_000.0)

    def fails(self, *args, **kwargs):
        raise RuntimeError("remote call failed")

    monkeypatch.setattr(PipelineOrchestrator, "_step_marketing", fails)
    run = pipeline_spend(db, 30_000.0)

    assert marketing_step(db, run).status == PipelineStepStatus.FAILED
    assert allocation(db) == (30_000.0, 0.0, 0.0)  # no se sabe qué llegó a hacer: sigue reservado


def test_a_retry_after_a_crash_does_not_reserve_the_same_spend_twice(db: Session, monkeypatch):
    authorise(db, 100_000.0)
    orchestrator = PipelineOrchestrator(db)
    run = orchestrator.enqueue_run(
        PipelineRequest(
            category="home", sale_price=50.0, destination_region="mexico", market="us", daily_budget=60_000.0
        )
    )

    def process_dies(self, *args, **kwargs):
        raise KeyboardInterrupt("the process died")

    original = PipelineOrchestrator._step_marketing
    monkeypatch.setattr(PipelineOrchestrator, "_step_marketing", process_dies)
    with pytest.raises(KeyboardInterrupt):
        Worker(name="worker-1").run_once(db)
    db.rollback()
    assert allocation(db) == (60_000.0, 0.0, 0.0)  # reservado y confirmado antes de caer

    from app.db.models.job import Job

    job = db.get(Job, run.job_id)
    job.lease_expires_at = datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=1)
    db.commit()
    monkeypatch.setattr(PipelineOrchestrator, "_step_marketing", original)
    drain(db)

    # El reintento no se compara contra su propia reserva, no la duplica, y al terminar la gasta.
    assert marketing_step(db, run).status == PipelineStepStatus.COMPLETED
    assert allocation(db) == (0.0, 60_000.0, 60_000.0)
    assert db.query(FinancialEvent).filter_by(type="RESERVE").count() == 1


def test_a_known_zero_cost_step_reserves_nothing(db: Session):
    authorise(db, 100_000.0)

    run = pipeline_spend(db, 0.0)

    assert marketing_step(db, run).status == PipelineStepStatus.COMPLETED
    assert db.query(FinancialEvent).count() == 0


# --- El presupuesto lo autoriza el propietario, no el código ------------------------


def test_the_code_no_longer_carries_a_hardcoded_spending_limit():
    import app.budgets.service as service

    assert not hasattr(service, "DEFAULT_BUDGET_HARD_LIMIT")


def test_the_cli_authorises_a_budget_with_an_audit_trail_and_refuses_an_invalid_one(db: Session):
    budget = cli.authorise_budget(db, hard_limit=500.0, soft_limit=400.0)

    assert (budget.hard_limit, budget.soft_limit) == (500.0, 400.0)
    entry = db.query(AuditLog).filter_by(action="budget.authorise").one()
    assert entry.actor.startswith("cli:")
    with pytest.raises(cli.BootstrapError):
        cli.authorise_budget(db, hard_limit=0.0)


def test_the_cli_refuses_to_change_the_budget_without_the_bootstrap_flag(monkeypatch):
    monkeypatch.delenv(cli.BOOTSTRAP_ENV, raising=False)

    with pytest.raises(cli.BootstrapError, match="the budget"):
        cli._require_bootstrap_flag("the budget")

    monkeypatch.setenv(cli.BOOTSTRAP_ENV, "1")
    cli._require_bootstrap_flag("the budget")
    assert os.environ[cli.BOOTSTRAP_ENV] == "1"
