from app.permissions.engine import PermissionEngine
from app.permissions.policies import ActionType, PermissionResult


def test_research_read_actions_are_allowed():
    engine = PermissionEngine()

    result = engine.check(actor_role="agent", action=ActionType.RESEARCH_READ)

    assert result == PermissionResult.ALLOWED


def test_simulated_draft_creation_is_allowed():
    engine = PermissionEngine()

    result = engine.check(actor_role="agent", action=ActionType.DRAFT_CREATE)

    assert result == PermissionResult.ALLOWED


def test_any_simulated_external_spend_requires_human_approval():
    engine = PermissionEngine()

    result = engine.check(actor_role="agent", action=ActionType.EXTERNAL_SPEND)

    assert result == PermissionResult.HUMAN_APPROVAL_REQUIRED


def test_policy_editing_is_allowed_for_owner():
    engine = PermissionEngine()

    result = engine.check(actor_role="owner", action=ActionType.POLICY_EDIT)

    assert result == PermissionResult.ALLOWED


def test_policy_editing_is_denied_for_non_owner():
    engine = PermissionEngine()

    result = engine.check(actor_role="agent", action=ActionType.POLICY_EDIT)

    assert result == PermissionResult.DENIED


def test_agent_cannot_grant_itself_permissions():
    engine = PermissionEngine()

    result = engine.check(actor_role="agent", action=ActionType.PERMISSION_GRANT, is_self_target=True)

    assert result == PermissionResult.DENIED


def test_permission_self_escalation_is_forbidden_regardless_of_role():
    engine = PermissionEngine()

    result = engine.check(actor_role="owner", action=ActionType.PERMISSION_GRANT, is_self_target=True)

    assert result == PermissionResult.DENIED


def test_granting_permissions_to_another_actor_is_not_blocked_by_self_escalation_rule():
    engine = PermissionEngine()

    result = engine.check(actor_role="owner", action=ActionType.PERMISSION_GRANT, is_self_target=False)

    assert result == PermissionResult.ALLOWED


def test_an_unrecognized_role_is_denied_by_default_even_for_normally_allowed_actions():
    engine = PermissionEngine()

    result = engine.check(actor_role=None, action=ActionType.RESEARCH_READ)

    assert result == PermissionResult.DENIED
