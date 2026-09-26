"""El runtime de trabajos (Milestone 31): reclamo, reintentos, arriendos y
cancelación.

Lo que se prueba aquí no es que los datos vayan y vengan, sino que el runtime se
comporta cuando algo sale mal: un worker que muere, un manejador que revienta,
una cancelación a mitad, un tipo que nadie registró.
"""

import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models.job import Job, JobAttempt, JobEvent
from app.jobs.queue import JobQueue, backoff_seconds
from app.jobs.schemas import HELD, TERMINAL, JobCancelledError, JobEventKind, JobStatus


def utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


def aware(value: datetime.datetime) -> datetime.datetime:
    """SQLite pierde la zona horaria al ir y volver; en PostgreSQL vuelve
    puesta. Todo lo que se guarda es UTC, así que normalizar aquí compara lo
    mismo en los dos."""
    return value if value.tzinfo is not None else value.replace(tzinfo=datetime.UTC)


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


def events_of(db, job: Job) -> list[str]:
    return [e.kind for e in db.query(JobEvent).filter_by(job_id=job.id).order_by(JobEvent.created_at).all()]


# --- Encolar -----------------------------------------------------------------


def test_an_enqueued_job_is_claimable_and_recorded(queue, db):
    job = queue.enqueue(job_type="diagnostic.echo", payload={"a": 1})

    assert job.status == JobStatus.QUEUED
    assert job.attempt == 0
    assert job.correlation_id
    assert events_of(db, job) == [JobEventKind.ENQUEUED]


def test_a_job_scheduled_for_later_is_not_claimable_yet(queue):
    queue.enqueue(job_type="diagnostic.echo", available_at=utcnow() + datetime.timedelta(minutes=5))

    assert queue.claim(worker="w1") is None


def test_the_same_idempotency_key_returns_the_same_job(queue, db):
    """Reintentar una petición HTTP cuyo resultado no se conoce no puede
    duplicar el trabajo."""
    first = queue.enqueue(job_type="diagnostic.echo", idempotency_key="k-1")
    second = queue.enqueue(job_type="diagnostic.echo", idempotency_key="k-1")

    assert first.id == second.id
    assert db.query(Job).count() == 1


def test_jobs_without_a_key_are_never_deduplicated(queue, db):
    queue.enqueue(job_type="diagnostic.echo")
    queue.enqueue(job_type="diagnostic.echo")

    assert db.query(Job).count() == 2


# --- Reclamar ----------------------------------------------------------------


def test_claiming_leases_the_job_and_opens_an_attempt(queue, db):
    queue.enqueue(job_type="diagnostic.echo")

    job = queue.claim(worker="w1")

    assert job is not None
    assert job.status == JobStatus.RUNNING
    assert job.attempt == 1
    assert job.lease_worker == "w1"
    assert job.lease_expires_at is not None
    attempt = db.query(JobAttempt).filter_by(job_id=job.id).one()
    assert (attempt.number, attempt.worker) == (1, "w1")


def test_a_claimed_job_is_not_claimed_twice(queue):
    queue.enqueue(job_type="diagnostic.echo")

    assert queue.claim(worker="w1") is not None
    assert queue.claim(worker="w2") is None


def test_the_oldest_available_job_goes_first(queue):
    old = queue.enqueue(job_type="diagnostic.echo", payload={"n": 1})
    old.available_at = utcnow() - datetime.timedelta(minutes=10)
    queue._db.commit()
    queue.enqueue(job_type="diagnostic.echo", payload={"n": 2})

    assert queue.claim(worker="w1").id == old.id


@pytest.mark.parametrize("status", sorted(HELD))
def test_a_held_job_is_never_claimed(queue, db, status):
    """WAITING_APPROVAL y BLOCKED son del Milestone 33: el runtime ya sabe que
    no son suyos."""
    job = queue.enqueue(job_type="diagnostic.echo")
    job.status = status
    db.commit()

    assert queue.claim(worker="w1") is None


@pytest.mark.parametrize("status", sorted(TERMINAL))
def test_a_finished_job_is_never_claimed(queue, db, status):
    job = queue.enqueue(job_type="diagnostic.echo")
    job.status = status
    db.commit()

    assert queue.claim(worker="w1") is None


# --- Completar y fallar ------------------------------------------------------


def test_completing_stores_the_reference_and_releases_the_lease(queue, db):
    queue.enqueue(job_type="diagnostic.echo")
    job = queue.claim(worker="w1")

    done = queue.complete(job.id, worker="w1", reference="corr-9")

    assert done.status == JobStatus.COMPLETED
    assert done.result_reference == "corr-9"
    assert done.lease_worker is None
    assert db.query(JobAttempt).filter_by(job_id=job.id).one().status == JobStatus.COMPLETED
    assert JobEventKind.COMPLETED in events_of(db, job)


def test_a_failure_schedules_a_retry_with_backoff(queue, db):
    queue.enqueue(job_type="diagnostic.echo", max_attempts=3)
    job = queue.claim(worker="w1")

    failed = queue.fail(job.id, worker="w1", error="boom")

    assert failed.status == JobStatus.RETRYING
    assert aware(failed.available_at) > utcnow()
    assert failed.error == "boom"
    assert JobEventKind.RETRY_SCHEDULED in events_of(db, job)


def test_the_last_failure_is_final(queue, db):
    queue.enqueue(job_type="diagnostic.echo", max_attempts=1)
    job = queue.claim(worker="w1")

    failed = queue.fail(job.id, worker="w1", error="boom")

    assert failed.status == JobStatus.FAILED
    assert failed.failed_at is not None
    assert JobEventKind.FAILED in events_of(db, job)


