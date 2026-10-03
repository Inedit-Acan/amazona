# ruff: noqa: F811 - los fixtures de pytest se importan del módulo de apoyo y los tests los piden por su nombre
"""El disparador de trabajos recurrentes dentro del mantenimiento del worker (Milestone 45, ADR 0029 §2), sobre
SQLite y PostgreSQL.

Lo que se afirma:

- el tiempo se divide en cubos y cada tipo se encola con una clave estable `recurring:{tipo}:{cubo}`: repetir la
vuelta, reiniciar el worker o tener N
  workers produce **un solo trabajo por tipo y cubo**; el cubo siguiente encola otro;
- un worker que muere con su trabajo reclamado no lo pierde: el arriendo vence, otro lo recupera y lo completa (el
barrido es idempotente);
- con `reconciliation_enabled = false` no se encola nada y un tick que ya estaba encolado **no hace nada**;
- la purga borra los ticks completados y viejos con sus intentos y eventos, y **solo** esos;
- un fallo del mantenimiento no impide reclamar trabajo; ningún tick lleva datos; ningún camino ejecuta ni reconcilia
una acción externa.
"""

import datetime

import pytest
from payment_test_support import run_together
from reconciliation_test_support import (  # noqa: F401 - fixtures de pytest
    NOW,
    age_action,
    ago,
    authorise_budget,
    db,
    engine,
    event_row,
    factory,
    make_action,
    status_of,
    stored_event,
)
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.actions.service import ExternalActionService
from app.core.config import Settings
from app.db.models.job import Job, JobAttempt, JobEvent
from app.jobs import handlers
from app.jobs.queue import JobQueue
from app.jobs.recurring import (
    KEY_PREFIX,
    RECONCILE_ACTIONS,
    RECONCILE_JOB_TYPES,
    RECONCILE_PAYMENT_EVENTS,
    RECONCILE_REPORT,
    RecurringScheduler,
    bucket_of,
    recurring_jobs,
    tick_key,
    tick_prefix,
)
from app.jobs.schemas import JobStatus
from app.jobs.worker import Worker

SETTINGS = Settings(_env_file=None)
DISABLED = Settings(_env_file=None, reconciliation_enabled=False)
STEP = datetime.timedelta(seconds=SETTINGS.reconcile_actions_interval_seconds)


def ticks(db: Session) -> list[Job]:
    db.expire_all()
    return list(
        db.scalars(select(Job).where(Job.idempotency_key.like(f"{KEY_PREFIX}%")).order_by(Job.created_at, Job.id))
    )


def drain(worker: Worker, session: Session, limit: int = 50) -> int:
    done = 0
    while worker.run_once(session) is not None and done < limit:
        done += 1
    return done


def attempts_of(db: Session, job: Job) -> int:
    return db.scalar(select(func.count(JobAttempt.id)).where(JobAttempt.job_id == job.id)) or 0


# --- Cubos y claves -------------------------------------------------------------------------------------------------


