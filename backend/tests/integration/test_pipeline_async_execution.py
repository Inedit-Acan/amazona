"""Milestone 32 (ADR 0010): el pipeline se ejecuta en un trabajo del runtime, con
cada paso persistido, y eso es lo que hace posibles reintentar, reanudar y cancelar.

Se usa el `Worker` de verdad —no una llamada directa al orquestador— porque lo que
hay que demostrar es precisamente que el ciclo completo funciona a través del
runtime: reclamar, ejecutar paso a paso, fallar, esperar, continuar.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.db.models.job import Job, JobAttempt, JobEvent
from app.db.models.pipeline_review import PipelineReview
from app.db.models.pipeline_step import PipelineStep, PipelineStepAttempt
from app.jobs.schemas import JobEventKind, JobStatus
from app.jobs.worker import Worker
from app.pipeline.kill_switch import PipelineKillSwitchService
from app.pipeline.schemas import PipelineRunStatus, PipelineStepStatus
from app.pipeline.service import (
    PIPELINE_RUN_JOB,
    PipelineOrchestrator,
    PipelineRequest,
    steps_view,
)


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def request_payload() -> PipelineRequest:
    return PipelineRequest(category="home", sale_price=50.0, destination_region="mexico")


def steps_of(db: Session, run_id: str) -> list[PipelineStep]:
    return db.query(PipelineStep).filter_by(pipeline_run_id=run_id).order_by(PipelineStep.ordinal).all()


def statuses(db: Session, run_id: str) -> dict[str, str]:
    return {step.name: step.status for step in steps_of(db, run_id)}


def drain(db: Session, worker: Worker | None = None, rounds: int = 12) -> Worker:
    """Deja que el worker vacíe la cola. Devuelve el worker para poder seguir
    usando el mismo nombre —y por tanto el mismo arriendo— en la prueba."""
    worker = worker or Worker(name="test-worker")
    for _ in range(rounds):
        if worker.run_once(db) is None:
            break
    return worker


# --- Encolar ---------------------------------------------------------------


def test_enqueueing_creates_the_run_its_nine_steps_and_one_job(db_session, request_payload):
    run = PipelineOrchestrator(db_session).enqueue_run(request_payload, created_by="operator@example.com")

    assert run.status == PipelineRunStatus.QUEUED
    assert run.product_id is None
    assert [step.name for step in steps_of(db_session, run.id)] == [
        "research",
        "sourcing",
        "economics",
        "legal",
        "ecommerce",
        "marketplace",
        "marketing",
        "operations",
        "cfo",
    ]
    assert set(statuses(db_session, run.id).values()) == {PipelineStepStatus.PENDING}

    job = db_session.get(Job, run.job_id)
    assert job is not None
    assert job.type == PIPELINE_RUN_JOB
    assert job.status == JobStatus.QUEUED
    assert job.payload == {"pipeline_run_id": run.id}
    assert job.correlation_id == run.correlation_id
    assert job.created_by == "operator@example.com"


def test_enqueueing_keeps_the_business_parameters_so_it_can_be_resumed(db_session, request_payload):
    run = PipelineOrchestrator(db_session).enqueue_run(request_payload)

    assert run.request["sale_price"] == 50.0
    assert run.request["destination_region"] == "mexico"
    assert PipelineRequest.from_payload(run.request) == request_payload


def test_enqueueing_is_refused_while_the_kill_switch_is_off(db_session, request_payload):
    """ADR 0006 §3 sigue en pie: el switch se consulta antes de crear nada."""
    from app.core.errors import PipelineDisabledError

    PipelineKillSwitchService(db_session).disable(reason="drill", actor="owner", correlation_id="cid-1")

    with pytest.raises(PipelineDisabledError):
        PipelineOrchestrator(db_session).enqueue_run(request_payload)


# --- Ejecutar con el runtime ----------------------------------------------


def test_the_worker_runs_the_whole_chain_and_persists_every_step(db_session, request_payload):
    run = PipelineOrchestrator(db_session).enqueue_run(request_payload)

    drain(db_session)

    db_session.refresh(run)
    assert run.status == PipelineRunStatus.COMPLETED
    assert run.failed_step is None
    assert run.product_id is not None

    steps = steps_of(db_session, run.id)
    assert {step.status for step in steps} == {PipelineStepStatus.COMPLETED}
    # Cada paso guarda su propio correlation_id (ADR 0005) y la fila que produjo.
    assert all(step.correlation_id is not None for step in steps)
    assert all(step.entity_id is not None for step in steps)
    assert all(step.started_at is not None and step.finished_at is not None for step in steps)
    assert len({step.correlation_id for step in steps}) == 9

    job = db_session.get(Job, run.job_id)
    assert job.status == JobStatus.COMPLETED
    assert job.result_reference == run.correlation_id


def test_every_step_records_one_attempt_with_the_job_that_ran_it(db_session, request_payload):
    run = PipelineOrchestrator(db_session).enqueue_run(request_payload)

    drain(db_session)

    attempts = (
        db_session.query(PipelineStepAttempt)
        .filter(PipelineStepAttempt.pipeline_step_id.in_([s.id for s in steps_of(db_session, run.id)]))
        .all()
    )
    assert len(attempts) == 9
    assert {attempt.status for attempt in attempts} == {PipelineStepStatus.COMPLETED}
    assert {attempt.job_id for attempt in attempts} == {run.job_id}


def test_the_ids_are_threaded_between_steps_exactly_as_before(db_session, request_payload):
    """Lo que ADR 0005 llamaba «enhebrar los ids reales»: el producto elegido en
    research es el que usan los demás pasos."""
    run = PipelineOrchestrator(db_session).enqueue_run(request_payload)

    drain(db_session)

    db_session.refresh(run)
    view = steps_view(steps_of(db_session, run.id))
    assert view["research"]["entity_id"] == run.product_id
    assert view["economics"]["recommendation"] in {"GO", "REVIEW", "NO_GO"}
    assert view["legal"]["recommendation"] in {"GO", "REVIEW", "NO_GO"}
    assert view["cfo"]["step_status"] == PipelineStepStatus.COMPLETED


def test_a_category_without_candidates_is_partial_and_skips_the_rest(db_session):
    run = PipelineOrchestrator(db_session).enqueue_run(
        PipelineRequest(category="does-not-exist", sale_price=50.0, destination_region="mexico")
    )

    drain(db_session)

    db_session.refresh(run)
    assert run.status == PipelineRunStatus.PARTIAL
    assert run.failed_step == "research"
    step_statuses = statuses(db_session, run.id)
    assert step_statuses["research"] == PipelineStepStatus.FAILED
    assert set(list(step_statuses.values())[1:]) == {PipelineStepStatus.SKIPPED}

    # PARTIAL es un resultado de negocio, no un fallo técnico: el trabajo termina
    # bien y no se reintenta solo. Volver a preguntar lo mismo daría lo mismo.
    job = db_session.get(Job, run.job_id)
    assert job.status == JobStatus.COMPLETED
    assert job.attempt == 1

    # Y sigue disparando revisión humana, como en el Milestone 14 (ADR 0006).
    assert run.needs_review is True
    review = db_session.query(PipelineReview).filter_by(pipeline_run_id=run.id).one()
    assert review.status == "PENDING"


# --- Fallar y reanudar -----------------------------------------------------


def test_a_failing_step_keeps_the_previous_ones_and_leaves_the_run_resumable(
    db_session, request_payload, monkeypatch
):
    from app.economics.service import EconomicAnalysisService

    def explode(*args, **kwargs):
        raise RuntimeError("economics provider is down")

    monkeypatch.setattr(EconomicAnalysisService, "run_analysis", explode)
    run = PipelineOrchestrator(db_session).enqueue_run(request_payload)

    drain(db_session)

    db_session.refresh(run)
    assert run.status == PipelineRunStatus.FAILED
    assert run.failed_step == "economics"

    step_statuses = statuses(db_session, run.id)
    assert step_statuses["research"] == PipelineStepStatus.COMPLETED
    assert step_statuses["sourcing"] == PipelineStepStatus.COMPLETED
    assert step_statuses["economics"] == PipelineStepStatus.FAILED
    assert step_statuses["legal"] == PipelineStepStatus.PENDING

    economics = next(s for s in steps_of(db_session, run.id) if s.name == "economics")
    assert "economics provider is down" in (economics.error or "")

    # El runtime lo trata como cualquier fallo: espera y reintenta.
    job = db_session.get(Job, run.job_id)
    assert job.status == JobStatus.RETRYING
    assert job.attempt == 1


def test_resuming_after_a_fix_does_not_redo_the_work_that_was_already_valid(
    db_session, request_payload, monkeypatch
):
    from app.economics.service import EconomicAnalysisService

    original = EconomicAnalysisService.run_analysis
    monkeypatch.setattr(
        EconomicAnalysisService,
        "run_analysis",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("economics provider is down")),
    )
    orchestrator = PipelineOrchestrator(db_session)
    run = orchestrator.enqueue_run(request_payload)
    drain(db_session)
    db_session.refresh(run)
    before = {s.name: s.entity_id for s in steps_of(db_session, run.id)}
    research_correlation_id = next(s for s in steps_of(db_session, run.id) if s.name == "research").correlation_id

    monkeypatch.setattr(EconomicAnalysisService, "run_analysis", original)
    orchestrator.resume_run(run, actor="operator@example.com")
    drain(db_session)

    db_session.refresh(run)
    assert run.status == PipelineRunStatus.COMPLETED
    after = {s.name: s.entity_id for s in steps_of(db_session, run.id)}
    # Research y sourcing no se repitieron: mismas filas, mismo correlation_id.
    assert after["research"] == before["research"]
    assert after["sourcing"] == before["sourcing"]
    assert (
        next(s for s in steps_of(db_session, run.id) if s.name == "research").correlation_id
        == research_correlation_id
    )
    assert after["economics"] is not None


def test_resuming_reuses_the_same_job_so_the_history_stays_in_one_place(
    db_session, request_payload, monkeypatch
):
    from app.legal.service import LegalComplianceService

    monkeypatch.setattr(
        LegalComplianceService,
        "run_analysis",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("legal provider is down")),
    )
    orchestrator = PipelineOrchestrator(db_session)
    run = orchestrator.enqueue_run(request_payload)
    drain(db_session)
    first_job_id = run.job_id

    orchestrator.resume_run(run, actor="operator@example.com")

    db_session.refresh(run)
    assert run.job_id == first_job_id
    job = db_session.get(Job, first_job_id)
    assert job.status == JobStatus.QUEUED
    assert job.attempt == 0
    kinds = [
        event.kind
        for event in db_session.query(JobEvent).filter_by(job_id=first_job_id).order_by(JobEvent.created_at).all()
    ]
    assert JobEventKind.REQUEUED in kinds
    # Y los intentos anteriores siguen ahí: es lo que explica por qué hubo que
    # reanudarla.
    assert db_session.query(JobAttempt).filter_by(job_id=first_job_id).count() >= 1


def test_the_step_attempt_history_survives_a_resume(db_session, request_payload, monkeypatch):
    from app.economics.service import EconomicAnalysisService

    original = EconomicAnalysisService.run_analysis
    monkeypatch.setattr(
        EconomicAnalysisService,
        "run_analysis",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("economics provider is down")),
    )
    orchestrator = PipelineOrchestrator(db_session)
    run = orchestrator.enqueue_run(request_payload)
    drain(db_session)

    monkeypatch.setattr(EconomicAnalysisService, "run_analysis", original)
    orchestrator.resume_run(run, actor="operator@example.com")
    drain(db_session)

    economics = next(s for s in steps_of(db_session, run.id) if s.name == "economics")
    attempts = (
        db_session.query(PipelineStepAttempt)
        .filter_by(pipeline_step_id=economics.id)
        .order_by(PipelineStepAttempt.number)
        .all()
    )
    assert [attempt.status for attempt in attempts] == [
        PipelineStepStatus.FAILED,
        PipelineStepStatus.COMPLETED,
    ]
    assert "economics provider is down" in (attempts[0].error or "")
    assert economics.attempt == 2


def test_resuming_from_a_chosen_step_redoes_it_and_everything_after(db_session, request_payload):
    orchestrator = PipelineOrchestrator(db_session)
    run = orchestrator.enqueue_run(request_payload)
    drain(db_session)
    db_session.refresh(run)
    before = {s.name: s.entity_id for s in steps_of(db_session, run.id)}

    orchestrator.resume_run(run, actor="operator@example.com", from_step="economics")

    step_statuses = statuses(db_session, run.id)
    assert step_statuses["sourcing"] == PipelineStepStatus.COMPLETED
    assert step_statuses["economics"] == PipelineStepStatus.PENDING
    assert step_statuses["cfo"] == PipelineStepStatus.PENDING

    drain(db_session)

    db_session.refresh(run)
    after = {s.name: s.entity_id for s in steps_of(db_session, run.id)}
    assert run.status == PipelineRunStatus.COMPLETED
    assert after["sourcing"] == before["sourcing"]
    assert after["economics"] != before["economics"]


def test_resuming_from_research_forgets_the_product_that_no_longer_applies(db_session, request_payload):
    orchestrator = PipelineOrchestrator(db_session)
    run = orchestrator.enqueue_run(request_payload)
    drain(db_session)
    db_session.refresh(run)
    assert run.product_id is not None

    orchestrator.resume_run(run, actor="operator@example.com", from_step="research")

    db_session.refresh(run)
    assert run.product_id is None


def test_a_completed_run_cannot_be_resumed_by_accident(db_session, request_payload):
    from app.core.errors import PipelineRunStateError

    orchestrator = PipelineOrchestrator(db_session)
    run = orchestrator.enqueue_run(request_payload)
    drain(db_session)
    db_session.refresh(run)

    with pytest.raises(PipelineRunStateError):
        orchestrator.resume_run(run, actor="operator@example.com")


def test_a_run_without_its_parameters_refuses_to_resume_instead_of_inventing_them(
    db_session, request_payload
):
    """Las ejecuciones anteriores al Milestone 32 no guardaron precio de venta ni
    región de destino. Se dice que faltan; no se rellenan con un número inventado."""
    from app.core.errors import PipelineRunStateError

    orchestrator = PipelineOrchestrator(db_session)
    run = orchestrator.enqueue_run(request_payload)
    drain(db_session)
    db_session.refresh(run)
    run.request = {"category": "home", "market": "us"}
    run.status = PipelineRunStatus.FAILED
    db_session.commit()

    with pytest.raises(PipelineRunStateError) as failure:
        orchestrator.resume_run(run, actor="operator@example.com")
    assert "sale_price" in str(failure.value)


# --- Cancelar --------------------------------------------------------------


def test_cancelling_a_queued_run_stops_it_before_any_step_runs(db_session, request_payload):
    orchestrator = PipelineOrchestrator(db_session)
    run = orchestrator.enqueue_run(request_payload)

    orchestrator.cancel_run(run, actor="operator@example.com")

    assert run.status == PipelineRunStatus.CANCELLED
    assert db_session.get(Job, run.job_id).status == JobStatus.CANCELLED

    drain(db_session)

    db_session.refresh(run)
    assert run.status == PipelineRunStatus.CANCELLED
    assert set(statuses(db_session, run.id).values()) == {PipelineStepStatus.PENDING}
    assert run.product_id is None


def test_cancelling_mid_flight_reaches_the_run_at_the_next_heartbeat(db_session, request_payload):
    """Una cancelación llega a una ejecución en marcha entre dos pasos: el paso en
    curso se termina, y el siguiente ya no empieza."""
    from app.sourcing.service import SourcingService

    orchestrator = PipelineOrchestrator(db_session)
    run = orchestrator.enqueue_run(request_payload)
    original = SourcingService.run_sourcing

    def cancel_while_sourcing(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        # Alguien pulsa «cancelar» justo mientras corre este paso.
        PipelineOrchestrator(db_session).cancel_run(
            db_session.get(type(run), run.id), actor="operator@example.com"
        )
        return result

    monkey = pytest.MonkeyPatch()
    monkey.setattr(SourcingService, "run_sourcing", cancel_while_sourcing)
    try:
        drain(db_session)
    finally:
        monkey.undo()

    db_session.refresh(run)
    assert run.status == PipelineRunStatus.CANCELLED
    step_statuses = statuses(db_session, run.id)
    assert step_statuses["research"] == PipelineStepStatus.COMPLETED
    assert step_statuses["sourcing"] == PipelineStepStatus.COMPLETED
    # Los pasos que no llegaron a empezar siguen PENDING: es lo que permite
    # reanudarla después sin repetir nada.
    assert step_statuses["economics"] == PipelineStepStatus.PENDING
    assert db_session.get(Job, run.job_id).status == JobStatus.CANCELLED


def test_a_cancelled_run_can_be_resumed_from_where_it_stopped(db_session, request_payload):
    orchestrator = PipelineOrchestrator(db_session)
    run = orchestrator.enqueue_run(request_payload)
    orchestrator.cancel_run(run, actor="operator@example.com")

    orchestrator.resume_run(run, actor="operator@example.com")
    drain(db_session)

    db_session.refresh(run)
    assert run.status == PipelineRunStatus.COMPLETED


def test_a_finished_run_cannot_be_cancelled(db_session, request_payload):
    from app.core.errors import PipelineRunStateError

    orchestrator = PipelineOrchestrator(db_session)
    run = orchestrator.enqueue_run(request_payload)
    drain(db_session)
    db_session.refresh(run)

    with pytest.raises(PipelineRunStateError):
        orchestrator.cancel_run(run, actor="operator@example.com")


# --- Kill switch a mitad ---------------------------------------------------


def test_the_kill_switch_blocks_the_job_instead_of_burning_its_attempts(db_session, request_payload):
    """Si el switch se apaga entre encolar y ejecutar, el trabajo queda BLOCKED:
    el runtime no lo reclama y no gasta intentos, porque esperar no lo arregla
    (ADR 0010 §5)."""
    orchestrator = PipelineOrchestrator(db_session)
    run = orchestrator.enqueue_run(request_payload)
    PipelineKillSwitchService(db_session).disable(reason="drill", actor="owner", correlation_id="cid-1")

    drain(db_session)

    db_session.refresh(run)
    assert run.status == PipelineRunStatus.BLOCKED
    job = db_session.get(Job, run.job_id)
    assert job.status == JobStatus.BLOCKED
    assert job.attempt == 1
    assert "disabled by an operator" in (job.error or "")
    assert set(statuses(db_session, run.id).values()) == {PipelineStepStatus.PENDING}


def test_a_blocked_run_continues_once_the_switch_is_back_on(db_session, request_payload):
    orchestrator = PipelineOrchestrator(db_session)
    run = orchestrator.enqueue_run(request_payload)
    switch = PipelineKillSwitchService(db_session)
    switch.disable(reason="drill", actor="owner", correlation_id="cid-1")
    drain(db_session)

    switch.enable(actor="owner", correlation_id="cid-2")
    orchestrator.resume_run(run, actor="operator@example.com")
    drain(db_session)

    db_session.refresh(run)
    assert run.status == PipelineRunStatus.COMPLETED
    assert db_session.get(Job, run.job_id).status == JobStatus.COMPLETED
