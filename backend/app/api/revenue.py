"""Los agregados del registro de ingresos verificados, **solo lectura** (Milestone 45, ADR 0030).

Tres `GET` sobre el registro: un resumen por moneda (lo verificado, lo que está en revisión y la evidencia
pendiente, cada cosa por separado), una serie por día o por mes y una lista paginada de las entradas que explican
cualquier cifra. **Un `GET` no escribe nada.** Ninguna respuesta lleva margen, beneficio, coste, impuestos, IVA/OSS,
caja ni comisiones: el registro no puede demostrarlos (ver `scope`). Los importes son texto exacto, nunca un número
JSON (que sería un `float`).

Qué es cada cifra, cómo se trata la moneda y por qué: `app/revenue/aggregates.py` y el ADR 0030.
"""

import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.revenue import aggregates
from app.revenue.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE

router = APIRouter(prefix="/api/revenue", tags=["revenue"])


class Scope(BaseModel):
    is_accounting_ledger: bool
    basis: str
    #: Lo que estas cifras **no** contienen ni calculan.
    excludes: list[str]


class VerifiedRow(BaseModel):
    currency: str
    revenue: str
    refunds: str
    net: str
    captures: int
    refund_count: int


class UnderReviewRow(BaseModel):
    currency: str
    classification: str
    received: str
    refunded: str
    outstanding: str
    receipts: int
    refund_count: int


class EvidenceTotal(BaseModel):
    currency: str
    event_type: str
    count: int
    amount: str


class PendingEvidenceTotals(BaseModel):
    count: int
    by_currency: list[EvidenceTotal]


class ConsolidatedEur(BaseModel):
    currency: str
    revenue: str
    refunds: str
    net: str
    under_review_outstanding: str


class NonAggregable(BaseModel):
    currency: str
    reason: str


class SummaryOut(BaseModel):
    period: dict[str, str | None]
    entries: int
    #: Ingreso y reembolso verificados (`ORDER_PAYMENT`), por moneda.
    verified: list[VerifiedRow]
    #: Dinero en revisión (`DUPLICATE_RECEIPT`, `MISMATCH_RECEIPT`), por moneda y clase; nunca suma al verificado.
    under_review: list[UnderReviewRow]
    #: Eventos de dinero sin asentar (`CONFLICT`, `UNMATCHED`): ni ingreso ni reembolso.
    pending_evidence: PendingEvidenceTotals
    #: Solo EUR; `null` si no hay ninguna entrada en EUR en el periodo («Sin datos»).
    consolidated_eur: ConsolidatedEur | None
    non_aggregable_currencies: list[NonAggregable]
    scope: Scope


class SeriesBucket(BaseModel):
    bucket: str
    currency: str
    revenue: str
    refunds: str
    net: str
    under_review_received: str
    under_review_refunded: str
    entries: int


class SeriesOut(BaseModel):
    granularity: str
    period: dict[str, str | None]
    buckets: list[SeriesBucket]
    scope: Scope


class EntryOut(BaseModel):
    id: str
    kind: str
    classification: str
    payment_event_id: str
    payment_id: str
    order_id: str
    refund_id: str | None
    capture_entry_id: str | None
    amount: str
    currency: str
    occurred_at: str
    recorded_at: str


class EntriesPageOut(BaseModel):
    items: list[EntryOut]
    has_more: bool
    next_cursor: str | None


def _utc(value: datetime.datetime | None) -> datetime.datetime | None:
    """Una fecha sin zona se toma como UTC y una con otra zona se lleva a UTC: todo el registro es UTC."""
    if value is None:
        return None
    return value.replace(tzinfo=datetime.UTC) if value.tzinfo is None else value.astimezone(datetime.UTC)


def _period(start: datetime.datetime | None, end: datetime.datetime | None) -> aggregates.Period:
    return aggregates.Period(start=_utc(start), end=_utc(end))


def _stamp(value: datetime.datetime) -> str:
    """Siempre en UTC: PostgreSQL devuelve las fechas en la zona de la sesión y SQLite sin zona (mismo instante)."""
    return _utc(value).isoformat()  # type: ignore[union-attr]


@router.get("/summary", response_model=SummaryOut)
def revenue_summary(
    start: datetime.datetime | None = Query(None, alias="from"),
    end: datetime.datetime | None = Query(None, alias="to"),
    db: Session = Depends(get_db),
) -> SummaryOut:
    return SummaryOut.model_validate(aggregates.summary(db, _period(start, end)))


@router.get("/series", response_model=SeriesOut)
def revenue_series(
    granularity: str = Query("day"),
    start: datetime.datetime | None = Query(None, alias="from"),
    end: datetime.datetime | None = Query(None, alias="to"),
    db: Session = Depends(get_db),
) -> SeriesOut:
    now = datetime.datetime.now(datetime.UTC)
    period = aggregates.resolve_series_period(granularity, _period(start, end), now=now)
    return SeriesOut.model_validate(aggregates.series(db, granularity=granularity, period=period))


@router.get("/entries", response_model=EntriesPageOut)
def revenue_entries(
    cursor: str | None = Query(None),
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    currency: str | None = Query(None, pattern="^[A-Z]{3}$"),
    classification: str | None = Query(None),
    kind: str | None = Query(None),
    start: datetime.datetime | None = Query(None, alias="from"),
    end: datetime.datetime | None = Query(None, alias="to"),
    db: Session = Depends(get_db),
) -> EntriesPageOut:
    page = aggregates.entries_page(
        db,
        period=_period(start, end),
        cursor=cursor,
        limit=limit,
        currency=currency,
        classification=classification,
        kind=kind,
    )
    return EntriesPageOut(
        items=[
            EntryOut(
                id=entry.id,
                kind=entry.kind,
                classification=entry.classification,
                payment_event_id=entry.payment_event_id,
                payment_id=entry.payment_id,
                order_id=entry.order_id,
                refund_id=entry.refund_id,
                capture_entry_id=entry.capture_entry_id,
                amount=aggregates.money(entry.amount),
                currency=entry.currency,
                occurred_at=_stamp(entry.occurred_at),
                recorded_at=_stamp(entry.recorded_at),
            )
            for entry in page.entries
        ],
        has_more=page.has_more,
        next_cursor=page.next_cursor,
    )
