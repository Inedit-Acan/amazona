import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.db.models.audit import AuditLog as AuditLogModel
from app.db.session import get_db

router = APIRouter(prefix="/api/audit", tags=["audit"])


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


@router.get("", response_model=list[AuditEntryOut])
def list_audit_entries(correlation_id: str | None = None, db: Session = Depends(get_db)) -> list[AuditLogModel]:
    query = db.query(AuditLogModel)
    if correlation_id is not None:
        query = query.filter(AuditLogModel.correlation_id == correlation_id)
    return query.order_by(AuditLogModel.created_at).limit(500).all()
