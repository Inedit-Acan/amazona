"""The RBAC matrix, asserted role by role.

Deliberately exhaustive: every one of the seven roles is checked against every
API action, so widening a role's powers can only happen by changing a test that
says so out loud. Milestone 29 wrote the mutating half; Milestone 29.1 added the
three read actions.
"""

import pytest

from app.auth.actor import RoleName
from app.permissions.policies import API_ROLE_ACTIONS, ApiAction, role_can

#: Every read except the audit trail. Six of the seven roles get exactly this.
READS = {ApiAction.BUSINESS_READ, ApiAction.DIAGNOSTICS_READ}

#: What each role may do. Anything absent is denied.
EXPECTED: dict[RoleName, set[ApiAction]] = {
    RoleName.OWNER: set(ApiAction),
    RoleName.ADMIN: set(ApiAction),
    RoleName.OPERATOR: READS
    | {
        ApiAction.OBJECTIVE_WRITE,
        ApiAction.AGENT_RUN,
        ApiAction.PIPELINE_RUN,
        ApiAction.INCIDENT_WRITE,
        ApiAction.JOB_WRITE,
    },
    RoleName.ANALYST: READS | {ApiAction.AGENT_RUN},
    RoleName.REVIEWER: READS
    | {ApiAction.APPROVAL_RESOLVE, ApiAction.REVIEW_RESOLVE, ApiAction.AUDIT_READ},
    RoleName.VIEWER: READS,
    RoleName.SYSTEM: READS
    | {
        ApiAction.OBJECTIVE_WRITE,
        ApiAction.AGENT_RUN,
        ApiAction.PIPELINE_RUN,
        ApiAction.INCIDENT_WRITE,
        ApiAction.JOB_WRITE,
    },
}

#: Actions that change something. Used to state "read-only" precisely.
WRITES = set(ApiAction) - READS - {ApiAction.AUDIT_READ}


@pytest.mark.parametrize("role", list(RoleName))
@pytest.mark.parametrize("action", list(ApiAction))
def test_every_role_against_every_action(role: RoleName, action: ApiAction):
    assert role_can(role, action) is (action in EXPECTED[role])


def test_no_role_at_all_can_do_anything():
    for action in ApiAction:
        assert role_can(None, action) is False


def test_an_unknown_role_grants_nothing():
    # role_can only accepts RoleName, but a role row could carry any name; the
    # lookup falls back to the empty set rather than to "allowed".
    assert API_ROLE_ACTIONS.get("SUPERUSER", frozenset()) == frozenset()  # type: ignore[arg-type]


def test_viewer_is_read_only():
    for action in WRITES:
        assert role_can(RoleName.VIEWER, action) is False, action
    for action in READS:
        assert role_can(RoleName.VIEWER, action) is True, action


def test_the_audit_trail_is_narrower_than_the_rest_of_the_reads():
    """It carries the identity of whoever acted, so it is not "business data
    anyone with an account may read" (Milestone 29.1)."""
    readers = {role for role in RoleName if role_can(role, ApiAction.AUDIT_READ)}

    assert readers == {RoleName.OWNER, RoleName.ADMIN, RoleName.REVIEWER}
    for role in (RoleName.VIEWER, RoleName.OPERATOR, RoleName.ANALYST, RoleName.SYSTEM):
        assert role_can(role, ApiAction.BUSINESS_READ) is True
        assert role_can(role, ApiAction.AUDIT_READ) is False


def test_every_role_can_read_business_data():
    for role in RoleName:
        assert role_can(role, ApiAction.BUSINESS_READ) is True, role


def test_analyst_can_run_agents_but_not_touch_the_kill_switch():
    assert role_can(RoleName.ANALYST, ApiAction.AGENT_RUN) is True
    assert role_can(RoleName.ANALYST, ApiAction.KILL_SWITCH_WRITE) is False


def test_operator_runs_pipelines_but_does_not_hold_the_kill_switch():
    assert role_can(RoleName.OPERATOR, ApiAction.PIPELINE_RUN) is True
    assert role_can(RoleName.OPERATOR, ApiAction.KILL_SWITCH_WRITE) is False


def test_reviewer_resolves_decisions_but_cannot_start_work():
    assert role_can(RoleName.REVIEWER, ApiAction.APPROVAL_RESOLVE) is True
    assert role_can(RoleName.REVIEWER, ApiAction.REVIEW_RESOLVE) is True
    assert role_can(RoleName.REVIEWER, ApiAction.PIPELINE_RUN) is False


def test_only_owner_and_admin_hold_the_kill_switch():
    holders = {role for role in RoleName if role_can(role, ApiAction.KILL_SWITCH_WRITE)}
    assert holders == {RoleName.OWNER, RoleName.ADMIN}


def test_watching_the_queue_is_not_the_same_as_feeding_it():
    """Milestone 31: ver lo que hace el sistema es lectura de negocio; hacerle
    trabajar, no."""
    feeders = {role for role in RoleName if role_can(role, ApiAction.JOB_WRITE)}

    assert feeders == {RoleName.OWNER, RoleName.ADMIN, RoleName.OPERATOR, RoleName.SYSTEM}
    for role in (RoleName.VIEWER, RoleName.ANALYST, RoleName.REVIEWER):
        assert role_can(role, ApiAction.BUSINESS_READ) is True
        assert role_can(role, ApiAction.JOB_WRITE) is False
