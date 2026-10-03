"""Los agregados del registro de ingresos verificados, de **solo lectura** (Milestone 45, ADR 0030).

Todo lo verificado y todo lo que está en revisión sale **exclusivamente** del registro (`revenue_ledger_entries`); la
evidencia económica pendiente (`CONFLICT`/`UNMATCHED`) sale de `payment_events` porque, por decisión D1, nunca entra
en el registro, y se muestra **aparte**: no suma en ningún total. Aquí no hay escrituras ni confirmaciones.

## Qué es cada cifra

- **Ingreso verificado** (`revenue`): capturas `ORDER_PAYMENT`. **Reembolso verificado** (`refunds`): reembolsos que
  heredan `ORDER_PAYMENT`. **Neto**: la resta; puede ser negativo en un periodo (un reembolso de una captura anterior).
- **Dinero en revisión**: `DUPLICATE_RECEIPT` y `MISMATCH_RECEIPT`, cada una con sus reembolsos heredados.
  **Nunca** se suma al ingreso verificado ni se compensa con él (ADR 0030 L5): un reembolso reduce la clase de su
  captura y solo esa.
- **Evidencia pendiente**: dinero de eventos que no se pudieron asentar; ni ingreso ni reembolso.

## Moneda

Todo va **por moneda**; una moneda nunca se suma con otra. EUR es la única moneda de cálculo consolidado de M45
(decisión D3): el bloque `consolidated_eur` solo contiene EUR, y las demás monedas se listan como **no agregables**
porque no existe una conversión contable válida (no hay FX). Un importe es siempre un `Decimal` exacto devuelto como
texto; nunca `float`.

## Lo que no hay, a propósito

Ni margen, ni beneficio, ni coste, ni impuestos, ni IVA/OSS, ni caja, ni comisiones: el registro no puede demostrarlos
(ADR 0030 §15). La respuesta lo dice en `scope`.

## Tiempo

El periodo se mide por `occurred_at` (cuándo ocurrió el hecho según el proveedor, no cuándo llegó), en UTC: `from`
inclusivo y `to` exclusivo.
"""

import datetime
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import ColumnElement, func, literal, select, tuple_
from sqlalchemy.orm import Session

from app.core.errors import ValidationError
from app.db.models.revenue import RevenueLedgerEntry as Entry
from app.revenue.domain import Classification, EntryKind
from app.revenue.evidence import money, pending_evidence_totals
from app.revenue.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, EntryCursor

#: La única moneda en la que M45 consolida (decisión D3 del propietario). No es un ajuste ni sale de `Settings`.
CONSOLIDATION_CURRENCY = "EUR"

GRANULARITIES = ("day", "month")
#: Cuántos días abarca como máximo una serie diaria / una mensual, y cuántos por defecto: la salida está acotada.
MAX_SERIES_DAYS = {"day": 366, "month": 1096}
DEFAULT_SERIES_DAYS = {"day": 30, "month": 365}

UNDER_REVIEW = (Classification.DUPLICATE_RECEIPT.value, Classification.MISMATCH_RECEIPT.value)
_ZERO = Decimal("0.0000")
_PLACES = Decimal("0.0001")

#: Lo que estos agregados no son ni contienen. Se devuelve en cada respuesta para que ninguna pantalla lo invente.
SCOPE = {
    "is_accounting_ledger": False,
    "basis": "operational verified payment facts (ADR 0030); occurred_at in UTC, from inclusive, to exclusive",
    "excludes": ["costs", "margin", "profit", "taxes", "vat_oss", "cash", "gateway_fees", "fx_conversion"],
}


def _dec(value: object) -> Decimal:
    """Un importe de la base como `Decimal` exacto a la precisión de la columna (SQLite suma en coma flotante)."""
    return Decimal(str(value if value is not None else 0)).quantize(_PLACES)


@dataclass(frozen=True)
class Period:
    """Un rango de `occurred_at`: `start` inclusivo, `end` exclusivo. Cualquiera de los dos puede faltar."""

    start: datetime.datetime | None = None
    end: datetime.datetime | None = None

    def __post_init__(self) -> None:
        for value in (self.start, self.end):
            if value is not None and value.tzinfo is None:
                raise ValueError("a period is in UTC: its limits carry a time zone")
        # Un límite con otra zona horaria se lleva a UTC: todo el registro y toda comparación son UTC.
        if self.start is not None:
            object.__setattr__(self, "start", self.start.astimezone(datetime.UTC))
        if self.end is not None:
            object.__setattr__(self, "end", self.end.astimezone(datetime.UTC))
        if self.start is not None and self.end is not None and self.start >= self.end:
            raise ValidationError("the period is empty: `from` must be earlier than `to`")

    def conditions(self) -> list[ColumnElement[bool]]:
        found: list[ColumnElement[bool]] = []
        if self.start is not None:
            found.append(Entry.occurred_at >= self.start)
        if self.end is not None:
            found.append(Entry.occurred_at < self.end)
        return found

    def view(self) -> dict:
        return {
            "from": self.start.isoformat() if self.start else None,
            "to": self.end.isoformat() if self.end else None,
            "basis": "occurred_at",
        }


