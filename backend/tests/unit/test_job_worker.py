"""El worker de trabajos (Milestone 31): el ciclo completo, y qué hace cuando
el manejador se porta mal.
"""

import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models.job import JobEvent
from app.db.models.product import Product
from app.jobs import registry
from app.jobs.handlers import DIAGNOSTIC_ECHO, RESEARCH_RUN
from app.jobs.queue import JobQueue
from app.jobs.schemas import JobBlockedError, JobCancelledError, JobResult, JobStatus
from app.jobs.worker import Worker


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture()
def queue(db):
    return JobQueue(db)


@pytest.fixture()
def worker():
    return Worker(name="test-worker")


@pytest.fixture()
def temporary_handler():
    """Registra un manejador solo para una prueba y lo retira después: el
    registro es global, y un test no puede ensuciar al siguiente."""
    registered: list[str] = []

    def add(job_type: str, handler):
        registry.register(job_type)(handler)
        registered.append(job_type)

    yield add

    for job_type in registered:
        registry._HANDLERS.pop(job_type, None)


# --- El ciclo feliz ----------------------------------------------------------


def test_the_worker_runs_a_job_and_completes_it(queue, db, worker):
    job = queue.enqueue(job_type=DIAGNOSTIC_ECHO, payload={"hola": "mundo"})

    handled = worker.run_once(db)

    db.refresh(job)
    assert handled is not None and handled.id == job.id
    assert job.status == JobStatus.COMPLETED
    assert job.result_reference == job.correlation_id
    assert job.lease_worker is None


def test_the_worker_does_nothing_when_the_queue_is_empty(db, worker):
    assert worker.run_once(db) is None


def test_a_real_job_does_the_work_outside_the_request(queue, db, worker):
    """`research.run` hace lo mismo que POST /api/research/runs, pero en un
    worker: el navegador no espera y un fallo se reintenta."""
    job = queue.enqueue(job_type=RESEARCH_RUN, payload={"category": "electronics", "max_results": 3})

    worker.run_once(db)

    db.refresh(job)
    assert job.status == JobStatus.COMPLETED
    assert job.result_reference == job.correlation_id
    # El resultado vive donde vive siempre, no en la fila del trabajo.
    assert db.query(Product).count() > 0


# --- Cuando el manejador falla ----------------------------------------------


def test_a_failing_handler_schedules_a_retry(queue, db, worker):
    job = queue.enqueue(job_type=DIAGNOSTIC_ECHO, payload={"fail": True}, max_attempts=3)

    worker.run_once(db)

    db.refresh(job)
    assert job.status == JobStatus.RETRYING
    assert job.attempt == 1
    assert "diagnostic failure" in (job.error or "")


def test_a_handler_that_keeps_failing_ends_up_failed(queue, db, worker):
    job = queue.enqueue(job_type=DIAGNOSTIC_ECHO, payload={"fail": True}, max_attempts=2)

    for _ in range(2):
        worker.run_once(db)
        job.available_at = datetime.datetime.now(datetime.UTC) - datetime.timedelta(seconds=1)
        db.commit()
        JobQueue(db).release_due_retries()

    db.refresh(job)
    assert job.status == JobStatus.FAILED
    assert job.attempt == 2


def test_an_unknown_job_type_fails_immediately_without_burning_retries(queue, db, worker):
    """Un tipo que nadie registró es un error de despliegue: esperar no lo
    arregla, así que no se reintenta tres veces para nada."""
    job = queue.enqueue(job_type="nope.does-not-exist", max_attempts=3)
    job.status = JobStatus.QUEUED
    db.commit()

    worker.run_once(db)

    db.refresh(job)
    assert job.status == JobStatus.FAILED
    assert "no handler registered" in (job.error or "")


def test_a_handler_that_writes_before_failing_does_not_leave_half_a_change(
    queue, db, worker, temporary_handler
):
    """Si el manejador escribió y luego reventó, el worker deshace: un trabajo
    que se va a reintentar no puede dejar la mitad de su efecto hecho."""

    def writes_then_fails(payload, context, session):
        session.add(Product(name="fantasma", category="test", created_by="test"))
        session.flush()
        raise RuntimeError("reventó después de escribir")

    temporary_handler("test.writes-then-fails", writes_then_fails)
    queue.enqueue(job_type="test.writes-then-fails", max_attempts=1)

    worker.run_once(db)

    assert db.query(Product).filter_by(name="fantasma").count() == 0


