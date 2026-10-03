"""El estado de la reconciliación programada, de solo lectura (Milestone 45, ADR 0029 §8).

Responde a qué hay abierto y desde cuándo, qué está `UNKNOWN_OUTCOME` esperando información o una persona, qué
eventos de pago esperan y cuáles han
topado su tope de intentos, y cuándo corrió cada trabajo. **Un `GET` no escribe nada** y no cierra, repite ni corrige
ninguna operación: las
decisiones sobre un resultado desconocido son de una persona (`resolve-action`, `retry-payment-event`).
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.reconciliation.report import build_status

router = APIRouter(prefix="/api/reconciliation", tags=["reconciliation"])


class OpenState(BaseModel):
    count: int
    oldest_age_seconds: int | None


class UnknownOutcome(BaseModel):
    id: str
    reference: str
    operation: str
    provider: str
    age_seconds: int | None


class ActionsStatus(BaseModel):
    #: `PENDING`, `CALLING` y `UNKNOWN_OUTCOME`, con cuántas hay y la edad de la más antigua.
    open: dict[str, OpenState]
    unknown_outcomes: list[UnknownOutcome]


class CappedEvent(BaseModel):
    id: str
    provider: str
    event_type: str
    attempts: int
    age_seconds: int | None
    last_error: str | None
    last_reconcile_at: str | None


class WaitingEvents(BaseModel):
    count: int
    oldest_age_seconds: int | None


class CappedEvents(BaseModel):
    count: int
    items: list[CappedEvent]


class EventsStatus(BaseModel):
    waiting: WaitingEvents
    capped: CappedEvents


class LastRun(BaseModel):
    status: str
    created_at: str
    completed_at: str | None


class SettingsView(BaseModel):
    actions_interval_seconds: int
    actions_older_than_minutes: int
    events_interval_seconds: int
    events_older_than_minutes: int
    event_max_attempts: int
    #: `null` si hace falta configurarlo y no se ha hecho.
    external_call_max_seconds: int | None
    #: Cierto cuando es el valor provisional de simulación: no es contractual ni de ningún proveedor.
    external_call_max_seconds_is_provisional: bool


class ReconciliationStatus(BaseModel):
    enabled: bool
    settings: SettingsView
    actions: ActionsStatus
    events: EventsStatus
    runs: dict[str, LastRun | None]


@router.get("/status", response_model=ReconciliationStatus)
def reconciliation_status(
    db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
) -> ReconciliationStatus:
    return ReconciliationStatus.model_validate(build_status(db, settings))
