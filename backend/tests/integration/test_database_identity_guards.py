"""Lo que la base de datos garantiza por sí misma (hardening pre-M44, ADR 0026).

El código daba por único un presupuesto, su saldo, el interruptor del pipeline, un movimiento del libro y una pregunta
pendiente, y lo protegía con locks y consultas previas. Eso falla cuando alguien se salta el servicio o cuando el
lock no cubre un camino; aquí se prueba que **la base de datos** rechaza el duplicado, y que lo legítimo sigue pasando.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy import event as sa_event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app import cli
from app.budgets.service import MAX_HARD_LIMIT, BudgetLedgerService
from app.core.errors import ValidationError
from app.db.base import Base
from app.db.models.budget import Budget, BudgetAllocation, FinancialEvent
from app.db.models.pipeline_kill_switch import PipelineKillSwitch
from app.db.models.pipeline_review import PipelineReview
from app.pipeline.service import PipelineOrchestrator

OWNER = "owner@amazona.local"


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


def refused(db: Session, *rows) -> None:
    """Las filas que la base tiene que rechazar, todas a la vez."""
    with pytest.raises(IntegrityError):
        db.add_all(rows)
        db.commit()
    db.rollback()


def accepted(db: Session, *rows) -> None:
    db.add_all(rows)
    db.commit()


# --- Presupuesto, saldo e interruptor ------------------------------------------------


def test_two_budgets_cannot_share_a_name(db: Session):
    accepted(db, Budget(name="main", hard_limit=100.0))

    refused(db, Budget(name="main", hard_limit=500.0))
    accepted(db, Budget(name="another", hard_limit=100.0))  # otro nombre, otro presupuesto


def test_a_budget_has_one_allocation(db: Session):
    budget = Budget(name="main", hard_limit=100.0)
    accepted(db, budget)
    accepted(db, BudgetAllocation(budget_id=budget.id))

    refused(db, BudgetAllocation(budget_id=budget.id))


def test_two_kill_switches_cannot_share_a_name(db: Session):
    accepted(db, PipelineKillSwitch(name="pipeline", enabled=True))

    refused(db, PipelineKillSwitch(name="pipeline", enabled=False))


# --- El libro: una reserva y una liquidación por referencia ------------------------------


def event(kind: str, reference: str | None, budget_id: str | None = None, amount: float = 10.0) -> FinancialEvent:
    return FinancialEvent(budget_id=budget_id, type=kind, amount=amount, reference=reference)


def test_a_reference_is_reserved_once(db: Session):
    accepted(db, event("RESERVE", "ref-1"))

    refused(db, event("RESERVE", "ref-1"))


def test_a_reservation_can_be_settled_once_either_way(db: Session):
    accepted(db, event("RESERVE", "ref-1"), event("COMMIT", "ref-1"))

    refused(db, event("COMMIT", "ref-1"))
    refused(db, event("RELEASE", "ref-1"))  # ni comprometida y luego liberada: el dinero contaría dos veces


def test_committed_then_released_is_refused_and_released_then_committed_too(db: Session):
    accepted(db, event("RESERVE", "ref-a"), event("RELEASE", "ref-a"))

    refused(db, event("COMMIT", "ref-a"))


def test_different_references_and_unreferenced_events_do_not_collide(db: Session):
    accepted(
        db,
        event("RESERVE", "ref-1"),
        event("RESERVE", "ref-2"),
        event("COMMIT", "ref-1"),
        event("RELEASE", "ref-2"),
        event("RESERVE", None),
        event("RESERVE", None),  # sin referencia no hay identidad que repetir
    )

    assert db.query(FinancialEvent).count() == 6


# --- Preguntas pendientes ---------------------------------------------------------------


def review(run: str, *, kind: str = "ACTION_GATE", step: str | None = "ecommerce", status: str = "PENDING"):
    return PipelineReview(
        pipeline_run_id=run, kind=kind, step=step, reasons=["needs approval"], status=status, correlation_id="c"
    )


def test_a_step_has_at_most_one_pending_gate(db: Session):
    accepted(db, review("run-1"))

    refused(db, review("run-1"))


def test_a_resolved_gate_does_not_block_a_new_pending_one(db: Session):
    accepted(db, review("run-1", status="CONSUMED"), review("run-1", status="REJECTED"), review("run-1"))

    assert db.query(PipelineReview).count() == 3


def test_gates_of_different_steps_and_runs_are_independent(db: Session):
    accepted(db, review("run-1"), review("run-1", step="marketplace"), review("run-2"))

    assert db.query(PipelineReview).count() == 3


def test_a_run_has_one_pending_post_hoc_review_and_it_does_not_collide_with_a_gate(db: Session):
    accepted(db, review("run-1", kind="POST_HOC", step=None), review("run-1"))

    refused(db, review("run-1", kind="POST_HOC", step=None))
    accepted(db, review("run-2", kind="POST_HOC", step=None))


def test_an_integrity_error_that_is_not_a_duplicate_question_is_not_swallowed():
    """Una clave ajena rota no es «otro ejecutor abrió la misma»: no hay pendiente que devolver y se relanza."""
    engine = create_engine("sqlite+pysqlite:///:memory:")

    @sa_event.listens_for(engine, "connect")
    def _foreign_keys_on(dbapi_connection, _):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)

    with Session(engine) as session:
        with pytest.raises(IntegrityError):
            PipelineOrchestrator(session)._open_review(review("run-that-does-not-exist"))
    engine.dispose()


def test_opening_the_same_pending_question_twice_returns_the_one_that_exists(db: Session):
    orchestrator = PipelineOrchestrator(db)

    first = orchestrator._open_review(review("run-1"))
    second = orchestrator._open_review(review("run-1"))
    db.commit()

    assert first is None  # se abrió una nueva
    assert second is not None and second.status == "PENDING"  # la otra ya existía y es la que se devuelve
    assert db.query(PipelineReview).count() == 1


# --- El saldo se crea una vez y el techo es un número de verdad -----------------------------


def test_the_first_reservation_creates_the_allocation_once(db: Session):
    accepted(db, Budget(name="orchestrator-default", hard_limit=1000.0))  # presupuesto sin saldo (datos antiguos)
    ledger = BudgetLedgerService(db)

    assert ledger.reserve(amount=10.0, reference="r-1")
    assert ledger.reserve(amount=10.0, reference="r-2")
    db.commit()

    assert db.query(BudgetAllocation).count() == 1
    assert float(db.query(BudgetAllocation).one().reserved) == 20.0


@pytest.mark.parametrize(
    "bad",
    [float("inf"), float("-inf"), float("nan"), 0.0, -1.0, 0.001, 10.005, float(MAX_HARD_LIMIT) + 1, 1e30],
)
def test_a_hard_limit_must_be_finite_positive_in_cents_and_within_the_maximum(db: Session, bad: float):
    with pytest.raises(ValidationError):
        BudgetLedgerService(db).authorise_budget(hard_limit=bad, actor=OWNER)

    assert db.query(Budget).count() == 0  # no queda nada a medias


@pytest.mark.parametrize("good", [0.01, 99.99, 100_000.0, float(MAX_HARD_LIMIT)])
def test_a_valid_hard_limit_is_accepted(db: Session, good: float):
    budget = BudgetLedgerService(db).authorise_budget(hard_limit=good, actor=OWNER)

    assert float(budget.hard_limit) == pytest.approx(good)


def test_a_soft_limit_must_also_be_a_finite_amount_in_cents(db: Session):
    ledger = BudgetLedgerService(db)

    with pytest.raises(ValidationError):
        ledger.authorise_budget(hard_limit=100.0, soft_limit=float("nan"), actor=OWNER)
    with pytest.raises(ValidationError):
        ledger.authorise_budget(hard_limit=100.0, soft_limit=50.005, actor=OWNER)
    assert db.query(Budget).count() == 0


def test_the_cli_refuses_an_infinite_limit_with_a_readable_error(db: Session):
    with pytest.raises(cli.BootstrapError, match="finite"):
        cli.authorise_budget(db, hard_limit=float("inf"))


def test_authorising_the_same_budget_twice_leaves_one_budget_and_one_allocation(db: Session):
    ledger = BudgetLedgerService(db)

    ledger.authorise_budget(hard_limit=500.0, actor=OWNER)
    ledger.authorise_budget(hard_limit=500.0, actor=OWNER)
    ledger.authorise_budget(hard_limit=800.0, actor=OWNER)

    assert db.query(Budget).count() == 1
    assert db.query(BudgetAllocation).count() == 1
    assert float(db.query(Budget).one().hard_limit) == 800.0
