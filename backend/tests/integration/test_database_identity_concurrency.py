"""Las garantías de identidad frente a peticiones a la vez, en PostgreSQL (hardening pre-M44, ADR 0026).

SQLite serializa las transacciones y nunca reproduce estas carreras; aquí cada hilo tiene su propia sesión y arrancan
juntos tras una barrera. Antes del arreglo, 30 primeras reservas simultáneas dejaron entre 2 y 4 filas de saldo en 3 de
12 pruebas (medido); ahora la creación se serializa y, además, la base solo admite una.
"""

import threading

from pg_test_support import ephemeral_postgres
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.budgets.service import BudgetLedgerService
from app.db.models.budget import Budget
from app.db.models.pipeline_review import PipelineReview
from app.pipeline.service import PipelineOrchestrator, PipelineRequest

OWNER = "owner@amazona.local"


def run_together(engine, jobs: list) -> list:
    barrier = threading.Barrier(len(jobs))
    results: list = []
    lock = threading.Lock()

    def worker(job) -> None:
        with Session(engine) as session:
            try:
                barrier.wait(timeout=10)
                outcome = job(session)
            except Exception as exc:  # noqa: BLE001 - lo que le pasó a cada tarea es el dato
                outcome = exc
        with lock:
            results.append(outcome)

    threads = [threading.Thread(target=worker, args=(job,)) for job in jobs]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)
    return results


def scalar(engine, sql: str):
    with engine.connect() as connection:
        return connection.execute(text(sql)).scalar_one()


def test_thirty_first_reservations_create_exactly_one_allocation():
    for trial in range(6):
        with ephemeral_postgres() as engine:
            with Session(engine) as db:
                db.add(Budget(name="orchestrator-default", hard_limit=1000.0))  # presupuesto sin saldo (datos antiguos)
                db.commit()

            def reserve(index: int):
                def job(session: Session):
                    ok = BudgetLedgerService(session).reserve(amount=10.0, reference=f"r-{trial}-{index}")
                    session.commit()
                    return ok

                return job

            results = run_together(engine, [reserve(i) for i in range(30)])

            assert [r for r in results if isinstance(r, Exception)] == []
            assert results.count(True) == 30
            assert scalar(engine, "select count(*) from budget_allocations") == 1
            assert float(scalar(engine, "select reserved from budget_allocations")) == 300.0


def test_simultaneous_authorisations_leave_one_budget_and_one_allocation():
    with ephemeral_postgres() as engine:

        def authorise(session: Session):
            BudgetLedgerService(session).authorise_budget(hard_limit=500.0, actor=OWNER)

        results = run_together(engine, [authorise] * 12)

        assert [r for r in results if isinstance(r, Exception)] == []
        assert scalar(engine, "select count(*) from budgets") == 1
        assert scalar(engine, "select count(*) from budget_allocations") == 1


def test_twelve_executors_opening_the_same_question_leave_one_pending_review():
    with ephemeral_postgres() as engine:
        with Session(engine) as seed:
            run = PipelineOrchestrator(seed).enqueue_run(
                PipelineRequest(category="home", sale_price=0.5, destination_region="mexico", market="us")
            )
            run_id = run.id

        def open_question(session: Session):
            review = PipelineReview(
                pipeline_run_id=run_id,
                kind="ACTION_GATE",
                step="ecommerce",
                action="publish_product",
                reasons=["needs approval"],
                status="PENDING",
                correlation_id="c",
            )
            existing = PipelineOrchestrator(session)._open_review(review)
            session.commit()
            return existing

        results = run_together(engine, [open_question] * 12)

        assert [r for r in results if isinstance(r, Exception)] == []
        assert scalar(engine, "select count(*) from pipeline_reviews where status = 'PENDING'") == 1
        assert sum(1 for r in results if r is None) == 1  # una abrió la pregunta; las otras recibieron la suya


def test_eight_simultaneous_settlements_of_one_reservation_move_the_money_once():
    """El respaldo de la base de datos: aunque algo se saltara los guardias del servicio, una reserva no se liquida dos
    veces. Las demás liquidaciones fallan y su aritmética se deshace con la transacción."""
    with ephemeral_postgres() as engine:
        with Session(engine) as db:
            ledger = BudgetLedgerService(db)
            ledger.authorise_budget(hard_limit=1000.0, actor=OWNER)
            assert ledger.reserve(amount=100.0, reference="approval:1")
            db.commit()

        def settle(session: Session):
            BudgetLedgerService(session).record_commit(amount=100.0, reference="approval:1")
            session.commit()
            return "settled"

        results = run_together(engine, [settle] * 8)

        assert results.count("settled") == 1
        assert all(isinstance(r, IntegrityError) for r in results if r != "settled")
        assert scalar(engine, "select count(*) from financial_events where type = 'COMMIT'") == 1
        assert float(scalar(engine, "select committed from budget_allocations")) == 100.0
        assert float(scalar(engine, "select reserved from budget_allocations")) == 0.0
