from enum import StrEnum


class ActionType(StrEnum):
    RESEARCH_READ = "research.read"
    DRAFT_CREATE = "draft.create"
    EXTERNAL_SPEND = "external.spend"
    POLICY_EDIT = "policy.edit"
    PERMISSION_GRANT = "permission.grant"


class PermissionResult(StrEnum):
    ALLOWED = "ALLOWED"
    HUMAN_APPROVAL_REQUIRED = "HUMAN_APPROVAL_REQUIRED"
    DENIED = "DENIED"


OWNER_ONLY_ACTIONS = {ActionType.POLICY_EDIT}

DEFAULT_POLICY: dict[ActionType, PermissionResult] = {
    ActionType.RESEARCH_READ: PermissionResult.ALLOWED,
    ActionType.DRAFT_CREATE: PermissionResult.ALLOWED,
    ActionType.EXTERNAL_SPEND: PermissionResult.HUMAN_APPROVAL_REQUIRED,
    ActionType.POLICY_EDIT: PermissionResult.ALLOWED,
    ActionType.PERMISSION_GRANT: PermissionResult.ALLOWED,
}
