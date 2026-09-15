import datetime

from pydantic import BaseModel, Field

from app.ceo.schemas import ApprovalStatus
from app.core.errors import AmazonaError, NotFoundError
from app.core.ids import new_id


class ApprovalNotPendingError(AmazonaError):
    """Raised when acting on an approval that is expired or already resolved."""


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


class Approval(BaseModel):
    id: str = Field(default_factory=new_id)
    decision_id: str
    action: str
    amount: float | None = None
    status: ApprovalStatus = ApprovalStatus.PENDING
    requested_at: datetime.datetime = Field(default_factory=_utcnow)
    expires_at: datetime.datetime | None = None
    resolved_at: datetime.datetime | None = None
    resolved_by: str | None = None


class ApprovalService:
    """Human approval lifecycle. Each approval authorizes exactly one
    contextual action (a specific decision_id + action + amount) and can
    never be reused once resolved or expired."""

    def __init__(self) -> None:
        self._approvals: dict[str, Approval] = {}
        self._history: dict[str, list[dict]] = {}

    def create_approval(
        self,
        *,
        decision_id: str,
        action: str,
        amount: float | None,
        expiry: datetime.datetime | None,
    ) -> Approval:
        approval = Approval(decision_id=decision_id, action=action, amount=amount, expires_at=expiry)
        self._approvals[approval.id] = approval
        self._record(approval.id, to_status=ApprovalStatus.PENDING, actor="system")
        return approval

    def get_approval(self, approval_id: str) -> Approval:
        approval = self._approvals.get(approval_id)
        if approval is None:
            raise NotFoundError(f"approval {approval_id} not found")
        return approval

    def approve(self, approval_id: str, actor: str) -> Approval:
        return self._resolve(approval_id, actor, ApprovalStatus.APPROVED)

    def reject(self, approval_id: str, actor: str) -> Approval:
        return self._resolve(approval_id, actor, ApprovalStatus.REJECTED)

    def expire_pending(self, now: datetime.datetime) -> list[Approval]:
        expired = []
        for approval in self._approvals.values():
            if approval.status == ApprovalStatus.PENDING and approval.expires_at and approval.expires_at <= now:
                approval.status = ApprovalStatus.EXPIRED
                approval.resolved_at = now
                self._record(approval.id, to_status=ApprovalStatus.EXPIRED, actor="system")
                expired.append(approval)
        return expired

    def get_history(self, approval_id: str) -> list[dict]:
        return list(self._history.get(approval_id, []))

    def _resolve(self, approval_id: str, actor: str, status: ApprovalStatus) -> Approval:
        approval = self.get_approval(approval_id)
        if approval.status != ApprovalStatus.PENDING:
            raise ApprovalNotPendingError(f"approval {approval_id} is not pending (status={approval.status})")

        approval.status = status
        approval.resolved_at = _utcnow()
        approval.resolved_by = actor
        self._record(approval_id, to_status=status, actor=actor)
        return approval

    def _record(self, approval_id: str, *, to_status: ApprovalStatus, actor: str) -> None:
        self._history.setdefault(approval_id, []).append(
            {"to_status": to_status, "actor": actor, "at": _utcnow()}
        )
