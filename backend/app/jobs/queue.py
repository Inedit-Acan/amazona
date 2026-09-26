"""La cola de trabajos (Milestone 31, ADR 0009).

PostgreSQL es la cola y la fuente de verdad. Reclamar un trabajo es un
`SELECT ... FOR UPDATE SKIP LOCKED`, que es el patrón estándar para esto: dos
workers nunca se llevan la misma fila, y reclamar el trabajo y escribir su
intento ocurren en la **misma transacción**, así que no existe el estado en el
que un trabajo está reclamado pero nadie ha registrado quién.
"""

import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.ids import new_correlation_id
from app.db.models.job import Job, JobAttempt, JobEvent
from app.jobs.schemas import CLAIMABLE, TERMINAL, JobCancelledError, JobEventKind, JobStatus

#: Cuánto dura un arriendo si el tipo de trabajo no dice otra cosa. Pasado este
#: tiempo sin latido, el trabajo se considera huérfano.
DEFAULT_LEASE_SECONDS = 60

#: Espera entre reintentos: 5 s, 10 s, 20 s… con techo. Exponencial para no
#: machacar un servicio que ya está mal.
RETRY_BASE_SECONDS = 5
RETRY_MAX_SECONDS = 600


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


def backoff_seconds(attempt: int) -> int:
    """Espera antes del intento `attempt + 1`."""
    return min(RETRY_MAX_SECONDS, RETRY_BASE_SECONDS * (2 ** max(0, attempt - 1)))