# --- Cancelación a mitad -----------------------------------------------------


def test_a_cancelled_job_stops_at_its_next_heartbeat(queue, db, worker, temporary_handler):
    def cancels_itself(payload, context, session):
        JobQueue(session).cancel(context.job_id)
        context.heartbeat()  # aquí se entera
        return JobResult(reference="no debería llegar")

    temporary_handler("test.cancels-itself", cancels_itself)
    job = queue.enqueue(job_type="test.cancels-itself")

    worker.run_once(db)

    db.refresh(job)
    assert job.status == JobStatus.CANCELLED
    assert job.result_reference is None


def test_the_result_of_a_job_taken_away_mid_flight_is_discarded(queue, db, worker, temporary_handler):
    """El manejador termina, pero mientras tanto lo cancelaron. Aceptar su
    resultado pisaría la decisión de quien canceló."""

    def finishes_after_being_cancelled(payload, context, session):
        JobQueue(session).cancel(context.job_id)
        return JobResult(reference="tarde")

    temporary_handler("test.late", finishes_after_being_cancelled)
    job = queue.enqueue(job_type="test.late")

    worker.run_once(db)

    db.refresh(job)
    assert job.status == JobStatus.CANCELLED
    assert job.result_reference is None


# --- Mantenimiento en cada vuelta -------------------------------------------


def test_each_cycle_reaps_dead_leases_before_claiming(queue, db, worker):
    """El mantenimiento va dentro del bucle: no hay un proceso aparte que
    alguien pueda olvidarse de arrancar."""
    abandoned = queue.enqueue(job_type=DIAGNOSTIC_ECHO, max_attempts=3)
    claimed = queue.claim(worker="worker-que-murio", lease_seconds=60)
    claimed.lease_expires_at = datetime.datetime.now(datetime.UTC) - datetime.timedelta(seconds=1)
    db.commit()

    worker.run_once(db)

    db.refresh(abandoned)
    assert abandoned.status == JobStatus.COMPLETED
    kinds = [e.kind for e in db.query(JobEvent).filter_by(job_id=abandoned.id).all()]
    assert "lease_expired" in kinds


def test_each_cycle_releases_retries_whose_wait_is_over(queue, db, worker):
    job = queue.enqueue(job_type=DIAGNOSTIC_ECHO, payload={"fail": True}, max_attempts=3)
    worker.run_once(db)
    db.refresh(job)
    assert job.status == JobStatus.RETRYING

    job.available_at = datetime.datetime.now(datetime.UTC) - datetime.timedelta(seconds=1)
    job.payload = {}
    db.commit()

    worker.run_once(db)

    db.refresh(job)
    assert job.status == JobStatus.COMPLETED
    assert job.attempt == 2


def test_two_workers_never_take_the_same_job(queue, db):
    queue.enqueue(job_type=DIAGNOSTIC_ECHO)

    first = Worker(name="w1").run_once(db)
    second = Worker(name="w2").run_once(db)

    assert first is not None
    assert second is None


def test_the_worker_survives_a_handler_that_raises_on_import_of_its_payload(queue, db, worker, temporary_handler):
    def explodes(payload, context, session):
        raise JobCancelledError("me lo quitaron")

    temporary_handler("test.taken", explodes)
    job = queue.enqueue(job_type="test.taken")

    worker.run_once(db)

    db.refresh(job)
    # Se lo quitaron: el worker no reporta nada y el trabajo se queda como
    # estaba, para que decida quien lo tenga ahora.
    assert job.status == JobStatus.RUNNING


def test_a_handler_that_hits_an_external_condition_leaves_the_job_blocked(
    queue, db, worker, temporary_handler
):
    """Milestone 32: `JobBlockedError` es la forma en que un manejador dice «esto
    no lo arregla esperar». El trabajo queda BLOCKED sin gastar intentos, y el
    runtime no lo vuelve a reclamar hasta que alguien lo reencole."""

    def blocked(payload, context, session):
        raise JobBlockedError("pipeline runs are currently disabled by an operator")

    temporary_handler("test.blocked", blocked)
    job = queue.enqueue(job_type="test.blocked", max_attempts=3)

    worker.run_once(db)

    db.refresh(job)
    assert job.status == JobStatus.BLOCKED
    assert job.attempt == 1
    assert "disabled by an operator" in (job.error or "")
    assert worker.run_once(db) is None