def test_every_attempt_keeps_its_own_error(queue, db):
    """Un reintento no puede borrar la historia del intento anterior."""
    queue.enqueue(job_type="diagnostic.echo", max_attempts=3)
    job = queue.claim(worker="w1")
    queue.fail(job.id, worker="w1", error="primero")
    job.available_at = utcnow()
    job.status = JobStatus.QUEUED
    db.commit()
    queue.claim(worker="w2")
    queue.fail(job.id, worker="w2", error="segundo")

    attempts = db.query(JobAttempt).filter_by(job_id=job.id).order_by(JobAttempt.number).all()
    assert [(a.number, a.worker, a.error) for a in attempts] == [
        (1, "w1", "primero"),
        (2, "w2", "segundo"),
    ]


def test_backoff_grows_and_has_a_ceiling():
    assert backoff_seconds(1) < backoff_seconds(2) < backoff_seconds(3)
    assert backoff_seconds(50) == backoff_seconds(60)


def test_a_retry_becomes_claimable_once_its_wait_is_over(queue, db):
    queue.enqueue(job_type="diagnostic.echo", max_attempts=3)
    job = queue.claim(worker="w1")
    queue.fail(job.id, worker="w1", error="boom")

    assert queue.claim(worker="w2") is None

    job.available_at = utcnow() - datetime.timedelta(seconds=1)
    db.commit()
    assert queue.release_due_retries() == 1
    assert queue.claim(worker="w2") is not None


# --- Arriendos y workers muertos --------------------------------------------


def test_a_heartbeat_extends_the_lease(queue, db):
    queue.enqueue(job_type="diagnostic.echo")
    job = queue.claim(worker="w1", lease_seconds=30)
    before = aware(job.lease_expires_at)

    queue.heartbeat(job.id, worker="w1", lease_seconds=300)

    db.refresh(job)
    assert aware(job.lease_expires_at) > before


def test_a_heartbeat_from_the_wrong_worker_is_refused(queue):
    queue.enqueue(job_type="diagnostic.echo")
    job = queue.claim(worker="w1")

    with pytest.raises(JobCancelledError):
        queue.heartbeat(job.id, worker="w2")


def test_a_dead_worker_releases_its_job(queue, db):
    """Detección de worker muerto: no hace falta que los workers se registren ni
    se vigilen, basta con que un arriendo vencido sea recuperable."""
    queue.enqueue(job_type="diagnostic.echo", max_attempts=3)
    job = queue.claim(worker="w1", lease_seconds=60)
    job.lease_expires_at = utcnow() - datetime.timedelta(seconds=1)
    db.commit()

    reaped = queue.reap_expired_leases()

    db.refresh(job)
    assert [j.id for j in reaped] == [job.id]
    assert job.status == JobStatus.QUEUED
    assert job.lease_worker is None
    assert JobEventKind.LEASE_EXPIRED in events_of(db, job)
    assert queue.claim(worker="w2") is not None


def test_a_dead_worker_on_the_last_attempt_fails_the_job(queue, db):
    queue.enqueue(job_type="diagnostic.echo", max_attempts=1)
    job = queue.claim(worker="w1")
    job.lease_expires_at = utcnow() - datetime.timedelta(seconds=1)
    db.commit()

    queue.reap_expired_leases()

    db.refresh(job)
    assert job.status == JobStatus.FAILED


def test_a_zombie_worker_cannot_overwrite_its_replacement(queue, db):
    """El worker viejo termina tarde y quiere reportar: se descarta, porque
    aceptarlo pisaría lo que hizo quien lo sustituyó."""
    queue.enqueue(job_type="diagnostic.echo", max_attempts=3)
    job = queue.claim(worker="w1")
    job.lease_expires_at = utcnow() - datetime.timedelta(seconds=1)
    db.commit()
    queue.reap_expired_leases()
    queue.claim(worker="w2")

    with pytest.raises(JobCancelledError):
        queue.complete(job.id, worker="w1", reference="tarde")


# --- Cancelar y reencolar ----------------------------------------------------


def test_a_queued_job_can_be_cancelled(queue, db):
    job = queue.enqueue(job_type="diagnostic.echo")

    cancelled = queue.cancel(job.id, actor="owner@amazona.local")

    assert cancelled.status == JobStatus.CANCELLED
    assert cancelled.cancelled_at is not None
    assert queue.claim(worker="w1") is None


def test_cancelling_a_running_job_reaches_it_through_its_heartbeat(queue):
    queue.enqueue(job_type="diagnostic.echo")
    job = queue.claim(worker="w1")

    queue.cancel(job.id)

    with pytest.raises(JobCancelledError):
        queue.heartbeat(job.id, worker="w1")


def test_cancelling_a_finished_job_changes_nothing(queue):
    queue.enqueue(job_type="diagnostic.echo")
    job = queue.claim(worker="w1")
    queue.complete(job.id, worker="w1")

    assert queue.cancel(job.id).status == JobStatus.COMPLETED


def test_a_failed_job_can_be_requeued(queue, db):
    """La cola de mensajes muertos es el conjunto de trabajos en FAILED, y
    vaciarla es reencolarlos."""
    queue.enqueue(job_type="diagnostic.echo", max_attempts=1)
    job = queue.claim(worker="w1")
    queue.fail(job.id, worker="w1", error="boom")

    requeued = queue.requeue(job.id, actor="owner@amazona.local")

    assert requeued.status == JobStatus.QUEUED
    assert requeued.attempt == 0
    assert requeued.error is None
    assert queue.claim(worker="w2") is not None


def test_cancelling_a_job_that_does_not_exist_is_an_error(queue):
    with pytest.raises(LookupError):
        queue.cancel("nope")
