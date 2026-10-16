import datetime
from enum import StrEnum

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import literal, tuple_
from sqlalchemy.orm import Session

from app.db.models.audit import AuditLog as AuditLogModel
from app.db.session import get_db

router = APIRouter(prefix="/api/audit", tags=["audit"])

#: The most rows a single request returns. Without parameters this is also how many it returns: the 500 OLDEST.
MAX_LIMIT = 500


class AuditOrder(StrEnum):
    ASC = "asc"
    DESC = "desc"


class AuditEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    actor: str
    action: str
    resource: str
    before: dict | None
    after: dict | None
    correlation_id: str
    created_at: datetime.datetime


def _parse_instant(text: str, name: str) -> datetime.datetime:
    """An ISO-8601 date AND time, as an aware UTC instant.

    A value without a zone is read as UTC (everything this system stores is UTC); one with a zone is converted. It is
    parsed here, not by pydantic, because pydantic also accepts a bare number as a Unix timestamp and a date alone as
    midnight: both would be a silent reinterpretation, and an invalid value must be a 422, never a guess.
    """
    if "T" not in text and " " not in text:
        raise HTTPException(status_code=422, detail=f"{name} must be an ISO-8601 date and time")
    try:
        parsed = datetime.datetime.fromisoformat(text)
        return parsed.replace(tzinfo=datetime.UTC) if parsed.tzinfo is None else parsed.astimezone(datetime.UTC)
    except (ValueError, OverflowError):  # OverflowError: year 9999 with a negative offset does not fit in UTC
        raise HTTPException(status_code=422, detail=f"{name} is not a valid ISO-8601 timestamp") from None


def _parse_cursor(text: str) -> tuple[datetime.datetime, str]:
    """`before` is `<created_at>,<id>`: the `created_at` of the last row received, exactly as the API returned it
    (any ISO-8601 offset is fine, it is the same instant; percent-encode a `+`), a comma, and that row's id."""
    instant, comma, row_id = text.partition(",")
    if not comma or not row_id:
        raise HTTPException(status_code=422, detail="before must be '<created_at>,<id>'")
    return _parse_instant(instant, "before"), row_id


@router.get("", response_model=list[AuditEntryOut])
def list_audit_entries(
    correlation_id: str | None = None,
    order: AuditOrder = AuditOrder.ASC,
    limit: int = Query(default=MAX_LIMIT, ge=1, le=MAX_LIMIT),
    since: str | None = None,
    before: str | None = None,
    db: Session = Depends(get_db),
) -> list[AuditLogModel]:
    """The audit trail, ordered by `(created_at, id)`.

    With no parameter it is what it always was: ascending, 500 rows, the 500 oldest. `order=desc&limit=n` returns the
    n most recent. `since` keeps rows at or after an instant. `before` is a keyset cursor `(created_at, id)`: only rows
    strictly before it in `(created_at, id)` order, which pages backwards with no offset and no lost or repeated row
    when several rows share a `created_at`. `correlation_id` filters as before and combines with everything.
    """
    since_at = _parse_instant(since, "since") if since is not None else None
    cursor = _parse_cursor(before) if before is not None else None

    query = db.query(AuditLogModel)
    if correlation_id is not None:
        query = query.filter(AuditLogModel.correlation_id == correlation_id)
    if since_at is not None:
        query = query.filter(AuditLogModel.created_at >= since_at)
    if cursor is not None:
        cursor_at, cursor_id = cursor
        # A row comparison, not `created_at < c OR (created_at = c AND id < i)`: the same thing, but PostgreSQL turns a
        # row comparison into one range scan of an index on (created_at, id), which the OR form cannot use.
        row = tuple_(AuditLogModel.created_at, AuditLogModel.id)
        query = query.filter(
            row < tuple_(literal(cursor_at, AuditLogModel.created_at.type), literal(cursor_id, AuditLogModel.id.type))
        )
    if order is AuditOrder.DESC:
        query = query.order_by(AuditLogModel.created_at.desc(), AuditLogModel.id.desc())
    else:
        query = query.order_by(AuditLogModel.created_at.asc(), AuditLogModel.id.asc())
    return query.limit(limit).all()
