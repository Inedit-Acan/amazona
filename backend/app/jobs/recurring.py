"""Trabajos recurrentes dentro del mantenimiento del worker (Milestone 45, ADR 0029 §2).

El runtime (ADR 0009) solo ejecuta lo que alguien encola; ningún trabajo se programaba solo. Esto añade el
**disparador**, sin tabla de horarios,
ni proceso aparte, ni Redis, ni n8n:

- cada tipo recurrente tiene un intervalo; el tiempo se divide en **cubos** de ese tamaño (`cubo = floor(ahora /
intervalo)`);
- cada vuelta de cada worker intenta encolar el tick del cubo actual con `idempotency_key =
"recurring:{tipo}:{cubo}"`. La columna `jobs.idempotency_key`
  es única: con N workers encolando a la vez, o un mismo worker repitiendo la vuelta, **solo existe un trabajo por
  tipo y cubo**;
- un worker recuerda el último cubo que ya encoló para no consultar la base en cada vuelta de dos segundos;
- un tick perdido (el worker murió, el trabajo falló) no se repone: el siguiente cubo encola otro. Los barridos son
idempotentes (compare-and-set por fila),
  así que ejecutarlos dos veces o dos a la vez no puede duplicar nada;
- con `reconciliation_enabled = false` no se encola nada.

Los trabajos recurrentes completados se **purgan** pasados `reconcile_tick_retention_days` días (con sus intentos y
eventos): son miles de filas al día.
"""

import datetime
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.jobs.queue import JobQueue

RECONCILE_ACTIONS = "reconcile.actions"
RECONCILE_PAYMENT_EVENTS = "reconcile.payment_events"
RECONCILE_REPORT = "reconcile.report"
RECONCILE_JOB_TYPES = (RECONCILE_ACTIONS, RECONCILE_PAYMENT_EVENTS, RECONCILE_REPORT)

KEY_PREFIX = "recurring:"
#: Un tick que falla se reintenta dos veces con espera; el siguiente cubo encola otro de todos modos.
TICK_MAX_ATTEMPTS = 3
#: La purga se intenta como mucho una vez por hora y worker.
PURGE_EVERY = datetime.timedelta(hours=1)


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


@dataclass(frozen=True)
class RecurringJob:
    job_type: str
    interval_seconds: int


def recurring_jobs(settings: Settings) -> list[RecurringJob]:
    """Lo que hay que encolar de forma recurrente con estos ajustes. Con la reconciliación apagada, nada."""
    if not settings.reconciliation_enabled:
        return []
    return [
        RecurringJob(RECONCILE_ACTIONS, settings.reconcile_actions_interval_seconds),
        RecurringJob(RECONCILE_PAYMENT_EVENTS, settings.reconcile_events_interval_seconds),
        RecurringJob(RECONCILE_REPORT, settings.reconcile_actions_interval_seconds),
    ]


def bucket_of(now: datetime.datetime, interval_seconds: int) -> int:
    """El cubo temporal de `now`: dos instantes del mismo intervalo caen en el mismo cubo, en cualquier proceso."""
    return int(now.timestamp() // interval_seconds)


def tick_prefix(job_type: str) -> str:
    return f"{KEY_PREFIX}{job_type}:"


def tick_key(job_type: str, bucket: int) -> str:
    return f"{tick_prefix(job_type)}{bucket}"


class RecurringScheduler:
    def __init__(self, settings: Settings, *, clock: Callable[[], datetime.datetime] = _utcnow) -> None:
        self._settings = settings
        self._clock = clock
        self._last_bucket: dict[str, int] = {}
        self._last_purge: datetime.datetime | None = None

    def enqueue_due(self, db: Session) -> list[str]:
        """Encola el tick del cubo actual de cada tipo recurrente y devuelve las claves tratadas (nuevas o ya
        existentes)."""
        now = self._clock()
        handled: list[str] = []
        for spec in recurring_jobs(self._settings):
            bucket = bucket_of(now, spec.interval_seconds)
            if self._last_bucket.get(spec.job_type) == bucket:
                continue  # este worker ya lo encoló (o lo encontró ya encolado) en este cubo
            key = tick_key(spec.job_type, bucket)
            JobQueue(db).enqueue(
                job_type=spec.job_type,
                payload={"bucket": bucket, "interval_seconds": spec.interval_seconds},
                idempotency_key=key,
                max_attempts=TICK_MAX_ATTEMPTS,
                created_by="scheduler",
            )
            self._last_bucket[spec.job_type] = bucket
            handled.append(key)
        return handled

    def purge(self, db: Session) -> int:
        """Borra los trabajos recurrentes completados hace más de la retención. A lo sumo una vez por hora y worker."""
        now = self._clock()
        if self._last_purge is not None and now - self._last_purge < PURGE_EVERY:
            return 0
        self._last_purge = now
        cutoff = now - datetime.timedelta(days=self._settings.reconcile_tick_retention_days)
        return JobQueue(db).purge_completed(key_prefix=KEY_PREFIX, older_than=cutoff)
