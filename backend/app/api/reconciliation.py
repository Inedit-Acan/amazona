"""El estado de la reconciliación programada, de solo lectura (Milestone 45, ADR 0029 §8).

Responde a qué hay abierto y desde cuándo, qué está `UNKNOWN_OUTCOME` esperando información o una persona, qué
eventos de pago esperan y cuáles han
topado su tope de intentos, y cuándo corrió cada trabajo. **Un `GET` no escribe nada** y no cierra, repite ni corrige
ninguna operación: las
decisiones sobre un resultado desconocido son de una persona (`resolve-action`, `retry-payment-event`).
"""

from typing import Any

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


class LedgerFindings(BaseModel):
    count: int
    #: Cada elemento dice qué comprobación (C1–C4) y de qué cobro o entrada; ni cuerpos ni hashes.
    items: list[dict[str, Any]]


class LedgerStatus(BaseModel):
    entries: int
    #: Divergencias entre el registro y el estado de pago: se informan, nunca se corrigen (ADR 0030 §12).
    divergences: LedgerFindings
    #: Cobros capturados antes del registro: informativo, no una divergencia (ADR 0030 §13).
    outside_ledger: LedgerFindings


class EvidenceTotal(BaseModel):
    currency: str
    event_type: str
    count: int
    amount: str


class EvidenceItem(BaseModel):
    id: str
    status: str
    event_type: str
    provider: str
    amount: str
    currency: str
    payment_id: str | None
    refund_id: str | None
    note: str | None
    occurred_at: str
    age_seconds: int


class PendingEvidence(BaseModel):
    count: int
    by_currency: list[EvidenceTotal]
    items: list[EvidenceItem]


class RevenueStatus(BaseModel):
    ledger: LedgerStatus
    #: Dinero de eventos `CONFLICT` o `UNMATCHED`: visible, y **no** ingreso (ADR 0030 §4).
    pending_evidence: PendingEvidence


class ReconciliationStatus(BaseModel):
    enabled: bool
    settings: SettingsView
    actions: ActionsStatus
    events: EventsStatus
    runs: dict[str, LastRun | None]
    revenue: RevenueStatus


@router.get("/status", response_model=ReconciliationStatus)
def reconciliation_status(
    db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
) -> ReconciliationStatus:
    return ReconciliationStatus.model_validate(build_status(db, settings))
