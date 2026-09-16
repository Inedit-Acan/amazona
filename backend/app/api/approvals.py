import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.approvals.service import ApprovalNotPendingError
from app.core.errors import NotFoundError
from app.db.models.approval import Approval as ApprovalModel
from app.db.models.audit import AuditLog as AuditLogModel
from app.db.session import get_db

router = APIRouter(prefix="/api/approvals", tags=["approvals"])


class ApprovalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    decision_id: str
    action: str
    amount: float | None
    status: str
    expires_at: datetime.datetime | None
    resolved_at: datetime.datetime | None
    resolved_by: str | None


class ApprovalActionIn(BaseModel):
    actor: str


@router.get("", response_model=list[ApprovalOut])
def list_approvals(db: Session = Depends(get_db)) -> list[ApprovalModel]:
    return db.query(ApprovalModel).all()


@router.post("/{approval_id}/approve", response_model=ApprovalOut)
def approve_approval(approval_id: str, payload: ApprovalActionIn, db: Session = Depends(get_db)) -> ApprovalModel:
    return _resolve(approval_id, payload.actor, "APPROVED", db)


@router.post("/{approval_id}/reject", response_model=ApprovalOut)
def reject_approval(approval_id: str, payload: ApprovalActionIn, db: Session = Depends(get_db)) -> ApprovalModel:
    return _resolve(approval_id, payload.actor, "REJECTED", db)


def _as_aware_utc(value: datetime.datetime) -> datetime.datetime:
    """SQLite drops tzinfo on round-trip; every stored datetime here is UTC."""
    return value if value.tzinfo is not None else value.replace(tzinfo=datetime.UTC)


def _resolve(approval_id: str, actor: str, new_status: str, db: Session) -> ApprovalModel:
    approval = db.get(ApprovalModel, approval_id)
    if approval is None:
        raise NotFoundError(f"approval {approval_id} not found")

    now = datetime.datetime.now(datetime.UTC)
    if approval.status == "PENDING" and approval.expires_at and _as_aware_utc(approval.expires_at) <= now:
        approval.status = "EXPIRED"
        approval.resolved_at = now
        db.add(
            AuditLogModel(
                actor="system",
                action="approval.expire",
                resource=f"approval:{approval.id}",
                before={"status": "PENDING"},
                after={"status": "EXPIRED"},
                correlation_id=approval.correlation_id,
            )
        )
        db.commit()

    if approval.status != "PENDING":
        raise ApprovalNotPendingError(f"approval {approval_id} is not pending (status={approval.status})")

    before_status = approval.status
    approval.status = new_status
    approval.resolved_at = now
    approval.resolved_by = actor
    action_verb = "approve" if new_status == "APPROVED" else "reject"
    db.add(
        AuditLogModel(
            actor=actor,
            action=f"approval.{action_verb}",
            resource=f"approval:{approval.id}",
            before={"status": before_status},
            after={"status": new_status},
            correlation_id=approval.correlation_id,
        )
    )
    db.commit()
    db.refresh(approval)
    return approval
