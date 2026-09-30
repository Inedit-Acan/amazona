"""Una autorización humana se usa una sola vez (hardening pre-M44, D10b).

Antes, la revisión `APPROVED` de un paso con efecto seguía valiendo para siempre:
`resume_run(from_step=...)`, el reintento de un worker que cayó y `_reset_step`
volvían a ejecutar el paso sin preguntar. Medido: una aprobación y dos
`resume_run(from_step="ecommerce")` dejaban tres tiendas creadas con una sola revisión.

Ahora `APPROVED` es «existe y no se ha usado» y `CONSUMED` es «ya se usó»; el paso
consume la autorización **en la misma transacción que arranca** (un compare-and-set),
y una autorización consumida ya no vale para nada: el paso vuelve a preguntar.

Lo que pasa si algo se interrumpe:

- antes del commit de arranque no se ha consumido nada, y el reintento la usa;
- después, la autorización ya está gastada y el paso queda `RUNNING` con su intento sin
  terminar: el reintento pide una nueva y dice que el resultado anterior es desconocido;
- un paso que falla tras consumirla también pide una nueva: se ignora qué llegó a hacer.
"""

import collections
import datetime
import threading

import pytest
from pg_test_support import ephemeral_postgres
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.api import pipeline as pipeline_api
from app.auth.actor import Actor, ActorSource, RoleName
from app.core.config import Settings
from app.core.errors import PipelineReviewNotPendingError, PipelineRunStateError
from app.db.base import Base
from app.db.models.audit import AuditLog
from app.db.models.job import Job
from app.db.models.pipeline_review import PipelineReview
from app.db.models.pipeline_run import PipelineRun
from app.db.models.pipeline_step import PipelineStep, PipelineStepAttempt
from app.db.models.storefront import Storefront
from app.gates.action_gate import HumanApproval
from app.jobs.worker import Worker
from app.pipeline.kill_switch import PipelineKillSwitchService
from app.pipeline.schemas import REVIEW_KIND_ACTION_GATE, PipelineRunStatus, PipelineStepStatus
from app.pipeline.service import PipelineOrchestrator, PipelineRequest

#: Economía NO_GO de verdad: el precio no cubre ni el coste, así que cada paso con efecto pregunta.
REQUEST = PipelineRequest(category="home", sale_price=0.5, destination_region="mexico", market="us")
IDENTITY = Actor(subject="owner@amazona.local", role=RoleName.OWNER, source=ActorSource.DECLARED)
SETTINGS = Settings(_env_file=None)


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


def drain(db: Session, rounds: int = 12) -> None:
    worker = Worker(name="test-worker")
    for _ in range(rounds):
        if worker.run_once(db) is None:
            break


def reviews(db: Session, step: str = "ecommerce") -> list[PipelineReview]:
    return (
        db.query(PipelineReview)
        .filter_by(kind=REVIEW_KIND_ACTION_GATE, step=step)
        .order_by(PipelineReview.created_at, PipelineReview.id)
        .all()
    )


def approve(db: Session, review: PipelineReview) -> None:
    """Lo que hace la API al aprobar una puerta: marcar la revisión y reanudar."""
    review.status = "APPROVED"
    review.resolved_at = datetime.datetime.now(datetime.UTC)
    review.resolved_by = "owner@amazona.local"
    db.flush()
    PipelineOrchestrator(db).resume_run(db.get(PipelineRun, review.pipeline_run_id), actor="owner@amazona.local")
    db.commit()


def step_of(db: Session, run: PipelineRun, name: str = "ecommerce") -> PipelineStep:
    return db.query(PipelineStep).filter_by(pipeline_run_id=run.id, name=name).one()


def waiting_run(db: Session) -> PipelineRun:
    """Una ejecución parada en la puerta de `ecommerce`."""
    run = PipelineOrchestrator(db).enqueue_run(REQUEST)
    drain(db)
    assert reviews(db)[0].status == "PENDING"
    return run


def storefronts(db: Session) -> int:
    return db.query(Storefront).count()


# --- Se consume al empezar ----------------------------------------------------------


def test_an_approval_is_consumed_when_the_step_starts_and_the_step_runs_once(db: Session):
    run = waiting_run(db)
    review = reviews(db)[0]

    approve(db, review)
    drain(db)

    db.refresh(review)
    assert review.status == "CONSUMED"
    assert step_of(db, run).status == PipelineStepStatus.COMPLETED
    assert storefronts(db) == 1
    consumed = db.query(AuditLog).filter_by(action="pipeline_review.consume", resource=f"pipeline_review:{review.id}")
    assert consumed.count() == 1
    detail = consumed.one().after
    assert (detail["status"], detail["step"]) == ("CONSUMED", "ecommerce")
    assert detail["job_id"] == run.job_id