class JobQueue:
    def __init__(self, db: Session) -> None:
        self._db = db

    # --- Escribir en la cola ----------------------------------------------

    def enqueue(
        self,
        *,
        job_type: str,
        payload: dict | None = None,
        correlation_id: str | None = None,
        idempotency_key: str | None = None,
        max_attempts: int = 3,
        available_at: datetime.datetime | None = None,
        created_by: str | None = None,
    ) -> Job:
        """Encola un trabajo. Con `idempotency_key`, encolar dos veces lo mismo
        devuelve el trabajo que ya existía en vez de duplicarlo: es lo que hace
        seguro reintentar una petición HTTP cuyo resultado no se conoce."""
        if idempotency_key:
            existing = self._db.query(Job).filter_by(idempotency_key=idempotency_key).one_or_none()
            if existing is not None:
                return existing

        when = available_at or _utcnow()
        job = Job(
            type=job_type,
            status=JobStatus.PENDING if when > _utcnow() else JobStatus.QUEUED,
            payload=payload or {},
            correlation_id=correlation_id or new_correlation_id(),
            idempotency_key=idempotency_key,
            max_attempts=max_attempts,
            available_at=when,
            created_by=created_by,
        )
        self._db.add(job)
        try:
            self._db.flush()
        except IntegrityError:
            # Carrera con otro proceso que encoló la misma clave entre nuestra
            # consulta y este flush. El que perdió se queda con el que ganó.
            self._db.rollback()
            if idempotency_key:
                found = self._db.query(Job).filter_by(idempotency_key=idempotency_key).one_or_none()
                if found is not None:
                    return found
            raise

        self._record(job, JobEventKind.ENQUEUED, {"type": job_type, "available_at": when.isoformat()})
        self._db.commit()
        self._db.refresh(job)
        return job

    # --- Leer de la cola ---------------------------------------------------

    def claim(self, *, worker: str, lease_seconds: int = DEFAULT_LEASE_SECONDS) -> Job | None:
        """Reclama el trabajo elegible más antiguo, o None si no hay ninguno.

        `SKIP LOCKED` es lo que permite varios workers: cada uno se salta las
        filas que otro tiene bloqueadas en vez de esperar por ellas.
        """
        now = _utcnow()
        statement = (
            select(Job)
            .where(Job.status.in_([s.value for s in CLAIMABLE]), Job.available_at <= now)
            .order_by(Job.available_at)
            .limit(1)
        )
        # SQLite (los tests) no conoce SKIP LOCKED y lo ignora sin error; en
        # PostgreSQL es lo que hace segura la concurrencia.
        if self._db.bind is not None and self._db.bind.dialect.name == "postgresql":
            statement = statement.with_for_update(skip_locked=True)

        job = self._db.execute(statement).scalars().first()
        if job is None:
            return None

        job.status = JobStatus.RUNNING
        job.attempt += 1
        job.started_at = job.started_at or now
        job.lease_worker = worker
        job.lease_expires_at = now + datetime.timedelta(seconds=lease_seconds)
        self._db.add(
            JobAttempt(job_id=job.id, number=job.attempt, worker=worker, status=JobStatus.RUNNING, started_at=now)
        )
        self._record(job, JobEventKind.CLAIMED, {"worker": worker, "attempt": job.attempt})
        self._db.commit()
        self._db.refresh(job)
        return job

    # --- Durante la ejecución ---------------------------------------------

    def heartbeat(self, job_id: str, *, worker: str, lease_seconds: int = DEFAULT_LEASE_SECONDS) -> None:
        """Extiende el arriendo. Lanza `JobCancelledError` si el trabajo ha
        dejado de ser nuestro —lo cancelaron, o el segador ya lo dio por
        muerto—, que es como un manejador cooperativo se entera de que debe
        parar."""
        job = self._db.get(Job, job_id)
        if job is None or job.status != JobStatus.RUNNING or job.lease_worker != worker:
            raise JobCancelledError(f"job {job_id} is no longer held by {worker}")

        job.lease_expires_at = _utcnow() + datetime.timedelta(seconds=lease_seconds)
        self._record(job, JobEventKind.HEARTBEAT, None)
        self._db.commit()

    # --- Terminar ----------------------------------------------------------

    def complete(self, job_id: str, *, worker: str, reference: str | None = None, detail: dict | None = None) -> Job:
        job = self._require_held(job_id, worker)
        now = _utcnow()
        job.status = JobStatus.COMPLETED
        job.completed_at = now
        job.result_reference = reference
        job.error = None
        self._release(job)
        self._finish_attempt(job, JobStatus.COMPLETED, None, now)
        self._record(job, JobEventKind.COMPLETED, detail or ({"reference": reference} if reference else None))
        self._db.commit()
        self._db.refresh(job)
        return job

    def fail(self, job_id: str, *, worker: str, error: str) -> Job:
        """Registra el fallo de un intento. Si quedan intentos, programa el
        siguiente con espera exponencial; si no, el trabajo queda en FAILED.

        Ese FAILED **es** la cola de mensajes muertos: la fila sigue ahí, con
        todos sus intentos y su último error, y se puede reencolar. Una cola
        aparte solo añadiría un sitio más donde mirar.
        """
        job = self._require_held(job_id, worker)
        now = _utcnow()
        message = error[:2000]
        self._finish_attempt(job, JobStatus.FAILED, message, now)
        job.error = message
        self._release(job)

        if job.attempt < job.max_attempts:
            wait = backoff_seconds(job.attempt)
            job.status = JobStatus.RETRYING
            job.available_at = now + datetime.timedelta(seconds=wait)
            self._record(
                job,
                JobEventKind.RETRY_SCHEDULED,
                {"attempt": job.attempt, "next_in_seconds": wait, "error": message},
            )
        else:
            job.status = JobStatus.FAILED
            job.failed_at = now
            self._record(job, JobEventKind.FAILED, {"attempt": job.attempt, "error": message})

        self._db.commit()
        self._db.refresh(job)
        return job

    def block(self, job_id: str, *, worker: str, reason: str) -> Job:
        """Deja el trabajo parado por una condición externa, sin gastar intentos.

        Lo usa un manejador que no puede seguir por algo que el tiempo no
        arregla —el kill switch apagado (Milestone 32), y en el 33 un veto legal
        o un presupuesto agotado—. El runtime no reclama `BLOCKED`, así que se
        queda quieto hasta que una persona lo reencola. El intento en curso se
        cierra como BLOCKED: no fue un fallo del manejador.
        """
        job = self._require_held(job_id, worker)
        now = _utcnow()
        self._finish_attempt(job, JobStatus.BLOCKED, reason[:2000], now)
        job.status = JobStatus.BLOCKED
        job.error = reason[:2000]
        self._release(job)
        self._record(job, JobEventKind.BLOCKED, {"reason": reason})
        self._db.commit()
        self._db.refresh(job)
        return job

    def cancel(self, job_id: str, *, actor: str | None = None) -> Job:
        """Cancela un trabajo. Si está en marcha, el worker se entera en su
        siguiente latido; su resultado ya no se aceptará."""
        job = self._db.get(Job, job_id)
        if job is None:
            raise LookupError(f"job {job_id} not found")
        if job.status in TERMINAL:
            return job

        job.status = JobStatus.CANCELLED
        job.cancelled_at = _utcnow()
        self._release(job)
        self._record(job, JobEventKind.CANCELLED, {"actor": actor} if actor else None)
        self._db.commit()
        self._db.refresh(job)
        return job

    # --- Mantenimiento -----------------------------------------------------

    def reap_expired_leases(self) -> list[Job]:
        """Devuelve a la cola los trabajos cuyo worker murió sin decir nada.

        Es la detección de worker muerto: no hace falta que los workers se
        registren ni se vigilen entre ellos, basta con que un arriendo vencido
        sea recuperable.
        """
        now = _utcnow()
        orphans = (
            self._db.query(Job)
            .filter(Job.status == JobStatus.RUNNING, Job.lease_expires_at.isnot(None), Job.lease_expires_at < now)
            .all()
        )
        for job in orphans:
            worker = job.lease_worker
            self._finish_attempt(job, JobStatus.FAILED, "lease expired", now)
            self._release(job)
            self._record(job, JobEventKind.LEASE_EXPIRED, {"worker": worker})
            if job.attempt < job.max_attempts:
                job.status = JobStatus.QUEUED
                job.available_at = now
                self._record(job, JobEventKind.REQUEUED, {"reason": "lease expired"})
            else:
                job.status = JobStatus.FAILED
                job.failed_at = now
                job.error = "lease expired and no attempts left"
                self._record(job, JobEventKind.FAILED, {"reason": "lease expired"})
        if orphans:
            self._db.commit()
        return orphans

    def release_due_retries(self) -> int:
        """Pasa a QUEUED lo que ya cumplió su espera. Lo hace el worker en cada
        vuelta; no hay ningún temporizador aparte que pueda pararse."""
        now = _utcnow()
        due = (
            self._db.query(Job)
            .filter(Job.status.in_([JobStatus.RETRYING, JobStatus.PENDING]), Job.available_at <= now)
            .all()
        )
        for job in due:
            job.status = JobStatus.QUEUED
        if due:
            self._db.commit()
        return len(due)

    def requeue(self, job_id: str, *, actor: str | None = None) -> Job:
        """Devuelve a la cola un trabajo fallado o cancelado, reiniciando sus
        intentos. Es cómo se vacía la cola de mensajes muertos."""
        job = self._db.get(Job, job_id)
        if job is None:
            raise LookupError(f"job {job_id} not found")

        job.status = JobStatus.QUEUED
        job.attempt = 0
        job.available_at = _utcnow()
        job.error = None
        job.failed_at = None
        job.cancelled_at = None
        self._release(job)
        self._record(job, JobEventKind.REQUEUED, {"actor": actor} if actor else None)
        self._db.commit()
        self._db.refresh(job)
        return job

    # --- Interno -----------------------------------------------------------

    def _require_held(self, job_id: str, worker: str) -> Job:
        job = self._db.get(Job, job_id)
        if job is None:
            raise LookupError(f"job {job_id} not found")
        if job.status != JobStatus.RUNNING or job.lease_worker != worker:
            # El resultado de un worker que ya perdió el trabajo se descarta: si
            # no, un worker zombi pisaría lo que hizo su sustituto.
            raise JobCancelledError(f"job {job_id} is no longer held by {worker}")
        return job

    def _release(self, job: Job) -> None:
        job.lease_worker = None
        job.lease_expires_at = None

    def _finish_attempt(self, job: Job, status: JobStatus, error: str | None, when: datetime.datetime) -> None:
        attempt = (
            self._db.query(JobAttempt)
            .filter_by(job_id=job.id, number=job.attempt)
            .order_by(JobAttempt.started_at.desc())
            .first()
        )
        if attempt is None:
            return
        attempt.status = status
        attempt.error = error
        attempt.finished_at = when

    def _record(self, job: Job, kind: JobEventKind, detail: dict | None) -> None:
        self._db.add(JobEvent(job_id=job.id, kind=kind, detail=detail))
