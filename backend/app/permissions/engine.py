from app.permissions.policies import DEFAULT_POLICY, OWNER_ONLY_ACTIONS, ActionType, PermissionResult


class PermissionEngine:
    """Deterministic, LLM-independent permission checks.

    Permissions are external to agent/LLM output: an agent's own
    recommendation can never grant it an action the policy denies.
    """

    def __init__(self, policy: dict[ActionType, PermissionResult] | None = None) -> None:
        self._policy = dict(policy or DEFAULT_POLICY)

    def check(
        self,
        *,
        actor_role: str,
        action: ActionType,
        is_self_target: bool = False,
    ) -> PermissionResult:
        if action == ActionType.PERMISSION_GRANT and is_self_target:
            return PermissionResult.DENIED

        if action in OWNER_ONLY_ACTIONS and actor_role != "owner":
            return PermissionResult.DENIED

        return self._policy.get(action, PermissionResult.DENIED)
