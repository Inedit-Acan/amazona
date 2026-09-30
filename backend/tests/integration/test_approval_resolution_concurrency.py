"""La carrera de las aprobaciones, sobre PostgreSQL de verdad (hardening pre-M44, D10).

SQLite serializa todas las transacciones y nunca reproduce esta carrera; aquí cada
hilo tiene su propia sesión y su propia transacción, en una base efímera. Criterio, con
N peticiones simultáneas sobre la misma aprobación:

- exactamente una cambia `PENDING` -> `APPROVED` o `REJECTED`;
- exactamente una produce efectos: un solo `COMMIT` o un solo `RELEASE`, nunca los dos;
- las demás reciben el «ya resuelta» de siempre (`ApprovalNotPendingError`);
- el libro no pierde ningún importe (`committed` es exactamente la suma de lo aprobado).

Antes de D10: 8 `approve` simultáneos dejaban hasta 8 `COMMIT`, y un `approve` con un
`reject` dejaban `COMMIT` y `RELEASE` a la vez.
"""

import collections
import threading
import time

from pg_test_support import ephemeral_postgres
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api import approvals as approvals_api
from app.api import pipeline as pipeline_api
from app.auth.actor import Actor, ActorSource, RoleName
from app.budgets.service import BudgetLedgerService
from app.core.config import Settings
from app.db.models.approval import Approval
from app.db.models.audit import AuditLog
from app.db.models.decision import Decision
from app.db.models.objective import Objective
from app.db.models.pipeline_review import PipelineReview
from app.db.models.project import Project
from app.pipeline.schemas import REVIEW_KIND_ACTION_GATE, REVIEW_KIND_POST_HOC, PipelineRunStatus
from app.pipeline.service import PipelineOrchestrator, PipelineRequest

IDENTITY = Actor(subject="owner@amazona.local", role=RoleName.OWNER, source=ActorSource.DECLARED)
SETTINGS = Settings(_env_file=None)
REQUEST = PipelineRequest(category="home", sale_price=50.0, destination_region="mexico", market="us")


def seed_approval(engine, *, amount: float = 100.0) -> str:
    """Una aprobación pendiente con su reserva en el libro, como la deja el orquestador."""
    with Session(engine) as db:
        objective = Objective(title="t", created_by="t@t", context={})
        db.add(objective)
        db.flush()
        project = Project(objective_id=objective.id, name="p")
        db.add(project)
        db.flush()
        decision = Decision(project_id=project.id, status="HUMAN_APPROVAL", correlation_id="c-1")
        db.add(decision)
        db.flush()
        approval = Approval(
            decision_id=decision.id, action="launch", amount=amount, status="PENDING", correlation_id="c-1"
        )
        db.add(approval)
        db.flush()
        ledger = BudgetLedgerService(db)
        if ledger.find_budget() is None:
            ledger.authorise_budget(hard_limit=1_000_000.0, actor="owner@amazona.local")
        assert ledger.reserve(amount=amount, reference=f"approval:{approval.id}")
        db.commit()
        return approval.id


def race(engine, workers: list, *, timeout: float = 60.0) -> list[str]:
    """Lanza todas las peticiones a la vez y devuelve qué le pasó a cada una."""
    barrier = threading.Barrier(len(workers))
    outcomes: list[str] = []
    lock = threading.Lock()

    def run(work) -> None:
        session = Session(engine)
        try:
            barrier.wait(timeout=10)
            work(session)
            result = "ok"
        except Exception as exc:  # noqa: BLE001 - lo que le pasó a esa petición es el dato
            result = type(exc).__name__
        finally:
            session.close()
        with lock:
            outcomes.append(result)

    threads = [threading.Thread(target=run, args=(work,)) for work in workers]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=timeout)
    return outcomes


def resolve_approval(approval_id: str, verb: str):
    return lambda session: approvals_api._resolve(approval_id, verb, session, IDENTITY, None, SETTINGS)


def ledger_events(engine, reference: str) -> dict[str, int]:
    with engine.connect() as connection:
        rows = connection.execute(
            text("SELECT type, count(*) FROM financial_events WHERE reference = :r GROUP BY type"), {"r": reference}
        )
        return dict(rows.all())


def allocation(engine) -> tuple[float, float, float]:
    with engine.connect() as connection:
        row = connection.execute(text("SELECT reserved, committed, spent FROM budget_allocations")).one()
        return tuple(float(value) for value in row)


def status_of(engine, table: str, row_id: str) -> str:
    with engine.connect() as connection:
        return connection.execute(text(f"SELECT status FROM {table} WHERE id = :i"), {"i": row_id}).scalar()


def audit_count(engine, action: str, resource: str) -> int:
    with Session(engine) as db:
        return db.query(AuditLog).filter_by(action=action, resource=resource).count()


# --- Aprobaciones -------------------------------------------------------------------


def test_eight_simultaneous_approvals_have_exactly_one_winner():
    with ephemeral_postgres() as engine:
        for _ in range(5):
            approval_id = seed_approval(engine)
            before = allocation(engine)

            outcomes = race(engine, [resolve_approval(approval_id, "APPROVED")] * 8)

            assert collections.Counter(outcomes) == {"ok": 1, "ApprovalNotPendingError": 7}
            assert status_of(engine, "approvals", approval_id) == "APPROVED"
            assert ledger_events(engine, f"approval:{approval_id}") == {"RESERVE": 1, "COMMIT": 1}
            assert audit_count(engine, "approval.approve", f"approval:{approval_id}") == 1
            after = allocation(engine)
            assert after[1] - before[1] == 100  # committed: ni un COMMIT de más
            assert after[0] - before[0] == -100  # reserved: liberado una sola vez


