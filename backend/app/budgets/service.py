from decimal import Decimal

from sqlalchemy import case, select, text, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from app.budgets.engine import BudgetAssessment, BudgetSnapshot, assess_spend
from app.core.errors import ValidationError
from app.core.ids import new_correlation_id
from app.db.models.audit import AuditLog
from app.db.models.budget import Budget, BudgetAllocation, FinancialEvent

DEFAULT_BUDGET_NAME = "orchestrator-default"


class BudgetLedgerService:
    """**La** fuente de verdad del presupuesto: las filas `budgets` (lo que el propietario
    ha autorizado), `budget_allocations` (lo reservado, comprometido y gastado) y
    `financial_events` (el rastro). El orquestador del CEO, el ActionGate y cualquier otro
    que necesite saber si un gasto cabe preguntan aquí; ninguno mantiene su propio saldo
    en memoria.

    Tres reglas:

    - El presupuesto **no se crea solo**. Solo `authorise_budget`, un acto explícito del
      propietario y auditado, crea o cambia el techo. Antes, la primera reserva inventaba
      uno de 100 000 en el código: un límite que nadie había autorizado.
    - Que no haya presupuesto **no es un permiso**: `assess` lo dice (`NO_BUDGET_RECORD`
      deniega; solo una simulación declarada lo deja pasar).
    - Reservar comprueba el límite **en la misma sentencia que escribe** (`reserve`): dos
      peticiones a la vez no pueden reservar, entre las dos, más de lo que cabe.
    """

    def __init__(self, db: Session, *, budget_name: str = DEFAULT_BUDGET_NAME) -> None:
        self._db = db
        self._budget_name = budget_name

    # --- Leer --------------------------------------------------------------------------

    def find_budget(self) -> Budget | None:
        """El presupuesto autorizado, o `None`. Nunca lo crea. El más antiguo gana si
        hubiera duplicados (la tabla no tiene restricción única por nombre)."""
        return (
            self._db.query(Budget)
            .filter_by(name=self._budget_name)
            .order_by(Budget.created_at, Budget.id)
            .first()
        )

    def snapshot(self) -> BudgetSnapshot | None:
        budget = self.find_budget()
        if budget is None:
            return None
        allocation = self._db.query(BudgetAllocation).filter_by(budget_id=budget.id).first()
        return BudgetSnapshot(
            hard_limit=float(budget.hard_limit),
            soft_limit=_as_float(budget.soft_limit),
            reserved=float(allocation.reserved) if allocation else 0.0,
            committed=float(allocation.committed) if allocation else 0.0,
            spent=float(allocation.spent) if allocation else 0.0,
        )

    def assess(self, amount: float | None, *, simulated: bool) -> BudgetAssessment:
        """¿Cabe este gasto? Solo lee. `amount=None` es «no se sabe lo que cuesta»."""
        return assess_spend(amount=amount, snapshot=self.snapshot(), simulated=simulated)

    # --- El acto del propietario -------------------------------------------------------

    def authorise_budget(
        self,
        *,
        hard_limit: float,
        soft_limit: float | None = None,
        actor: str,
        correlation_id: str | None = None,
    ) -> Budget:
        """Crea o cambia el techo autorizado, y lo deja en la auditoría con el antes y el
        después. Es el único sitio donde nace una fila de `budgets`."""
        hard = Decimal(str(hard_limit))
        soft = Decimal(str(soft_limit)) if soft_limit is not None else None
        if hard <= 0:
            raise ValidationError("the hard limit of a budget must be greater than zero")
        if soft is not None and not (0 < soft <= hard):
            raise ValidationError("the soft limit must be greater than zero and not above the hard limit")

        self._serialise(f"budget:{self._budget_name}")
        budget = self.find_budget()
        before: dict | None = None
        if budget is None:
            budget = Budget(
                name=self._budget_name, hard_limit=float(hard), soft_limit=float(soft) if soft is not None else None
            )
            self._db.add(budget)
            self._db.flush()
        else:
            before = {"hard_limit": float(budget.hard_limit), "soft_limit": _as_float(budget.soft_limit)}
            budget.hard_limit = float(hard)
            budget.soft_limit = float(soft) if soft is not None else None
        self._allocation(budget)
        self._db.add(
            AuditLog(
                actor=actor,
                action="budget.authorise",
                resource=f"budget:{budget.id}",
                before=before,
                after={"hard_limit": float(hard), "soft_limit": _as_float(soft)},
                correlation_id=correlation_id or new_correlation_id(),
            )
        )
        self._db.commit()
        return budget

    # --- Mover dinero ------------------------------------------------------------------

    def reserve(self, *, amount: float, reference: str, idempotent: bool = False) -> bool:
        """Reserva `amount`, **comprobando el límite en la misma sentencia que escribe**:

            UPDATE budget_allocations SET reserved = reserved + :a
             WHERE id = :id AND hard_limit - reserved - committed >= :a

        Evaluar primero y reservar después dejaba que dos peticiones a la vez vieran las dos
        el mismo saldo libre y reservaran, entre las dos, más de lo que cabía. Aquí, de N
        peticiones que no caben juntas, solo las que caben tocan una fila.

        Devuelve False si no hay presupuesto autorizado o si el importe no cabe: no reserva
        nada. Con `idempotent=True`, una reserva que ya está viva para esa `reference` (hay un
        `RESERVE` sin su `COMMIT`/`RELEASE`) cuenta como hecha y no se repite: es lo que evita
        que reintentar un paso reserve dos veces el mismo gasto."""
        budget = self.find_budget()
        if budget is None:
            return False
        delta = Decimal(str(amount))
        allocation = self._allocation(budget)
        if idempotent:
            self._serialise(f"reserve:{reference}")
            if self.outstanding(reference) > 0:
                return True

        hard_limit = select(Budget.hard_limit).where(Budget.id == budget.id).scalar_subquery()
        result = self._execute(
            update(BudgetAllocation)
            .where(
                BudgetAllocation.id == allocation.id,
                hard_limit - BudgetAllocation.reserved - BudgetAllocation.committed >= delta,
            )
            .values(reserved=BudgetAllocation.reserved + delta)
        )
        if result.rowcount != 1:
            return False
        self._db.expire(allocation)
        self._event(budget.id, "RESERVE", amount, reference)
        return True

    def record_commit(self, *, amount: float, reference: str) -> bool:
        """La reserva pasa a comprometida y gastada. False si no hay presupuesto autorizado:
        entonces no se reservó nada en el libro (fue una simulación declarada) y no hay nada
        que mover."""
        return self._move(amount, reference, "COMMIT")

    def record_release(self, *, amount: float, reference: str) -> bool:
        """La reserva se libera, sin tocar lo comprometido ni lo gastado. Mismo criterio que
        `record_commit` si no hay presupuesto."""
        return self._move(amount, reference, "RELEASE")

    def _move(self, amount: float, reference: str, kind: str) -> bool:
        budget = self.find_budget()
        if budget is None:
            return False
        allocation = self._allocation(budget)
        delta = Decimal(str(amount))
        # Nunca negativo: liberar más de lo reservado deja cero. Aritmética de la base de
        # datos, no «leer el total, sumar en Python y escribir»: con dos peticiones a la vez la
        # segunda habría pisado la suma de la primera. La fila queda bloqueada por el UPDATE
        # hasta el commit, así que las peticiones concurrentes se ordenan solas.
        values: dict[str, object] = {
            "reserved": case(
                (BudgetAllocation.reserved - delta > 0, BudgetAllocation.reserved - delta), else_=0
            )
        }
        if kind == "COMMIT":
            values["committed"] = BudgetAllocation.committed + delta
            values["spent"] = BudgetAllocation.spent + delta
        self._execute(update(BudgetAllocation).where(BudgetAllocation.id == allocation.id).values(**values))
        self._db.expire(allocation)
        self._event(budget.id, kind, amount, reference)
        return True

    # --- Interno -----------------------------------------------------------------------

    def _allocation(self, budget: Budget) -> BudgetAllocation:
        allocation = self._db.query(BudgetAllocation).filter_by(budget_id=budget.id).first()
        if allocation is None:
            allocation = BudgetAllocation(budget_id=budget.id, reserved=0.0, committed=0.0, spent=0.0)
            self._db.add(allocation)
            self._db.flush()
        return allocation

    def _execute(self, statement) -> CursorResult:
        result = self._db.execute(statement.execution_options(synchronize_session=False))
        assert isinstance(result, CursorResult)
        return result

    def _event(self, budget_id: str, kind: str, amount: float, reference: str) -> None:
        self._db.add(FinancialEvent(budget_id=budget_id, type=kind, amount=float(amount), reference=reference))
        self._db.flush()

    def outstanding(self, reference: str) -> Decimal:
        """Lo reservado y aún no comprometido ni liberado para esa referencia."""
        total = Decimal(0)
        for event in self._db.query(FinancialEvent).filter_by(reference=reference).all():
            amount = Decimal(str(event.amount))
            if event.type == "RESERVE":
                total += amount
            elif event.type in ("COMMIT", "RELEASE"):
                total -= amount
        return total

    def _serialise(self, key: str) -> None:
        """En PostgreSQL, un lock de transacción por clave: dos operaciones sobre lo mismo
        esperan una a la otra en vez de pisarse. Lo libera el commit."""
        if self._db.get_bind().dialect.name == "postgresql":
            self._db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": key})


def _as_float(value) -> float | None:
    return float(value) if value is not None else None
