from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import case, select, text, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from app.budgets.engine import BudgetAssessment, BudgetSnapshot, assess_spend
from app.core.errors import ValidationError
from app.core.ids import new_correlation_id
from app.db.models.audit import AuditLog
from app.db.models.budget import Budget, BudgetAllocation, FinancialEvent
from app.sourcing.trade_terms import ACCOUNTING_CURRENCY

DEFAULT_BUDGET_NAME = "orchestrator-default"

#: El techo más alto que se puede autorizar. No es una política de negocio sino una guarda contra un error de
#: tecleo (un cero de más, `inf`, `nan`): ningún límite infinito existe, y uno absurdo no es una decisión del
#: propietario. Subirlo es un cambio de código revisado, no un parámetro.
MAX_HARD_LIMIT = Decimal("10000000.00")
_CENT = Decimal("0.01")


@dataclass(frozen=True)
class BudgetSummary:
    """El presupuesto autorizado y su saldo, tal como están ahora, para **enseñarlos** (`GET /api/budget`). Solo
    lectura.

    Todo sale de las filas: `name`, `period`, `hard_limit` y `soft_limit` de `budgets`; `reserved`, `committed` y
    `spent` de `budget_allocations`. La moneda no es una columna: es la moneda contable que ya usa la autorización
    (`_describe`). `remaining` es lo que el motor llama «disponible»: `hard_limit − reserved − committed` (la misma
    cuenta de la sentencia que reserva). `spent` NO se resta: un `COMMIT` ya lo suma a `committed`, y restarlo otra
    vez contaría el gasto dos veces."""

    name: str
    period: str
    currency: str
    hard_limit: Decimal
    soft_limit: Decimal | None
    reserved: Decimal
    committed: Decimal
    spent: Decimal
    remaining: Decimal


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
        hubiera duplicados (imposible desde la ADR 0026: el nombre es único en la base de datos)."""
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

    def summary(self) -> BudgetSummary | None:
        """El presupuesto autorizado con su saldo, o `None` si el propietario no ha autorizado ninguno. Solo lee: no
        crea el presupuesto ni su saldo (un presupuesto sin fila de saldo es «nada movido», como lo lee `snapshot`)."""
        budget = self.find_budget()
        if budget is None:
            return None
        allocation = self._db.query(BudgetAllocation).filter_by(budget_id=budget.id).first()
        hard_limit = _money(budget.hard_limit)
        reserved = _money(allocation.reserved) if allocation else Decimal("0.00")
        committed = _money(allocation.committed) if allocation else Decimal("0.00")
        spent = _money(allocation.spent) if allocation else Decimal("0.00")
        return BudgetSummary(
            name=budget.name,
            period=budget.period,
            currency=self._describe(budget)["currency"],
            hard_limit=hard_limit,
            soft_limit=_money(budget.soft_limit) if budget.soft_limit is not None else None,
            reserved=reserved,
            committed=committed,
            spent=spent,
            remaining=hard_limit - reserved - committed,
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
        hard = _amount(hard_limit, "the hard limit")
        soft = _amount(soft_limit, "the soft limit") if soft_limit is not None else None
        if hard <= 0:
            raise ValidationError("the hard limit of a budget must be greater than zero")
        if hard > MAX_HARD_LIMIT:
            raise ValidationError(f"the hard limit cannot exceed {MAX_HARD_LIMIT}: there is no unlimited budget")
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
            before = {**self._describe(budget), "hard_limit": float(budget.hard_limit)}
            before["soft_limit"] = _as_float(budget.soft_limit)
            budget.hard_limit = float(hard)
            budget.soft_limit = float(soft) if soft is not None else None
        self._allocation(budget)
        self._db.add(
            AuditLog(
                actor=actor,
                action="budget.authorise",
                resource=f"budget:{budget.id}",
                before=before,
                after={**self._describe(budget), "hard_limit": float(hard), "soft_limit": _as_float(soft)},
                correlation_id=correlation_id or new_correlation_id(),
            )
        )
        self._db.commit()
        return budget

    def _describe(self, budget: Budget) -> dict:
        """Qué autoriza exactamente la fila: el ámbito (su nombre y periodo) y la moneda. Quien lee la auditoría
        no tiene que adivinar a qué dinero se refiere un importe."""
        return {"scope": budget.name, "period": budget.period, "currency": ACCOUNTING_CURRENCY}

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
        if self._db.query(FinancialEvent.id).filter_by(type="RESERVE", reference=reference).first() is not None:
            # Una referencia se reserva **una** vez (ADR 0026; lo garantiza también la base de datos). Reintentar una
            # reserva que sigue viva es lo que `idempotent` permite; reservar otra vez lo que ya se liquidó, no: el
            # gasto nuevo es otro gasto y necesita otra referencia.
            if idempotent and self.outstanding(reference) > 0:
                return True
            raise ValidationError(
                f"reference {reference} was already reserved: a new spend needs a new reference, "
                "and a settled reservation is not reserved again"
            )

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
        """La reserva VIVA de `reference` pasa a comprometida y gastada. Devuelve `True` si la comprometió.

        `False` y **no escribe nada** si no hay presupuesto autorizado, si esa referencia no tiene una reserva viva
        (nunca se reservó, o ya se comprometió o se liberó) o si otra operación la liquidó mientras tanto: sin reserva
        no hay nada que comprometer. `ValidationError` si `amount` no es exactamente lo reservado (ver `_move`)."""
        return self._move(amount, reference, "COMMIT")

    def record_release(self, *, amount: float, reference: str) -> bool:
        """La reserva VIVA de `reference` se libera, sin tocar lo comprometido ni lo gastado. Mismo contrato que
        `record_commit`: sin reserva viva de esa referencia, no escribe nada y devuelve `False`."""
        return self._move(amount, reference, "RELEASE")

    def _move(self, amount: float, reference: str, kind: str) -> bool:
        """Liquida (compromete o libera) la reserva viva de `reference`.

        **La invariante vive aquí**, en el libro, y no en quien llama: se liquida SOLO lo reservado de ESA
        referencia, una sola vez y por su importe exacto.

        - Sin presupuesto autorizado, o sin reserva viva de la referencia (`outstanding == 0`: nunca reservada, o ya
          liquidada): no se escribe ningún evento ni se toca el saldo, y se devuelve `False`. Un `COMMIT`/`RELEASE`
          huérfano antes sumaba dinero que nadie reservó, o restaba del agregado la reserva de OTRA operación.
        - Con reserva viva, `amount` tiene que ser exactamente `outstanding(reference)`: la restricción única de la base
          (ADR 0026) admite UNA liquidación por referencia, así que una parcial dejaría un resto vivo que nadie puede
          cerrar, y una mayor comprometería dinero no reservado. Otro importe es un `ValidationError` y no escribe nada.
        - Dos liquidaciones de la misma referencia a la vez se ordenan con un lock por referencia (PostgreSQL): la
          segunda ve la reserva ya liquidada y no hace nada. La restricción única sigue siendo el respaldo."""
        budget = self.find_budget()
        if budget is None:
            return False
        delta = Decimal(str(amount))
        self._serialise(f"settle:{reference}")
        live = self.outstanding(reference)
        if live <= 0:
            return False
        if delta != live:
            raise ValidationError(
                f"{reference}: cannot {kind.lower()} {delta}; the live reservation is {live} and a reservation is "
                "settled once, for exactly what was reserved"
            )
        allocation = self._allocation(budget)
        # Aritmética de la base de datos, no «leer el total, sumar en Python y escribir»: con dos peticiones a la vez
        # la segunda habría pisado la suma de la primera. La fila queda bloqueada por el UPDATE hasta el commit, así que
        # las peticiones concurrentes se ordenan solas. Nunca negativo: respaldo por si el saldo ya viniera desajustado.
        values: dict[str, object] = {
            "reserved": case((BudgetAllocation.reserved - delta > 0, BudgetAllocation.reserved - delta), else_=0)
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
        """El saldo del presupuesto, creándolo si falta. Con dos primeras reservas a la vez, sin más, las dos lo
        creaban (medido: 3 de 12 pruebas con 30 hilos dejaron entre 2 y 4 filas, y cada comprobación de límite miraba la
        suya). Ahora la creación se serializa por presupuesto y, además, la base de datos solo admite una fila."""
        allocation = self._db.query(BudgetAllocation).filter_by(budget_id=budget.id).first()
        if allocation is None:
            self._serialise(f"allocation:{budget.id}")
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


def _amount(value: float, what: str) -> Decimal:
    """Un importe de verdad: finito, y en céntimos (más decimales se redondearían a otra cosa distinta de lo que se
    escribió)."""
    try:
        amount = Decimal(str(value))
    except ArithmeticError as exc:
        raise ValidationError(f"{what} must be a number") from exc
    if not amount.is_finite():
        raise ValidationError(f"{what} must be a finite number")
    try:
        in_cents = amount == amount.quantize(_CENT)
    except ArithmeticError as exc:  # un exponente enorme no cabe ni en la precisión de un importe
        raise ValidationError(f"{what} is out of range") from exc
    if not in_cents:
        raise ValidationError(f"{what} cannot have more than two decimals")
    return amount


def _money(value) -> Decimal:
    """Un importe de la base de datos, en céntimos exactos (las columnas son `Numeric(12, 2)`)."""
    return Decimal(str(value)).quantize(_CENT)


def _as_float(value) -> float | None:
    return float(value) if value is not None else None