def test_the_bucket_is_the_same_for_every_instant_of_an_interval_in_any_process():
    start = datetime.datetime(2026, 10, 3, 12, 0, 0, tzinfo=datetime.UTC)
    interval = 300

    assert bucket_of(start, interval) == bucket_of(start + datetime.timedelta(seconds=299), interval)
    assert bucket_of(start, interval) + 1 == bucket_of(start + datetime.timedelta(seconds=300), interval)
    assert bucket_of(start, interval) == int(start.timestamp() // 300)


def test_the_tick_key_names_the_type_and_the_bucket_and_nothing_else():
    assert tick_key(RECONCILE_ACTIONS, 42) == "recurring:reconcile.actions:42"
    assert tick_key(RECONCILE_PAYMENT_EVENTS, 7).startswith(tick_prefix(RECONCILE_PAYMENT_EVENTS))
    assert tick_prefix(RECONCILE_ACTIONS) != tick_prefix(RECONCILE_REPORT)


def test_the_recurring_jobs_follow_the_settings_and_vanish_when_disabled():
    jobs = {job.job_type: job.interval_seconds for job in recurring_jobs(SETTINGS)}

    assert jobs == {RECONCILE_ACTIONS: 300, RECONCILE_PAYMENT_EVENTS: 120, RECONCILE_REPORT: 300}
    assert set(jobs) == set(RECONCILE_JOB_TYPES)
    assert recurring_jobs(DISABLED) == []
    tuned = Settings(_env_file=None, reconcile_actions_interval_seconds=600, reconcile_events_interval_seconds=60)
    assert {j.job_type: j.interval_seconds for j in recurring_jobs(tuned)}[RECONCILE_ACTIONS] == 600


# --- Un trabajo por tipo y cubo
# ------------------------------------------------------------------------------------------


def test_repeating_the_round_restarting_the_worker_and_the_next_bucket(db: Session):
    scheduler = RecurringScheduler(SETTINGS, clock=lambda: NOW)

    first = scheduler.enqueue_due(db)
    assert len(first) == 3 and len(ticks(db)) == 3

    assert scheduler.enqueue_due(db) == [], "the same worker does not even ask again within the bucket"
    restarted = RecurringScheduler(SETTINGS, clock=lambda: NOW)
    assert sorted(restarted.enqueue_due(db)) == sorted(first), "a restarted worker finds what is already there"
    assert len(ticks(db)) == 3, "still one job per type and bucket"

    later = RecurringScheduler(SETTINGS, clock=lambda: NOW + STEP * 2)
    later.enqueue_due(db)
    assert len(ticks(db)) == 6, "the next bucket enqueues the next tick"


def test_each_type_has_its_own_bucket_size(db: Session):
    RecurringScheduler(SETTINGS, clock=lambda: NOW).enqueue_due(db)
    by_type = {job.type: job for job in ticks(db)}

    assert by_type[RECONCILE_ACTIONS].idempotency_key.endswith(str(bucket_of(NOW, 300)))
    assert by_type[RECONCILE_PAYMENT_EVENTS].idempotency_key.endswith(str(bucket_of(NOW, 120)))
    assert by_type[RECONCILE_ACTIONS].idempotency_key != by_type[RECONCILE_PAYMENT_EVENTS].idempotency_key


def test_a_tick_carries_no_data_only_its_bucket_and_who_scheduled_it(db: Session):
    RecurringScheduler(SETTINGS, clock=lambda: NOW).enqueue_due(db)

    for job in ticks(db):
        assert set(job.payload) == {"bucket", "interval_seconds"}
        assert job.created_by == "scheduler" and job.max_attempts == 3


def test_disabled_the_scheduler_enqueues_nothing(db: Session):
    assert RecurringScheduler(DISABLED, clock=lambda: NOW).enqueue_due(db) == []
    assert Worker(settings=DISABLED, clock=lambda: NOW).run_once(db) is None
    assert ticks(db) == []


# --- Varios workers -------------------------------------------------------------------------------------------------


def test_two_workers_in_the_same_bucket_produce_one_job_per_type_and_run_each_once(db: Session):
    one = Worker(name="w1", settings=SETTINGS, clock=lambda: NOW)
    two = Worker(name="w2", settings=SETTINGS, clock=lambda: NOW)

    drained = drain(one, db) + drain(two, db)

    jobs = ticks(db)
    assert len(jobs) == 3 and drained == 3, "three ticks, each run exactly once"
    assert {job.status for job in jobs} == {JobStatus.COMPLETED}
    assert [attempts_of(db, job) for job in jobs] == [1, 1, 1]


def test_many_workers_at_once_still_produce_one_job_per_type_and_run_each_once(engine, factory):
    if engine.dialect.name != "postgresql":
        pytest.skip("races only exist on a database with real transactions")

    def worker_job(session: Session):
        worker = Worker(name=f"w-{id(session)}", settings=SETTINGS, clock=lambda: NOW)
        return drain(worker, session)

    results = run_together(engine, [worker_job] * 8)

    errors = [r for r in results if isinstance(r, Exception)]
    assert not errors, errors
    assert sum(results) == 3, "eight workers, three ticks: each run by exactly one of them"
    with factory() as check:
        jobs = ticks(check)
        assert len(jobs) == 3 and {job.status for job in jobs} == {JobStatus.COMPLETED}
        assert sorted(attempts_of(check, job) for job in jobs) == [1, 1, 1]
        assert {job.type for job in jobs} == set(RECONCILE_JOB_TYPES)


# --- Un worker que muere
# ------------------------------------------------------------------------------------------------------


def test_a_worker_that_dies_holding_a_tick_loses_nothing_the_lease_expires_and_another_completes_it(db: Session):
    authorise_budget(db)
    stale = make_action(db, state="PENDING")
    age_action(db, stale, updated=ago(minutes=30), created=ago(minutes=30))
    scheduler = RecurringScheduler(SETTINGS, clock=lambda: NOW)
    scheduler.enqueue_due(db)
    victim = next(job for job in ticks(db) if job.type == RECONCILE_ACTIONS)
    claimed = JobQueue(db).claim(worker="dead-worker")  # reclama el más antiguo y muere sin completarlo
    assert claimed is not None
    if claimed.id != victim.id:  # el que haya reclamado, lo hace caducar igual
        victim = claimed
    db.execute(
        update(Job).where(Job.id == victim.id).values(lease_expires_at=datetime.datetime.now(datetime.UTC) - STEP)
    )
    db.commit()

    survivor = Worker(name="survivor", settings=SETTINGS, clock=lambda: NOW)
    drain(survivor, db)

    db.expire_all()
    job = db.get(Job, victim.id)
    assert job is not None and job.status == JobStatus.COMPLETED, "it was not lost"
    assert attempts_of(db, job) == 2, "the dead attempt and the one that completed it"
    kinds = [event.kind for event in db.scalars(select(JobEvent).where(JobEvent.job_id == job.id))]
    assert "lease_expired" in kinds and "requeued" in kinds
    assert status_of(db, stale) == "FAILED_CONFIRMED", "the idempotent sweep still did its work exactly once"


def test_the_zombie_cannot_overwrite_what_its_replacement_did(db: Session):
    queue = JobQueue(db)
    queue.enqueue(job_type="diagnostic.echo", payload={})  # un solo trabajo: no hay duda de cuál es
    zombie_claim = queue.claim(worker="zombie")
    assert zombie_claim is not None
    db.execute(
        update(Job).where(Job.id == zombie_claim.id).values(lease_expires_at=datetime.datetime.now(datetime.UTC) - STEP)
    )
    db.commit()
    queue.reap_expired_leases()
    replacement = queue.claim(worker="replacement")
    assert replacement is not None and replacement.id == zombie_claim.id
    queue.complete(replacement.id, worker="replacement", detail={"by": "replacement"})

    from app.jobs.schemas import JobCancelledError

    with pytest.raises(JobCancelledError):
        queue.complete(zombie_claim.id, worker="zombie", detail={"by": "zombie"})
    db.expire_all()
    done = db.get(Job, zombie_claim.id)
    assert done is not None and done.status == JobStatus.COMPLETED
    completed = [
        e.detail for e in db.scalars(select(JobEvent).where(JobEvent.job_id == done.id, JobEvent.kind == "completed"))
    ]
    assert completed == [{"by": "replacement"}], "only the replacement's result was recorded"


# --- Apagado --------------------------------------------------------------------------------------------------------


def test_disabled_an_already_enqueued_tick_does_nothing(db: Session, monkeypatch):
    authorise_budget(db)
    stale = make_action(db, state="PENDING")
    age_action(db, stale, updated=ago(minutes=30), created=ago(minutes=30))
    event = stored_event(db)
    RecurringScheduler(SETTINGS, clock=lambda: NOW).enqueue_due(db)  # ya hay ticks encolados
    monkeypatch.setattr(handlers, "get_settings", lambda: DISABLED)

    drained = drain(Worker(name="w", settings=DISABLED, clock=lambda: NOW), db)

    assert drained == 3
    assert status_of(db, stale) == "PENDING", "disabled: the stale action is left exactly as it was"
    assert event_row(db, event.provider_event_id).processing_status == "RECEIVED"
    assert event_row(db, event.provider_event_id).reconcile_attempts == 0
    completed = [e.detail for e in db.scalars(select(JobEvent).where(JobEvent.kind == "completed"))]
    assert completed == [{"disabled": True}] * 3


# --- De extremo a extremo
# -------------------------------------------------------------------------------------------------------


def test_a_worker_drains_the_ticks_and_the_system_converges_on_what_it_must(db: Session):
    authorise_budget(db)
    never_sent = make_action(db, state="PENDING", reference="pipeline_step:run-1:a")
    abandoned_call = make_action(db, state="CALLING", reference="pipeline_step:run-1:b")
    unknown = make_action(db, state="UNKNOWN_OUTCOME", reference="pipeline_step:run-1:c")
    recent = make_action(db, state="PENDING", reference="pipeline_step:run-1:d")
    for action in (never_sent, abandoned_call, unknown):
        age_action(db, action, updated=ago(minutes=30), call_started=ago(minutes=30), created=ago(minutes=30))
    event = stored_event(db, amount="50.00", payment_ref="nobody", client_reference="nobody")

    drain(Worker(name="w", settings=SETTINGS, clock=lambda: NOW), db)

    assert status_of(db, never_sent) == "FAILED_CONFIRMED", "what never left is released"
    assert status_of(db, abandoned_call) == "UNKNOWN_OUTCOME", "what may have left is unknown, never failed"
    assert status_of(db, unknown) == "UNKNOWN_OUTCOME", "an unknown outcome waits for information or a person"
    assert status_of(db, recent) == "PENDING", "a recent action may be about to call"
    assert event_row(db, event.provider_event_id).processing_status == "UNMATCHED", (
        "the event went through the usual door"
    )
    results = {
        job.type: [
            e.detail
            for e in db.scalars(select(JobEvent).where(JobEvent.job_id == job.id, JobEvent.kind == "completed"))
        ]
        for job in ticks(db)
    }
    assert results[RECONCILE_ACTIONS] == [
        {"examined": 2, "released": 1, "marked_unknown": 1, "lost_race": 0, "failed": 0}
    ]
    assert results[RECONCILE_PAYMENT_EVENTS][0]["outcomes"] == {"unmatched": 1}
    assert results[RECONCILE_REPORT][0]["events_capped"] == 0


def test_no_scheduled_path_ever_executes_or_reconciles_an_external_action(db: Session, monkeypatch):
    authorise_budget(db)
    make_action(db, state="PENDING", reference="pipeline_step:run-1:a")
    make_action(db, state="CALLING", reference="pipeline_step:run-1:b")
    stored_event(db)

    def forbidden(*args, **kwargs):
        raise AssertionError("a scheduled tick must never execute or reconcile an external action")

    monkeypatch.setattr(ExternalActionService, "execute", forbidden)
    monkeypatch.setattr(ExternalActionService, "reconcile", forbidden)
    monkeypatch.setattr(ExternalActionService, "begin_call", forbidden)

    drained = drain(Worker(name="w", settings=SETTINGS, clock=lambda: NOW), db)

    assert drained == 3 and {job.status for job in ticks(db)} == {JobStatus.COMPLETED}


def test_a_failing_maintenance_step_does_not_stop_the_worker_from_claiming_work(db: Session, monkeypatch):
    queue = JobQueue(db)
    queue.enqueue(job_type="diagnostic.echo", payload={"hello": "world"})

    def broken(self, session):
        raise RuntimeError("the scheduler is broken")

    monkeypatch.setattr(RecurringScheduler, "enqueue_due", broken)

    handled = Worker(name="w", settings=SETTINGS, clock=lambda: NOW).run_once(db)

    assert handled is not None and handled.type == "diagnostic.echo"
    db.expire_all()
    assert db.get(Job, handled.id).status == JobStatus.COMPLETED


# --- La purga -------------------------------------------------------------------------------------------------------


def completed_job(
    db: Session, *, key: str | None, job_type: str, finished: datetime.datetime, status: str = "done"
) -> Job:
    queue = JobQueue(db)
    job = queue.enqueue(job_type=job_type, payload={}, idempotency_key=key)
    claimed = queue.claim(worker="w")
    assert claimed is not None and claimed.id == job.id
    if status == "done":
        queue.complete(job.id, worker="w", detail={"ok": True})
        db.execute(update(Job).where(Job.id == job.id).values(completed_at=finished))
    else:
        queue.fail(job.id, worker="w", error="boom")
        db.execute(update(Job).where(Job.id == job.id).values(status="FAILED", failed_at=finished, max_attempts=1))
    db.commit()
    return job


def test_the_purge_removes_old_completed_ticks_with_their_history_and_nothing_else(db: Session):
    retention = datetime.timedelta(days=SETTINGS.reconcile_tick_retention_days)
    old = NOW - retention - datetime.timedelta(days=1)
    recent = NOW - datetime.timedelta(hours=1)
    doomed = completed_job(db, key=tick_key(RECONCILE_ACTIONS, 1), job_type=RECONCILE_ACTIONS, finished=old)
    kept = {
        "recent tick": completed_job(
            db, key=tick_key(RECONCILE_ACTIONS, 2), job_type=RECONCILE_ACTIONS, finished=recent
        ),
        "old failed tick": completed_job(
            db, key=tick_key(RECONCILE_ACTIONS, 3), job_type=RECONCILE_ACTIONS, finished=old, status="failed"
        ),
        "old completed, not a tick": completed_job(db, key="research:run-1", job_type="diagnostic.echo", finished=old),
        "old completed, no key": completed_job(db, key=None, job_type="diagnostic.echo", finished=old),
    }
    assert attempts_of(db, doomed) == 1

    removed = RecurringScheduler(SETTINGS, clock=lambda: NOW).purge(db)

    db.expire_all()
    assert removed == 1 and db.get(Job, doomed.id) is None
    assert db.scalar(select(func.count(JobAttempt.id)).where(JobAttempt.job_id == doomed.id)) == 0
    assert db.scalar(select(func.count(JobEvent.id)).where(JobEvent.job_id == doomed.id)) == 0
    for label, job in kept.items():
        assert db.get(Job, job.id) is not None, f"the purge must not touch: {label}"


def test_the_purge_runs_at_most_once_an_hour_per_worker(db: Session):
    old = NOW - datetime.timedelta(days=30)
    first = completed_job(db, key=tick_key(RECONCILE_ACTIONS, 1), job_type=RECONCILE_ACTIONS, finished=old)
    scheduler = RecurringScheduler(SETTINGS, clock=lambda: NOW)
    assert scheduler.purge(db) == 1 and db.get(Job, first.id) is None
    second = completed_job(db, key=tick_key(RECONCILE_ACTIONS, 2), job_type=RECONCILE_ACTIONS, finished=old)

    assert scheduler.purge(db) == 0, "not again within the hour"
    assert db.get(Job, second.id) is not None
    assert RecurringScheduler(SETTINGS, clock=lambda: NOW + datetime.timedelta(hours=2)).purge(db) == 1


def test_the_purge_is_bounded_per_call(db: Session):
    old = NOW - datetime.timedelta(days=30)
    for n in range(5):
        completed_job(db, key=tick_key(RECONCILE_ACTIONS, n), job_type=RECONCILE_ACTIONS, finished=old)

    removed = JobQueue(db).purge_completed(key_prefix=KEY_PREFIX, older_than=NOW, limit=2)

    assert removed == 2 and len(ticks(db)) == 3