class _Cell:
    """Lo que suman las entradas de una moneda, una clase y un tipo: cuántas y cuánto."""

    __slots__ = ("count", "total")

    def __init__(self) -> None:
        self.count = 0
        self.total = _ZERO


def _cells(rows) -> dict[tuple[str, str, str], _Cell]:
    cells: dict[tuple[str, str, str], _Cell] = {}
    for currency, classification, kind, count, total in rows:
        cell = cells.setdefault((currency, classification, kind), _Cell())
        cell.count += int(count)
        cell.total += _dec(total)
    return cells


def _cell(cells: dict, currency: str, classification: str, kind: EntryKind) -> _Cell:
    return cells.get((currency, classification, kind.value)) or _Cell()


def summary(db: Session, period: Period) -> dict:
    """Lo verificado, lo que está en revisión y la evidencia pendiente, por moneda, en un periodo. Solo `SELECT`."""
    rows = db.execute(
        select(Entry.currency, Entry.classification, Entry.kind, func.count(Entry.id), func.sum(Entry.amount))
        .where(*period.conditions())
        .group_by(Entry.currency, Entry.classification, Entry.kind)
        .order_by(Entry.currency, Entry.classification, Entry.kind)
    ).all()
    cells = _cells(rows)
    currencies = sorted({currency for currency, _, _ in cells})

    verified = []
    under_review = []
    for currency in currencies:
        captured = _cell(cells, currency, Classification.ORDER_PAYMENT.value, EntryKind.CAPTURE)
        refunded = _cell(cells, currency, Classification.ORDER_PAYMENT.value, EntryKind.REFUND)
        if captured.count or refunded.count:
            verified.append(
                {
                    "currency": currency,
                    "revenue": money(captured.total),
                    "refunds": money(refunded.total),
                    "net": money(captured.total - refunded.total),
                    "captures": captured.count,
                    "refund_count": refunded.count,
                }
            )
        for classification in UNDER_REVIEW:
            received = _cell(cells, currency, classification, EntryKind.CAPTURE)
            returned = _cell(cells, currency, classification, EntryKind.REFUND)
            if received.count or returned.count:
                under_review.append(
                    {
                        "currency": currency,
                        "classification": classification,
                        "received": money(received.total),
                        "refunded": money(returned.total),
                        "outstanding": money(received.total - returned.total),
                        "receipts": received.count,
                        "refund_count": returned.count,
                    }
                )

    pending = pending_evidence_totals(db, start=period.start, end=period.end)
    foreign = sorted(({*currencies} | {row["currency"] for row in pending["by_currency"]}) - {CONSOLIDATION_CURRENCY})
    return {
        "period": period.view(),
        "entries": sum(cell.count for cell in cells.values()),
        "verified": verified,
        "under_review": under_review,
        "pending_evidence": pending,
        "consolidated_eur": _consolidated(cells) if CONSOLIDATION_CURRENCY in currencies else None,
        "non_aggregable_currencies": [
            {"currency": currency, "reason": "no valid accounting conversion exists yet: shown separately, never added"}
            for currency in foreign
        ],
        "scope": SCOPE,
    }


def _consolidated(cells: dict) -> dict:
    """Solo EUR. Si no hay ninguna entrada en EUR en el periodo, este bloque no existe («Sin datos»)."""
    eur = CONSOLIDATION_CURRENCY
    captured = _cell(cells, eur, Classification.ORDER_PAYMENT.value, EntryKind.CAPTURE).total
    refunded = _cell(cells, eur, Classification.ORDER_PAYMENT.value, EntryKind.REFUND).total
    outstanding = sum(
        (
            _cell(cells, eur, classification, EntryKind.CAPTURE).total
            - _cell(cells, eur, classification, EntryKind.REFUND).total
            for classification in UNDER_REVIEW
        ),
        _ZERO,
    )
    return {
        "currency": eur,
        "revenue": money(captured),
        "refunds": money(refunded),
        "net": money(captured - refunded),
        "under_review_outstanding": money(outstanding),
    }


def resolve_series_period(granularity: str, period: Period, *, now: datetime.datetime) -> Period:
    """Pone los límites por defecto de una serie y comprueba que la ventana está acotada."""
    if granularity not in GRANULARITIES:
        raise ValidationError(f"granularity must be one of {', '.join(GRANULARITIES)}")
    end = period.end or now
    start = period.start or end - datetime.timedelta(days=DEFAULT_SERIES_DAYS[granularity])
    resolved = Period(start=start, end=end)
    if end - start > datetime.timedelta(days=MAX_SERIES_DAYS[granularity]):
        raise ValidationError(
            f"a {granularity} series covers at most {MAX_SERIES_DAYS[granularity]} days: narrow `from` and `to`"
        )
    return resolved