def test_a_consumed_review_no_longer_counts_as_a_human_authorisation(db: Session):
    run = waiting_run(db)
    review = reviews(db)[0]
    orchestrator = PipelineOrchestrator(db)

    assert orchestrator._human_approval(review) is HumanApproval.NONE  # PENDING
    review.status = "APPROVED"
    assert orchestrator._human_approval(review) is HumanApproval.GRANTED
    review.status = "CONSUMED"
    assert orchestrator._human_approval(review) is HumanApproval.NONE
    review.status = "REJECTED"
    assert orchestrator._human_approval(review) is HumanApproval.REJECTED
    assert run is not None


def test_resolving_a_consumed_review_is_refused(db: Session):
    run = waiting_run(db)
    review = reviews(db)[0]
    approve(db, review)
    drain(db)

    with pytest.raises(PipelineReviewNotPendingError, match="status=CONSUMED"):
        pipeline_api._resolve_review(review.id, "APPROVED", db, IDENTITY, None, SETTINGS)

    assert storefronts(db) == 1
    assert run is not None


# --- No se reutiliza ----------------------------------------------------------------


def test_redoing_the_step_with_from_step_asks_again_instead_of_reusing_the_approval(db: Session):
    run = waiting_run(db)
    approve(db, reviews(db)[0])
    drain(db)
    assert storefronts(db) == 1

    for attempt in (1, 2):
        PipelineOrchestrator(db).resume_run(
            db.get(PipelineRun, run.id), actor="owner@amazona.local", from_step="ecommerce"
        )
        drain(db)

        db.refresh(run)
        assert run.status == PipelineRunStatus.WAITING_APPROVAL, attempt
        assert storefronts(db) == 1, attempt  # no se ejecutó otra vez
        assert step_of(db, run).status == PipelineStepStatus.WAITING_APPROVAL

    pending = [review for review in reviews(db) if review.status == "PENDING"]
    assert len(pending) == 1  # una sola pregunta abierta, no una por intento
    assert any("already used" in reason for reason in pending[0].reasons)


def test_a_new_approval_authorises_exactly_one_more_execution(db: Session):
    run = waiting_run(db)
    approve(db, reviews(db)[0])
    drain(db)
    PipelineOrchestrator(db).resume_run(db.get(PipelineRun, run.id), actor="owner@amazona.local", from_step="ecommerce")
    drain(db)

    approve(db, [review for review in reviews(db) if review.status == "PENDING"][0])
    drain(db)

    assert storefronts(db) == 2
    assert [review.status for review in reviews(db)] == ["CONSUMED", "CONSUMED"]


def test_a_later_step_still_needs_its_own_approval(db: Session):
    run = waiting_run(db)
    approve(db, reviews(db)[0])
    drain(db)

    db.refresh(run)
    assert run.status == PipelineRunStatus.WAITING_APPROVAL
    assert [review.step for review in db.query(PipelineReview).filter_by(kind=REVIEW_KIND_ACTION_GATE)] == [
        "ecommerce",
        "marketplace",
    ]
    assert reviews(db, "marketplace")[0].status == "PENDING"


# --- Si algo se interrumpe ----------------------------------------------------------


def test_a_worker_that_dies_mid_step_does_not_leave_a_reusable_authorisation(db: Session, monkeypatch):
    run = waiting_run(db)
    review = reviews(db)[0]
    approve(db, review)

    def process_dies(self, *args, **kwargs):
        raise KeyboardInterrupt("the process died")  # no es un Exception: el pipeline no lo captura

    original = PipelineOrchestrator._step_ecommerce
    monkeypatch.setattr(PipelineOrchestrator, "_step_ecommerce", process_dies)
    with pytest.raises(KeyboardInterrupt):
        Worker(name="worker-1").run_once(db)
    db.rollback()  # lo que no se confirmó, con el proceso, desaparece

    # Quedó confirmado: autorización gastada, paso en marcha, intento sin terminar.
    db.refresh(review)
    assert review.status == "CONSUMED"
    assert step_of(db, run).status == PipelineStepStatus.RUNNING
    attempt = db.query(PipelineStepAttempt).filter_by(pipeline_step_id=step_of(db, run).id).one()
    assert attempt.status == PipelineStepStatus.RUNNING

    # El arriendo vence y otro worker reintenta con el código ya sano.
    job = db.get(Job, run.job_id)
    job.lease_expires_at = datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=1)
    db.commit()
    monkeypatch.setattr(PipelineOrchestrator, "_step_ecommerce", original)
    drain(db)

    db.refresh(run)
    assert run.status == PipelineRunStatus.WAITING_APPROVAL  # no ejecutó: pregunta
    assert storefronts(db) == 0
    pending = [item for item in reviews(db) if item.status == "PENDING"]
    assert len(pending) == 1
    assert any("outcome is unknown" in reason for reason in pending[0].reasons)


