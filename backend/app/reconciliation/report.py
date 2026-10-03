"""El estado de la reconciliación, de **solo lectura** (Milestone 45, ADR 0029 §8).

No cierra nada, no corrige nada y no escribe nada (un `GET` no escribe: I10). Responde a: ¿qué está abierto y desde
cuándo?, ¿qué está
`UNKNOWN_OUTCOME` y espera información o una persona?, ¿qué eventos esperan, y cuáles han topado y esperan a una
persona?, ¿cuándo corrió cada
trabajo y está encendido el disparador?

Las edades se miden así: `PENDING` desde su última escritura; `CALLING` y `UNKNOWN_OUTCOME` desde que **empezó la
llamada** (la última escritura si
faltara): es el instante que importa para saber si el proveedor ya debería haberse asentado.
"""

import datetime
from collections.abc import Callable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.actions.contract import ActionStatus
from app.core.config import PROVISIONAL_EXTERNAL_CALL_MAX_SECONDS, Settings
from app.db.models.external_action import ExternalAction
from app.db.models.job import Job
from app.db.models.payment import PaymentEvent
from app.jobs.recurring import RECONCILE_JOB_TYPES, tick_prefix
from app.payments.domain import EventProcessing
from app.revenue.check import check_ledger
from app.revenue.evidence import pending_economic_evidence

#: Cuántos elementos concretos lista el estado (el resto se cuenta, no se lista).
LISTED_UNKNOWN = 20
LISTED_CAPPED = 50


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


def _aware(value: datetime.datetime) -> datetime.datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=datetime.UTC)


def _age(now: datetime.datetime, since: datetime.datetime | None) -> int | None:
    return None if since is None else max(0, int((now - _aware(since)).total_seconds()))


def build_status(db: Session, settings: Settings, *, now: datetime.datetime | None = None) -> dict:
    """Una fotografía de lo que la reconciliación tiene delante. Solo `SELECT`."""
    moment = now or _utcnow()
    return {
        "enabled": settings.reconciliation_enabled,
        "settings": _settings_view(settings),
        "actions": _actions(db, moment),
        "events": _events(db, settings, moment),
        "runs": _runs(db),
        #: El registro de ingresos verificados (ADR 0030 §12): reconciliación con el estado de pago y la
        #: evidencia económica pendiente de revisión. Solo lectura: no corrige nada.
        "revenue": {
            "ledger": check_ledger(db),
            "pending_evidence": pending_economic_evidence(db, now=moment),
        },
    }


def _settings_view(settings: Settings) -> dict:
    ceiling = settings.effective_external_call_max_seconds
    return {
        "actions_interval_seconds": settings.reconcile_actions_interval_seconds,
        "actions_older_than_minutes": settings.reconcile_actions_older_than_minutes,
        "events_interval_seconds": settings.reconcile_events_interval_seconds,
        "events_older_than_minutes": settings.reconcile_events_older_than_minutes,
        "event_max_attempts": settings.reconcile_event_max_attempts,
        "external_call_max_seconds": ceiling,
        #: Cierto cuando el techo es el valor provisional de simulación: no es contractual ni de ningún proveedor.
        "external_call_max_seconds_is_provisional": settings.external_call_max_seconds is None
        and ceiling == PROVISIONAL_EXTERNAL_CALL_MAX_SECONDS,
    }


def _actions(db: Session, now: datetime.datetime) -> dict:
    since = func.coalesce(ExternalAction.call_started_at, ExternalAction.updated_at)
    by_status: dict[str, dict] = {}
    for status in (ActionStatus.PENDING, ActionStatus.CALLING, ActionStatus.UNKNOWN_OUTCOME):
        reference = ExternalAction.updated_at if status is ActionStatus.PENDING else since
        count, oldest = db.execute(
            select(func.count(ExternalAction.id), func.min(reference)).where(ExternalAction.status == status.value)
        ).one()
        by_status[status.value] = {"count": int(count), "oldest_age_seconds": _age(now, oldest)}
    unknown = db.execute(
        select(
            ExternalAction.id, ExternalAction.reference, ExternalAction.operation, ExternalAction.provider,
            since.label("since")
        )
        .where(ExternalAction.status == ActionStatus.UNKNOWN_OUTCOME.value)
        .order_by(since, ExternalAction.id)
        .limit(LISTED_UNKNOWN)
    ).all()
    return {
        "open": by_status,
        "unknown_outcomes": [
            {
                "id": row.id,
                "reference": row.reference,
                "operation": row.operation,
                "provider": row.provider,
                "age_seconds": _age(now, row.since),
            }
            for row in unknown
        ],
    }


def _events(db: Session, settings: Settings, now: datetime.datetime) -> dict:
    cap = settings.reconcile_event_max_attempts
    received = EventProcessing.RECEIVED.value
    waiting_count, waiting_oldest = db.execute(
        select(func.count(PaymentEvent.id), func.min(PaymentEvent.received_at)).where(
            PaymentEvent.processing_status == received, PaymentEvent.reconcile_attempts < cap
        )
    ).one()
    capped_count = db.scalar(
        select(func.count(PaymentEvent.id)).where(
            PaymentEvent.processing_status == received, PaymentEvent.reconcile_attempts >= cap
        )
    )
    capped = db.scalars(
        select(PaymentEvent)
        .where(PaymentEvent.processing_status == received, PaymentEvent.reconcile_attempts >= cap)
        .order_by(PaymentEvent.received_at, PaymentEvent.id)
        .limit(LISTED_CAPPED)
    ).all()
    return {
        "waiting": {"count": int(waiting_count), "oldest_age_seconds": _age(now, waiting_oldest)},
        "capped": {
            "count": int(capped_count or 0),
            "items": [
                {
                    "id": event.id,
                    "provider": event.provider,
                    "event_type": event.event_type,
                    "attempts": event.reconcile_attempts,
                    "age_seconds": _age(now, event.received_at),
                    "last_error": event.last_reconcile_error,
                    "last_reconcile_at": event.last_reconcile_at.isoformat() if event.last_reconcile_at else None,
                }
                for event in capped
            ],
        },
    }


def _runs(db: Session) -> dict:
    runs: dict[str, dict | None] = {}
    last: Callable[[str], Job | None] = lambda job_type: db.scalars(  # noqa: E731
        select(Job)
        .where(Job.idempotency_key.like(f"{tick_prefix(job_type)}%"))
        .order_by(Job.created_at.desc(), Job.id)
        .limit(1)
    ).first()
    for job_type in RECONCILE_JOB_TYPES:
        job = last(job_type)
        runs[job_type] = (
            None
            if job is None
            else {
                "status": str(job.status),
                "created_at": job.created_at.isoformat(),
                "completed_at": job.completed_at.isoformat() if job.completed_at else None,
            }
        )
    return runs
