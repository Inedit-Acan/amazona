"""El worker: reclama trabajos y los ejecuta (Milestone 31, ADR 0009).

    python -m app.jobs.worker

Se puede levantar más de uno: el reclamo es `SKIP LOCKED`, así que dos workers
nunca se llevan la misma fila. Cada vuelta hace tres cosas —liberar reintentos
vencidos, segar arriendos muertos y reclamar— para que no haga falta ningún
proceso de mantenimiento aparte que alguien pueda olvidar arrancar.
"""

import argparse
import logging
import os
import signal
import socket
import time
import types

from sqlalchemy.orm import Session

from app.core.ids import new_id
from app.core.logging import configure_logging, set_correlation_id
from app.db.models.job import Job
from app.db.session import get_session_factory
from app.jobs import handlers as _handlers  # noqa: F401 - importar registra los manejadores
from app.jobs.queue import DEFAULT_LEASE_SECONDS, JobQueue
from app.jobs.registry import UnknownJobTypeError, resolve
from app.jobs.schemas import JobBlockedError, JobCancelledError, JobContext

logger = logging.getLogger(__name__)

#: Cuánto espera el worker cuando no hay nada que hacer. Corto porque la cola es
#: la base de datos y consultarla es barato; la latencia de arranque de un
#: trabajo nunca pasa de esto.
IDLE_SLEEP_SECONDS = 2.0


def worker_name() -> str:
    """Nombre legible y único: host, pid y un sufijo, para distinguir dos
    workers en la misma máquina en la bitácora de un trabajo."""
    return f"{socket.gethostname()}:{os.getpid()}:{new_id()[:8]}"


class Worker:
    def __init__(self, name: str | None = None, lease_seconds: int = DEFAULT_LEASE_SECONDS) -> None:
        self.name = name or worker_name()
        self.lease_seconds = lease_seconds
        self._stopping = False

    def stop(self) -> None:
        self._stopping = True

    # --- Una vuelta --------------------------------------------------------

    def run_once(self, db: Session) -> Job | None:
        """Mantenimiento y, si hay algo, un trabajo. Devuelve el trabajo tratado
        o None. Separado del bucle para poder probarlo sin hilos ni relojes."""
        queue = JobQueue(db)
        queue.release_due_retries()
        queue.reap_expired_leases()

        job = queue.claim(worker=self.name, lease_seconds=self.lease_seconds)
        if job is None:
            return None

        self._execute(queue, db, job)
        return job

    def _execute(self, queue: JobQueue, db: Session, job: Job) -> None:
        set_correlation_id(job.correlation_id)
        context = JobContext(
            job_id=job.id,
            correlation_id=job.correlation_id,
            attempt=job.attempt,
            heartbeat=lambda: queue.heartbeat(job.id, worker=self.name, lease_seconds=self.lease_seconds),
            started_at=job.started_at or job.created_at,
        )

        try:
            handler = resolve(job.type)
        except UnknownJobTypeError as exc:
            # Un tipo desconocido no se arregla esperando: es un error de
            # despliegue, así que se agotan los intentos de golpe.
            logger.error("job %s has an unknown type %s", job.id, job.type)
            job.attempt = job.max_attempts
            db.commit()
            queue.fail(job.id, worker=self.name, error=str(exc))
            return

        try:
            result = handler(job.payload or {}, context, db)
        except JobCancelledError:
            # Nos lo quitaron mientras trabajábamos: no hay nada que reportar,
            # quien lo tenga ahora decidirá.
            logger.info("job %s was taken away from %s mid-flight", job.id, self.name)
            db.rollback()
            return
        except JobBlockedError as exc:
            # Una condición externa impide seguir y esperar no la arregla: se
            # queda en BLOCKED sin gastar intentos, hasta que alguien la levante
            # y lo reencole. Milestone 32 (kill switch), Milestone 33 (gates).
            logger.info("job %s is blocked: %s", job.id, exc.reason)
            try:
                queue.block(job.id, worker=self.name, reason=exc.reason)
            except JobCancelledError:
                logger.info("job %s was taken away before it could be blocked", job.id)
                db.rollback()
            return
        except Exception as exc:  # noqa: BLE001 - cualquier fallo del manejador es un intento fallido
            logger.exception("job %s failed on attempt %s", job.id, job.attempt)
            db.rollback()
            try:
                queue.fail(job.id, worker=self.name, error=f"{type(exc).__name__}: {exc}")
            except JobCancelledError:
                logger.info("job %s was cancelled before its failure could be recorded", job.id)
            return

        try:
            queue.complete(job.id, worker=self.name, reference=result.reference, detail=result.detail)
        except JobCancelledError:
            # El manejador terminó pero el trabajo ya no era nuestro. Se
            # descarta a propósito: aceptarlo pisaría lo que hizo su sustituto.
            logger.warning("job %s finished but %s no longer held it; result discarded", job.id, self.name)
            db.rollback()

    # --- El bucle ----------------------------------------------------------

    def run_forever(self, sleep_seconds: float = IDLE_SLEEP_SECONDS) -> None:
        factory = get_session_factory()
        logger.info("worker %s started", self.name)
        while not self._stopping:
            db = factory()
            try:
                handled = self.run_once(db)
            except Exception:  # noqa: BLE001 - una vuelta rota no puede tumbar al worker
                logger.exception("worker %s failed a cycle", self.name)
                db.rollback()
                handled = None
            finally:
                db.close()

            if handled is None and not self._stopping:
                time.sleep(sleep_seconds)
        logger.info("worker %s stopped", self.name)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.jobs.worker", description=__doc__)
    parser.add_argument("--name", default=None, help="nombre del worker (por defecto host:pid:sufijo)")
    parser.add_argument("--lease-seconds", type=int, default=DEFAULT_LEASE_SECONDS)
    parser.add_argument("--once", action="store_true", help="trata un trabajo y termina")
    args = parser.parse_args(argv)

    configure_logging("INFO")
    worker = Worker(name=args.name, lease_seconds=args.lease_seconds)

    def shutdown(signum: int, frame: types.FrameType | None) -> None:
        # Termina el trabajo que tenga entre manos y no reclama otro: matarlo a
        # mitad solo conseguiría que el segador lo reencolara.
        logger.info("worker %s got signal %s; finishing current job", worker.name, signum)
        worker.stop()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    if args.once:
        db = get_session_factory()()
        try:
            worker.run_once(db)
        finally:
            db.close()
        return 0

    worker.run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
