import pytest
from pydantic import ValidationError

from app.audit.service import AuditService


@pytest.fixture()
def service() -> AuditService:
    return AuditService()


def test_record_appends_an_entry_with_all_required_fields(service: AuditService):
    entry = service.record(
        actor="owner@amazona.local",
        action="approval.approve",
        resource="approval:appr-1",
        before={"status": "PENDING"},
        after={"status": "APPROVED"},
        correlation_id="corr-1",
    )

    assert entry.actor == "owner@amazona.local"
    assert entry.action == "approval.approve"
    assert entry.resource == "approval:appr-1"
    assert entry.before == {"status": "PENDING"}
    assert entry.after == {"status": "APPROVED"}
    assert entry.correlation_id == "corr-1"
    assert entry.timestamp is not None


def test_list_for_correlation_returns_only_matching_entries_in_order(service: AuditService):
    service.record(
        actor="a", action="first", resource="r1", before=None, after=None, correlation_id="corr-1"
    )
    service.record(
        actor="a", action="second", resource="r1", before=None, after=None, correlation_id="corr-2"
    )
    service.record(
        actor="a", action="third", resource="r1", before=None, after=None, correlation_id="corr-1"
    )

    entries = service.list_for_correlation("corr-1")

    assert [e.action for e in entries] == ["first", "third"]


def test_audit_entries_cannot_be_mutated_in_place(service: AuditService):
    entry = service.record(
        actor="a", action="first", resource="r1", before=None, after=None, correlation_id="corr-1"
    )

    with pytest.raises(ValidationError):
        entry.action = "tampered"


def test_mutating_a_returned_list_does_not_affect_the_stored_audit_trail(service: AuditService):
    service.record(actor="a", action="first", resource="r1", before=None, after=None, correlation_id="corr-1")

    entries = service.list_for_correlation("corr-1")
    entries.clear()

    assert len(service.list_for_correlation("corr-1")) == 1


def test_audit_service_exposes_no_update_or_delete_method(service: AuditService):
    assert not hasattr(service, "update")
    assert not hasattr(service, "delete")
