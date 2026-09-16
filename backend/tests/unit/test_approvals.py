import datetime

import pytest

from app.approvals.service import ApprovalNotPendingError, ApprovalService
from app.ceo.schemas import ApprovalStatus


def now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


@pytest.fixture()
def service() -> ApprovalService:
    return ApprovalService()


def test_create_approval_is_contextual_and_pending(service: ApprovalService):
    approval = service.create_approval(
        decision_id="dec-1",
        action="launch_marketing_campaign",
        amount=150.0,
        expiry=now() + datetime.timedelta(hours=24),
    )

    assert approval.decision_id == "dec-1"
    assert approval.action == "launch_marketing_campaign"
    assert approval.amount == 150.0
    assert approval.status == ApprovalStatus.PENDING


def test_approve_transitions_to_approved(service: ApprovalService):
    approval = service.create_approval(decision_id="dec-1", action="spend", amount=10.0, expiry=None)

    resolved = service.approve(approval.id, actor="owner@amazona.local")

    assert resolved.status == ApprovalStatus.APPROVED
    assert resolved.resolved_by == "owner@amazona.local"
    assert resolved.resolved_at is not None


def test_reject_transitions_to_rejected(service: ApprovalService):
    approval = service.create_approval(decision_id="dec-1", action="spend", amount=10.0, expiry=None)

    resolved = service.reject(approval.id, actor="owner@amazona.local")

    assert resolved.status == ApprovalStatus.REJECTED


def test_approval_cannot_be_reused_once_approved(service: ApprovalService):
    approval = service.create_approval(decision_id="dec-1", action="spend", amount=10.0, expiry=None)
    service.approve(approval.id, actor="owner@amazona.local")

    with pytest.raises(ApprovalNotPendingError):
        service.approve(approval.id, actor="owner@amazona.local")


def test_approval_cannot_be_reused_once_rejected(service: ApprovalService):
    approval = service.create_approval(decision_id="dec-1", action="spend", amount=10.0, expiry=None)
    service.reject(approval.id, actor="owner@amazona.local")

    with pytest.raises(ApprovalNotPendingError):
        service.reject(approval.id, actor="owner@amazona.local")


def test_expire_pending_marks_past_due_approvals_as_expired(service: ApprovalService):
    past_expiry = now() - datetime.timedelta(minutes=1)
    approval = service.create_approval(decision_id="dec-1", action="spend", amount=10.0, expiry=past_expiry)

    expired = service.expire_pending(now())

    assert [a.id for a in expired] == [approval.id]
    assert service.get_approval(approval.id).status == ApprovalStatus.EXPIRED


def test_expired_approval_cannot_execute():
    service = ApprovalService()
    past_expiry = now() - datetime.timedelta(minutes=1)
    approval = service.create_approval(decision_id="dec-1", action="spend", amount=10.0, expiry=past_expiry)
    service.expire_pending(now())

    with pytest.raises(ApprovalNotPendingError):
        service.approve(approval.id, actor="owner@amazona.local")


def test_expire_pending_does_not_touch_approvals_without_expiry(service: ApprovalService):
    approval = service.create_approval(decision_id="dec-1", action="spend", amount=10.0, expiry=None)

    expired = service.expire_pending(now())

    assert expired == []
    assert service.get_approval(approval.id).status == ApprovalStatus.PENDING


def test_all_transitions_are_recorded_in_history(service: ApprovalService):
    approval = service.create_approval(decision_id="dec-1", action="spend", amount=10.0, expiry=None)
    service.approve(approval.id, actor="owner@amazona.local")

    history = service.get_history(approval.id)

    assert [entry["to_status"] for entry in history] == [ApprovalStatus.PENDING, ApprovalStatus.APPROVED]
    assert history[-1]["actor"] == "owner@amazona.local"
