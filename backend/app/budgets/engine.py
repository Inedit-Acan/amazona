from dataclasses import dataclass
from enum import StrEnum

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


class BudgetStatus(StrEnum):
    """Qué dice el presupuesto **real** (el de la base de datos) sobre un gasto.

    Ninguno de los estados que aprueban significa «no hay información, así que sí»:
    cada uno dice por qué se aprueba, y la ausencia de información aprueba solo donde se
    declara que es una simulación (`SIMULATED_NO_BUDGET`).
    """

    #: Nadie ha llegado a evaluarlo. No aprueba: una señal sin evaluar no es un permiso.
    NOT_EVALUATED = "not_evaluated"
    #: La acción no gasta dinero, así que el presupuesto no tiene nada que decir.
    NOT_APPLICABLE = "not_applicable"
    #: Coste conocido y cero. No consume presupuesto, aunque esté agotado.
    ZERO_COST = "zero_cost"
    #: Hay presupuesto autorizado y el importe cabe.
    AVAILABLE = "available"
    #: Hay presupuesto autorizado y el importe no cabe.
    EXHAUSTED = "exhausted"
    #: Es una acción de gasto y el propietario no ha autorizado ningún presupuesto. Deniega.
    NO_BUDGET_RECORD = "no_budget_record"
    #: Es una acción de gasto y se ignora cuánto cuesta. Un coste desconocido no es cero. Deniega.
    UNKNOWN_COST = "unknown_cost"
    #: No hay presupuesto autorizado pero todo el despliegue es simulado: no sale dinero de
    #: verdad. Aprueba, y queda dicho que fue por eso y no porque «no haya límite».
    SIMULATED_NO_BUDGET = "simulated_no_budget"


@dataclass(frozen=True)
class BudgetAssessment:
    """La respuesta del presupuesto a un gasto: el estado, si aprueba y por qué no."""

    approved: bool
    reason: str | None = None
    status: BudgetStatus = BudgetStatus.NOT_EVALUATED
    warning: str | None = None


@dataclass(frozen=True)
class BudgetSnapshot:
    """El presupuesto autorizado y lo consumido, tal como está en la base de datos en
    este instante. No es un estado autoritativo: es una foto de la fila."""

    hard_limit: float
    soft_limit: float | None
    reserved: float
    committed: float
    spent: float


def assess_spend(*, amount: float | None, snapshot: BudgetSnapshot | None, simulated: bool) -> BudgetAssessment:
    """¿Cabe este gasto? Función pura, como `evaluate_action` y `evaluate_api_call`.

    `amount` es lo que cuesta la acción; `None` significa que **no se sabe**, y eso
    deniega. `snapshot` es el presupuesto autorizado; `None` significa que el propietario
    no ha autorizado ninguno. `simulated` es si todo el despliegue es simulado.
    """
    if amount is None:
        return BudgetAssessment(
            approved=False,
            status=BudgetStatus.UNKNOWN_COST,
            reason="the cost of this action is unknown, and an unknown cost is not zero",
        )
    if amount < 0:
        return BudgetAssessment(
            approved=False, status=BudgetStatus.UNKNOWN_COST, reason=f"a negative amount ({amount}) is not a cost"
        )
    if amount == 0:
        return BudgetAssessment(approved=True, status=BudgetStatus.ZERO_COST)
    if snapshot is None:
        if simulated:
            return BudgetAssessment(
                approved=True,
                status=BudgetStatus.SIMULATED_NO_BUDGET,
                reason="no budget is authorised, and this deployment is simulated: no money moves",
            )
        return BudgetAssessment(
            approved=False,
            status=BudgetStatus.NO_BUDGET_RECORD,
            reason="no budget has been authorised for this spend; the owner has to authorise one first",
        )

    state = BudgetState(
        hard_limit=snapshot.hard_limit,
        soft_limit=snapshot.soft_limit,
        reserved=snapshot.reserved,
        committed=snapshot.committed,
        spent=snapshot.spent,
    )
    decision = BudgetEngine().authorize(amount=amount, state=state)
    return BudgetAssessment(
        approved=decision.approved,
        status=BudgetStatus.AVAILABLE if decision.approved else BudgetStatus.EXHAUSTED,
        reason=decision.reason,
        warning=decision.warning,
    )
