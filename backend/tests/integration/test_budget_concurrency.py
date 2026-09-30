"""El presupuesto no se sobrepasa aunque las peticiones lleguen a la vez (hardening pre-M44, D14).

SQLite serializa todas las transacciones y nunca reproduce estas carreras; aquí cada hilo tiene su
propia sesión, en una base PostgreSQL efímera. Invariante: con un techo de 100 000, dos solicitudes
de 60 000 no caben juntas, **vengan por donde vengan**: exactamente una se reserva, y `reservado +
comprometido` nunca supera el techo.

Antes del arreglo, el CEO aprobaba cada solicitud contra un saldo en memoria y el gate evaluaba y
reservaba en dos pasos: con dos peticiones a la vez, las dos veían el mismo saldo libre.
"""

import collections
import threading

from pg_test_support import ephemeral_postgres
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.budgets.service import BudgetLedgerService
from app.ceo.orchestrator import CEOOrchestrator
from app.ceo.schemas import DecisionStatus
from app.core.ids import new_id
from app.db.models.budget import Budget
from app.db.models.objective import Objective
from app.db.models.pipeline_step import PipelineStep
from app.pipeline.schemas import PipelineStepStatus
from app.pipeline.service import PipelineOrchestrator, PipelineRequest

OWNER = "owner@amazona.local"
CONTEXT = {
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


def authorise(engine, hard_limit: float = 100_000.0) -> None:
    with Session(engine) as db:
        BudgetLedgerService(db).authorise_budget(hard_limit=hard_limit, actor=OWNER)


def run_together(engine, jobs: list) -> list:
    """Lanza todas las tareas a la vez, cada una con su sesión, y devuelve lo que devolvió cada una."""
    barrier = threading.Barrier(len(jobs))
    results: list = []
    lock = threading.Lock()

    def worker(job) -> None:
        with Session(engine) as session:
            try:
                barrier.wait(timeout=10)
                outcome = job(session)
            except Exception as exc:  # noqa: BLE001 - lo que le pasó a cada tarea es el dato
                outcome = f"error:{type(exc).__name__}:{exc}"
        with lock:
            results.append(outcome)

    threads = [threading.Thread(target=worker, args=(job,)) for job in jobs]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)
    return results


def ledger_row(engine) -> tuple[float, float]:
    with engine.connect() as connection:
        row = connection.execute(text("SELECT reserved, committed FROM budget_allocations")).one()
        return float(row[0]), float(row[1])


def reserve_job(amount: float, reference: str):
    def job(session: Session) -> bool:
        ok = BudgetLedgerService(session).reserve(amount=amount, reference=reference)
        session.commit()
        return ok

    return job


# --- El libro ------------------------------------------------------------------------


def test_simultaneous_authorisations_leave_a_single_budget():
    with ephemeral_postgres() as engine:

        def authorise_job(session: Session):
            BudgetLedgerService(session).authorise_budget(hard_limit=500.0, actor=OWNER)

        results = run_together(engine, [authorise_job] * 8)

        assert [r for r in results if isinstance(r, str)] == []
        with Session(engine) as db:
            assert db.query(Budget).count() == 1


def test_of_eight_simultaneous_reservations_of_60000_exactly_one_fits_in_100000():
    with ephemeral_postgres() as engine:
        authorise(engine)
        for trial in range(5):
            with Session(engine) as db:  # cada prueba parte de cero
                db.execute(text("UPDATE budget_allocations SET reserved = 0, committed = 0, spent = 0"))
                db.execute(text("DELETE FROM financial_events"))
                db.commit()

            results = run_together(engine, [reserve_job(60_000.0, f"r{trial}-{i}") for i in range(8)])

            assert collections.Counter(results) == {True: 1, False: 7}
            assert ledger_row(engine) == (60_000.0, 0.0)


def test_simultaneous_reservations_fill_the_limit_exactly_and_never_exceed_it():
    with ephemeral_postgres() as engine:
        authorise(engine)

        results = run_together(engine, [reserve_job(10_000.0, f"r-{i}") for i in range(16)])

        assert collections.Counter(results) == {True: 10, False: 6}
        assert ledger_row(engine) == (100_000.0, 0.0)


def test_simultaneous_commits_and_releases_lose_no_amount():
    with ephemeral_postgres() as engine:
        authorise(engine, 1_000_000.0)
        with Session(engine) as db:
            ledger = BudgetLedgerService(db)
            for i in range(10):
                assert ledger.reserve(amount=100.0, reference=f"r-{i}")
            db.commit()

        def settle(i: int):
            def job(session: Session):
                ledger = BudgetLedgerService(session)
                (ledger.record_commit if i % 2 == 0 else ledger.record_release)(amount=100.0, reference=f"r-{i}")
                session.commit()

            return job

        run_together(engine, [settle(i) for i in range(10)])

        assert ledger_row(engine) == (0.0, 500.0)  # cinco comprometidas, cinco liberadas


# --- Las tres vías a la vez -----------------------------------------------------------


def seed_objectives(engine, count: int) -> list[str]:
    with Session(engine) as db:
        ids = []
        for _ in range(count):
            objective = Objective(id=new_id(), title="spend", created_by=OWNER, context=CONTEXT)
            db.add(objective)
            ids.append(objective.id)
        db.commit()
        return ids


def seed_pipeline_runs(engine, count: int) -> list[str]:
    request = PipelineRequest(
        category="home", sale_price=50.0, destination_region="mexico", market="us", daily_budget=60_000.0
    )
    with Session(engine) as db:
        return [PipelineOrchestrator(db).enqueue_run(request).id for _ in range(count)]


def test_ceo_and_pipeline_spending_at_the_same_time_cannot_both_fit_60000_in_100000():
    with ephemeral_postgres() as engine:
        for _ in range(3):
            authorise(engine)
            with Session(engine) as db:
                db.execute(text("UPDATE budget_allocations SET reserved = 0, committed = 0, spent = 0"))
                db.execute(text("DELETE FROM financial_events"))
                db.commit()
            objective_ids = seed_objectives(engine, 3)
            run_ids = seed_pipeline_runs(engine, 3)

            def ceo(objective_id: str):
                def job(session: Session) -> str:
                    decision = CEOOrchestrator(session).run_objective(objective_id)
                    session.commit()
                    return f"ceo:{decision.status}"

                return job

            def pipeline(run_id: str):
                def job(session: Session) -> str:
                    PipelineOrchestrator(session).execute_run(run_id)
                    step = session.query(PipelineStep).filter_by(pipeline_run_id=run_id, name="marketing").one()
                    return f"pipeline:{step.status}"

                return job

            results = run_together(engine, [ceo(i) for i in objective_ids] + [pipeline(i) for i in run_ids])

            assert [r for r in results if r.startswith("error")] == []
            wins = [
                r
                for r in results
                if r in (f"ceo:{DecisionStatus.HUMAN_APPROVAL.value}", f"pipeline:{PipelineStepStatus.COMPLETED}")
            ]
            assert len(wins) == 1, results  # exactamente una de las seis solicitudes cabe
            reserved, committed = ledger_row(engine)
            assert reserved + committed == 60_000.0
            with engine.connect() as connection:
                reserves = connection.execute(text("SELECT count(*) FROM financial_events WHERE type = 'RESERVE'"))
                assert reserves.scalar() == 1
