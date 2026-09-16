from sqlalchemy.orm import Session

from app.db.models.budget import Budget, BudgetAllocation, FinancialEvent

DEFAULT_BUDGET_NAME = "orchestrator-default"
DEFAULT_BUDGET_HARD_LIMIT = 100_000.0


class BudgetLedgerService:
    """Durable ledger alongside the orchestrator's in-memory BudgetEngine/
    BudgetState: every reserve/commit/release the orchestrator and the
    approvals API perform is mirrored here as a real budget_allocations
    row plus an append-only financial_events trail, so the CFO agent
    (Milestone 10) can report real utilization instead of always zero.

    This does not replace BudgetEngine's in-memory authorization — it
    records the outcome of decisions BudgetEngine already made. One
    canonical Budget row (get-or-create by name) backs the whole
    orchestrator, mirroring BudgetState being a single instance per
    orchestrator today."""

    def __init__(
        self,
        db: Session,
        *,
        budget_name: str = DEFAULT_BUDGET_NAME,
        hard_limit: float = DEFAULT_BUDGET_HARD_LIMIT,
        soft_limit: float | None = None,
    ) -> None:
        self._db = db
        self._budget_name = budget_name
        self._hard_limit = hard_limit
        self._soft_limit = soft_limit

    def record_reserve(self, *, amount: float, reference: str) -> None:
        amount = float(amount)
        allocation = self._get_or_create_allocation()
        allocation.reserved = float(allocation.reserved) + amount
        self._db.add(
            FinancialEvent(budget_id=allocation.budget_id, type="RESERVE", amount=amount, reference=reference)
        )
        self._db.flush()

    def record_commit(self, *, amount: float, reference: str) -> None:
        amount = float(amount)
        allocation = self._get_or_create_allocation()
        allocation.reserved = max(0.0, float(allocation.reserved) - amount)
        allocation.committed = float(allocation.committed) + amount
        allocation.spent = float(allocation.spent) + amount
        self._db.add(
            FinancialEvent(budget_id=allocation.budget_id, type="COMMIT", amount=amount, reference=reference)
        )
        self._db.flush()

    def record_release(self, *, amount: float, reference: str) -> None:
        amount = float(amount)
        allocation = self._get_or_create_allocation()
        allocation.reserved = max(0.0, float(allocation.reserved) - amount)
        self._db.add(
            FinancialEvent(budget_id=allocation.budget_id, type="RELEASE", amount=amount, reference=reference)
        )
        self._db.flush()

    def _get_or_create_budget(self) -> Budget:
        budget = self._db.query(Budget).filter_by(name=self._budget_name).first()
        if budget is None:
            budget = Budget(name=self._budget_name, hard_limit=self._hard_limit, soft_limit=self._soft_limit)
            self._db.add(budget)
            self._db.flush()
        return budget

    def _get_or_create_allocation(self) -> BudgetAllocation:
        budget = self._get_or_create_budget()
        allocation = self._db.query(BudgetAllocation).filter_by(budget_id=budget.id).first()
        if allocation is None:
            allocation = BudgetAllocation(budget_id=budget.id, reserved=0.0, committed=0.0, spent=0.0)
            self._db.add(allocation)
            self._db.flush()
        return allocation