def test_an_approve_and_a_reject_at_the_same_time_leave_one_consistent_outcome():
    with ephemeral_postgres() as engine:
        for _ in range(5):
            approval_id = seed_approval(engine)

            outcomes = race(
                engine, [resolve_approval(approval_id, "APPROVED"), resolve_approval(approval_id, "REJECTED")]
            )

            assert collections.Counter(outcomes) == {"ok": 1, "ApprovalNotPendingError": 1}
            final = status_of(engine, "approvals", approval_id)
            events = ledger_events(engine, f"approval:{approval_id}")
            assert final in {"APPROVED", "REJECTED"}
            # Exactamente un efecto, y el que corresponde al ganador: nunca COMMIT y RELEASE juntos.
            assert events == {"RESERVE": 1, "COMMIT" if final == "APPROVED" else "RELEASE": 1}


def test_many_simultaneous_attempts_on_different_approvals_lose_no_amount_in_the_ledger():
    with ephemeral_postgres() as engine:
        ids = [seed_approval(engine, amount=100.0) for _ in range(12)]
        before = allocation(engine)

        outcomes = race(engine, [resolve_approval(approval_id, "APPROVED") for approval_id in ids])

        assert collections.Counter(outcomes) == {"ok": 12}
        after = allocation(engine)
        assert after[1] - before[1] == 1200  # committed: la suma exacta, sin actualizaciones perdidas
        assert after[2] - before[2] == 1200  # spent
        assert after[0] - before[0] == -1200


def test_a_ledger_write_waits_for_a_concurrent_one_instead_of_overwriting_it():
    """Determinista: A ha movido el saldo y no ha confirmado; B llega mientras tanto.

    Si B lee el total, suma en Python y escribe el resultado, cuando A confirma B pisa
    su importe y el libro pierde 100. Con aritmética de la base de datos, B espera al
    bloqueo de la fila y suma sobre lo que A dejó."""
    with ephemeral_postgres() as engine:
        with Session(engine) as seed:
            ledger = BudgetLedgerService(seed)
            ledger.authorise_budget(hard_limit=1_000_000.0, actor="owner@amazona.local")
            assert ledger.reserve(amount=1000.0, reference="seed")
            seed.commit()

        a = Session(engine)
        BudgetLedgerService(a).record_commit(amount=100.0, reference="A")  # ejecutado, sin confirmar

        def write_b() -> None:
            with Session(engine) as b:
                BudgetLedgerService(b).record_commit(amount=200.0, reference="B")
                b.commit()

        thread = threading.Thread(target=write_b)
        thread.start()
        time.sleep(1.0)  # B ya ha leído (código antiguo) o ya espera al bloqueo (código nuevo)
        a.commit()
        a.close()
        thread.join(timeout=30)

        assert allocation(engine) == (700.0, 300.0, 300.0)


# --- Revisiones del pipeline --------------------------------------------------------


def seed_review(engine, *, kind: str) -> tuple[str, str]:
    """Devuelve el id de la revisión y el `correlation_id` de su ejecución."""
    with Session(engine) as db:
        run = PipelineOrchestrator(db).enqueue_run(REQUEST)
        if kind == REVIEW_KIND_ACTION_GATE:
            run.status = PipelineRunStatus.WAITING_APPROVAL
            run.needs_review = True
        review = PipelineReview(
            pipeline_run_id=run.id,
            kind=kind,
            step="ecommerce" if kind == REVIEW_KIND_ACTION_GATE else None,
            action="publish_product" if kind == REVIEW_KIND_ACTION_GATE else None,
            reasons=["test"],
            status="PENDING",
            correlation_id=run.correlation_id,
        )
        db.add(review)
        db.commit()
        return review.id, run.correlation_id


def resolve_review(review_id: str, verb: str):
    return lambda session: pipeline_api._resolve_review(review_id, verb, session, IDENTITY, None, SETTINGS)


def test_a_post_hoc_review_has_exactly_one_winner():
    with ephemeral_postgres() as engine:
        for _ in range(12):  # la ventana de esta carrera es estrecha: una sola prueba no la atraparía
            review_id, _ = seed_review(engine, kind=REVIEW_KIND_POST_HOC)
            workers = [resolve_review(review_id, "APPROVED")] * 8 + [resolve_review(review_id, "REJECTED")] * 8

            outcomes = race(engine, workers)

            assert collections.Counter(outcomes) == {"ok": 1, "PipelineReviewNotPendingError": 15}
            final = status_of(engine, "pipeline_reviews", review_id)
            assert final in {"APPROVED", "REJECTED"}
            approve = audit_count(engine, "pipeline_review.approve", f"pipeline_review:{review_id}")
            reject = audit_count(engine, "pipeline_review.reject", f"pipeline_review:{review_id}")
            assert (approve, reject) == ((1, 0) if final == "APPROVED" else (0, 1))


def test_an_action_gate_review_resumes_the_run_exactly_once():
    with ephemeral_postgres() as engine:
        for _ in range(3):
            review_id, correlation_id = seed_review(engine, kind=REVIEW_KIND_ACTION_GATE)

            outcomes = race(engine, [resolve_review(review_id, "APPROVED")] * 8)

            assert collections.Counter(outcomes) == {"ok": 1, "PipelineReviewNotPendingError": 7}
            assert status_of(engine, "pipeline_reviews", review_id) == "APPROVED"
            with Session(engine) as db:
                resumes = db.query(AuditLog).filter_by(action="pipeline.resume", resource=f"pipeline:{correlation_id}")
                assert resumes.count() == 1