def test_a_lost_lease_mid_step_resets_the_step_but_not_the_authorisation(db: Session):
    """`_release_step` deja el paso PENDING para que otro worker lo repita: antes, con la
    misma autorización; ahora tiene que pedir otra."""
    run = waiting_run(db)
    review = reviews(db)[0]
    approve(db, review)
    orchestrator = PipelineOrchestrator(db)
    step = step_of(db, run)
    orchestrator._start_step(step, None, authorisation=review)  # el paso arranca y consume

    orchestrator._release_step(run, step)  # el arriendo se perdió a mitad del paso

    db.refresh(review)
    assert review.status == "CONSUMED"
    assert step.status == PipelineStepStatus.PENDING
    drain(db)
    db.refresh(run)
    assert run.status == PipelineRunStatus.WAITING_APPROVAL
    assert storefronts(db) == 0


def test_a_step_that_fails_after_consuming_needs_a_new_authorisation(db: Session, monkeypatch):
    run = waiting_run(db)
    review = reviews(db)[0]
    approve(db, review)

    def fails(self, *args, **kwargs):
        raise RuntimeError("remote call failed")

    original = PipelineOrchestrator._step_ecommerce
    monkeypatch.setattr(PipelineOrchestrator, "_step_ecommerce", fails)
    Worker(name="worker-1").run_once(db)
    db.refresh(review)
    assert review.status == "CONSUMED"
    assert step_of(db, run).status == PipelineStepStatus.FAILED

    monkeypatch.setattr(PipelineOrchestrator, "_step_ecommerce", original)
    PipelineOrchestrator(db).resume_run(db.get(PipelineRun, run.id), actor="owner@amazona.local")
    drain(db)

    db.refresh(run)
    assert run.status == PipelineRunStatus.WAITING_APPROVAL
    assert storefronts(db) == 0
    assert any("already used" in reason for item in reviews(db) if item.status == "PENDING" for reason in item.reasons)


def test_an_authorisation_that_was_not_used_is_not_consumed(db: Session):
    """Un veto (aquí, el kill switch) gana a la aprobación: si el paso no llega a ejecutarse, la
    autorización no se gasta, y se usa —una sola vez— cuando por fin se ejecuta."""
    run = waiting_run(db)
    review = reviews(db)[0]
    PipelineKillSwitchService(db).disable(reason="incident", actor="ops@amazona.local", correlation_id="c-1")
    approve(db, review)

    drain(db)

    db.refresh(review)
    db.refresh(run)
    assert review.status == "APPROVED"  # existe y no se ha usado
    assert run.status == PipelineRunStatus.BLOCKED
    assert storefronts(db) == 0

    PipelineKillSwitchService(db).enable(actor="ops@amazona.local", correlation_id="c-2")
    PipelineOrchestrator(db).resume_run(db.get(PipelineRun, run.id), actor="ops@amazona.local")
    drain(db)

    db.refresh(review)
    assert review.status == "CONSUMED"
    assert storefronts(db) == 1


# --- Dos ejecutores a la vez --------------------------------------------------------


def test_two_executors_cannot_consume_the_same_authorisation():
    with ephemeral_postgres() as engine:
        with Session(engine) as seed:
            run = PipelineOrchestrator(seed).enqueue_run(REQUEST)
            review = PipelineReview(
                pipeline_run_id=run.id,
                kind=REVIEW_KIND_ACTION_GATE,
                step="ecommerce",
                action="publish_product",
                reasons=["test"],
                status="APPROVED",
                correlation_id=run.correlation_id,
            )
            seed.add(review)
            seed.commit()
            run_id, review_id = run.id, review.id

        for _ in range(3):
            with Session(engine) as reset:
                reset.query(PipelineReview).filter_by(id=review_id).update({"status": "APPROVED"})
                reset.query(AuditLog).filter_by(action="pipeline_review.consume").delete()
                reset.commit()

            barrier = threading.Barrier(8)
            outcomes: list[str] = []
            lock = threading.Lock()

            def executor() -> None:
                with Session(engine) as session:
                    step = session.query(PipelineStep).filter_by(pipeline_run_id=run_id, name="ecommerce").one()
                    authorisation = session.get(PipelineReview, review_id)
                    try:
                        barrier.wait(timeout=10)
                        PipelineOrchestrator(session)._start_step(step, None, authorisation=authorisation)
                        result = "ok"
                    except PipelineRunStateError:
                        result = "PipelineRunStateError"
                    with lock:
                        outcomes.append(result)

            threads = [threading.Thread(target=executor) for _ in range(8)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=60)

            assert collections.Counter(outcomes) == {"ok": 1, "PipelineRunStateError": 7}
            with Session(engine) as check:
                assert check.get(PipelineReview, review_id).status == "CONSUMED"
                assert check.query(AuditLog).filter_by(action="pipeline_review.consume").count() == 1