def _bucket(db: Session, granularity: str):
    """El cubo temporal en UTC. `date_trunc` en PostgreSQL; `strftime` en SQLite (el resultado se normaliza igual)."""
    if db.get_bind().dialect.name == "postgresql":
        return func.date_trunc(granularity, func.timezone("UTC", Entry.occurred_at))
    pattern = "%Y-%m-%d" if granularity == "day" else "%Y-%m"
    return func.strftime(pattern, Entry.occurred_at)


def _label(value: object, granularity: str) -> str:
    text = value.isoformat() if hasattr(value, "isoformat") else str(value)
    return text[:10] if granularity == "day" else text[:7]


def series(db: Session, *, granularity: str, period: Period) -> dict:
    """Lo verificado y lo que está en revisión por cubo temporal y moneda. Solo los cubos con entradas (un cubo sin
    entradas es «sin datos», no un cero inventado). Solo `SELECT`."""
    bucket = _bucket(db, granularity).label("bucket")
    rows = db.execute(
        select(bucket, Entry.currency, Entry.classification, Entry.kind, func.count(Entry.id), func.sum(Entry.amount))
        .where(*period.conditions())
        .group_by(bucket, Entry.currency, Entry.classification, Entry.kind)
        .order_by(bucket, Entry.currency)
    ).all()
    cells: dict[tuple[str, str], dict[tuple[str, str], _Cell]] = {}
    for found, currency, classification, kind, count, total in rows:
        cell = cells.setdefault((_label(found, granularity), currency), {}).setdefault((classification, kind), _Cell())
        cell.count += int(count)
        cell.total += _dec(total)

    buckets = []
    for (label, currency), by_class in sorted(cells.items()):
        zero = _Cell()
        revenue = by_class.get((Classification.ORDER_PAYMENT.value, EntryKind.CAPTURE.value), zero).total
        refunds = by_class.get((Classification.ORDER_PAYMENT.value, EntryKind.REFUND.value), zero).total
        received = sum((by_class.get((c, EntryKind.CAPTURE.value), zero).total for c in UNDER_REVIEW), _ZERO)
        returned = sum((by_class.get((c, EntryKind.REFUND.value), zero).total for c in UNDER_REVIEW), _ZERO)
        buckets.append(
            {
                "bucket": label,
                "currency": currency,
                "revenue": money(revenue),
                "refunds": money(refunds),
                "net": money(revenue - refunds),
                "under_review_received": money(received),
                "under_review_refunded": money(returned),
                "entries": sum(cell.count for cell in by_class.values()),
            }
        )
    return {"granularity": granularity, "period": period.view(), "buckets": buckets, "scope": SCOPE}


@dataclass(frozen=True)
class EntryPage:
    entries: list[Entry]
    has_more: bool
    next_cursor: str | None


def entries_page(
    db: Session,
    *,
    period: Period,
    cursor: str | None = None,
    limit: int = DEFAULT_PAGE_SIZE,
    currency: str | None = None,
    classification: str | None = None,
    kind: str | None = None,
) -> EntryPage:
    """Una página de entradas, de la más reciente a la más antigua, por cursor. Sin uniones: una consulta, un índice."""
    if not 1 <= limit <= MAX_PAGE_SIZE:
        raise ValidationError(f"limit must be between 1 and {MAX_PAGE_SIZE}")
    if classification is not None and classification not in {c.value for c in Classification}:
        raise ValidationError("classification is not one of ORDER_PAYMENT, DUPLICATE_RECEIPT, MISMATCH_RECEIPT")
    if kind is not None and kind not in {k.value for k in EntryKind}:
        raise ValidationError("kind is not one of CAPTURE, REFUND")
    query = select(Entry).where(*period.conditions())
    if currency is not None:
        query = query.where(Entry.currency == currency)
    if classification is not None:
        query = query.where(Entry.classification == classification)
    if kind is not None:
        query = query.where(Entry.kind == kind)
    if cursor is not None:
        position = EntryCursor.decode(cursor)
        after = tuple_(Entry.occurred_at, Entry.id) < tuple_(literal(position.occurred_at), literal(position.entry_id))
        query = query.where(after)
    rows = list(db.scalars(query.order_by(Entry.occurred_at.desc(), Entry.id.desc()).limit(limit + 1)))
    page = rows[:limit]
    more = len(rows) > limit
    last = page[-1] if page else None
    next_cursor = None
    if more and last is not None:
        moment = last.occurred_at
        stamp = moment.replace(tzinfo=datetime.UTC) if moment.tzinfo is None else moment.astimezone(datetime.UTC)
        next_cursor = EntryCursor(occurred_at=stamp, entry_id=last.id).encode()
    return EntryPage(entries=page, has_more=more, next_cursor=next_cursor)
