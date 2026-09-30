from decimal import Decimal

from sqlalchemy import case, update
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
        allocation = self._get_or_create_allocation()
        self._apply(allocation, amount, reserve=True)
        self._event(allocation, "RESERVE", amount, reference)

    def record_commit(self, *, amount: float, reference: str) -> None:
        allocation = self._get_or_create_allocation()
        self._apply(allocation, amount, release_reserved=True, commit=True)
        self._event(allocation, "COMMIT", amount, reference)

    def record_release(self, *, amount: float, reference: str) -> None:
        allocation = self._get_or_create_allocation()
        self._apply(allocation, amount, release_reserved=True)
        self._event(allocation, "RELEASE", amount, reference)

    def _apply(
        self,
        allocation: BudgetAllocation,
        amount: float,
        *,
        reserve: bool = False,
        release_reserved: bool = False,
        commit: bool = False,
    ) -> None:
        """Mueve los saldos con aritmética **de la base de datos**
        (`SET committed = committed + :amount`), no leyendo el total, sumando en
        Python y escribiendo el resultado: con dos peticiones a la vez, la segunda
        habría pisado la suma de la primera y el libro habría perdido un importe.
        La fila queda bloqueada por el UPDATE hasta el commit, así que las
        peticiones concurrentes se ordenan solas."""
        delta = Decimal(str(amount))
        values: dict[str, object] = {}
        if reserve:
            values["reserved"] = BudgetAllocation.reserved + delta
        if release_reserved:
            # Nunca negativo, como antes: liberar más de lo reservado deja cero.
            values["reserved"] = case(
                (BudgetAllocation.reserved - delta > 0, BudgetAllocation.reserved - delta), else_=0
            )
        if commit:
            values["committed"] = BudgetAllocation.committed + delta
            values["spent"] = BudgetAllocation.spent + delta
        self._db.execute(
            update(BudgetAllocation)
            .where(BudgetAllocation.id == allocation.id)
            .values(**values)
            .execution_options(synchronize_session=False)
        )
        # El objeto que hay en la sesión ya no refleja la fila: que se vuelva a leer.
        self._db.expire(allocation)

    def _event(self, allocation: BudgetAllocation, kind: str, amount: float, reference: str) -> None:
        self._db.add(
            FinancialEvent(budget_id=allocation.budget_id, type=kind, amount=float(amount), reference=reference)
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
