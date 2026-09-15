from pydantic import BaseModel

from app.core.errors import AmazonaError


class BudgetLimitExceededError(AmazonaError):
    """Raised when a reserve/commit call would exceed an authorized limit."""


class BudgetState(BaseModel):
    hard_limit: float
    soft_limit: float | None = None
    single_action_limit: float | None = None
    reserved: float = 0.0
    committed: float = 0.0
    spent: float = 0.0
    locked: float = 0.0

    @property
    def available(self) -> float:
        return self.hard_limit - self.reserved - self.committed - self.locked


class BudgetDecision(BaseModel):
    approved: bool
    reason: str | None = None
    warning: str | None = None


class BudgetEngine:
    """Deterministic budget guardrails. Reserving/committing funds always
    checks the same available-budget math, so repeated rapid requests
    cannot cumulatively overspend the hard limit."""

    def authorize(self, *, amount: float, state: BudgetState) -> BudgetDecision:
        if state.single_action_limit is not None and amount > state.single_action_limit:
            return BudgetDecision(
                approved=False,
                reason=f"amount {amount} exceeds single-action limit {state.single_action_limit}",
            )

        if amount > state.available:
            return BudgetDecision(
                approved=False,
                reason=f"amount {amount} exceeds hard limit; only {state.available} available",
            )

        warning = None
        if state.soft_limit is not None:
            projected_used = state.hard_limit - state.available + amount
            if projected_used > state.soft_limit:
                warning = f"projected usage {projected_used} exceeds soft limit {state.soft_limit}"

        return BudgetDecision(approved=True, warning=warning)

    def reserve(self, state: BudgetState, amount: float) -> BudgetState:
        decision = self.authorize(amount=amount, state=state)
        if not decision.approved:
            raise BudgetLimitExceededError(decision.reason)
        state.reserved += amount
        return state

    def release(self, state: BudgetState, amount: float) -> BudgetState:
        state.reserved = max(0.0, state.reserved - amount)
        return state

    def commit(self, state: BudgetState, amount: float) -> BudgetState:
        state.reserved = max(0.0, state.reserved - amount)
        state.committed += amount
        state.spent += amount
        return state
