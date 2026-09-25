"""The RBAC matrix of Milestone 29, asserted role by role.

Deliberately exhaustive: every one of the seven roles is checked against every
one of the seven API actions, so widening a role's powers can only happen by
changing a test that says so out loud.
"""

import pytest

from app.auth.actor import RoleName
from app.permissions.policies import API_ROLE_ACTIONS, ApiAction, role_can

#: What each role may do. Anything absent is denied.
EXPECTED: dict[RoleName, set[ApiAction]] = {
    RoleName.OWNER: set(ApiAction),
    RoleName.ADMIN: set(ApiAction),
    RoleName.OPERATOR: {
        ApiAction.OBJECTIVE_WRITE,
        ApiAction.AGENT_RUN,
        ApiAction.PIPELINE_RUN,
        ApiAction.INCIDENT_WRITE,
    },
    RoleName.ANALYST: {ApiAction.AGENT_RUN},
    RoleName.REVIEWER: {ApiAction.APPROVAL_RESOLVE, ApiAction.REVIEW_RESOLVE},
    RoleName.VIEWER: set(),
    RoleName.SYSTEM: {
        ApiAction.OBJECTIVE_WRITE,
        ApiAction.AGENT_RUN,
        ApiAction.PIPELINE_RUN,
        ApiAction.INCIDENT_WRITE,
    },
}


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
    for action in ApiAction:
        assert role_can(RoleName.VIEWER, action) is False


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
