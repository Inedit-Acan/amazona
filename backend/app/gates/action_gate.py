"""El ActionGate: qué puede ejecutarse y qué no (Milestone 33, plan maestro §7).

Hasta aquí el pipeline seguía adelante con un `NO_GO` de legal o de economía
(ADR 0005 §Decisión). El plan maestro lo acepta **para análisis** y lo prohíbe
**para acciones con efecto**: publicar, anunciar, gastar, comprar, pagar,
enviar, reembolsar, cambiar un precio real o mandar una comunicación
contractual. Este módulo es quien traza esa raya.

Es una función pura, del mismo linaje que `evaluate_decision` (grafo CEO) y
`assess_pipeline_run` (revisión post-hoc): entradas explícitas, salida
determinista, cero acceso a base de datos. Quien recoge las entradas reales es
`app/gates/service.py`. Esa separación es lo que permite que las seis
situaciones que el plan exige probar sean una tabla de casos y no un montaje.

La regla que ordena todo lo demás: **los vetos ganan**. Una aprobación humana
puede levantar una duda, nunca un veto — ni un `NO_GO` legal, ni el kill switch,
ni un presupuesto agotado. Si algún día alguien necesita saltarse eso, que
cambie el veto, no que lo firme.
"""

from dataclasses import dataclass, field
from enum import StrEnum

from app.budgets.engine import BudgetAssessment, BudgetStatus
from app.core.config import Environment
from app.permissions.policies import PermissionResult


class SideEffectAction(StrEnum):
    """Las nueve acciones con efecto del plan maestro §7, más `COLLECT_PAYMENT` (Milestone 44).

    `COLLECT_PAYMENT` es la décima: abrir un cobro en una pasarela no es un pago nuestro (no sale dinero), pero sí
    una acción externa con consecuencias, y por eso se gobierna con el mismo gate en vez de quedar fuera de él.

    Todo lo que no está aquí es análisis y no pasa por el gate: investigar,
    cotizar, calcular márgenes, comprobar requisitos legales, prever, simular y
    comparar no le hacen nada a nadie fuera del sistema.
    """

    PUBLISH_PRODUCT = "publish_product"
    ACTIVATE_ADS = "activate_ads"
    SPEND_MONEY = "spend_money"
    PURCHASE_SUPPLIER = "purchase_supplier"
    MAKE_PAYMENT = "make_payment"
    SHIP_ORDER = "ship_order"
    REFUND = "refund"
    CHANGE_PRICE = "change_price"
    SEND_CONTRACT_COMMUNICATION = "send_contract_communication"
    COLLECT_PAYMENT = "collect_payment"


#: Las que gastan del presupuesto operativo. Se distinguen porque el presupuesto y la autonomía económica solo
#: tienen sentido sobre ellas: publicar un producto no gasta.
#:
#: `REFUND` ya no está aquí (Milestone 44, ADR 0028 §5): devolver a un cliente lo que cobró no es un gasto
#: discrecional ni sale del presupuesto de anuncios y compras. Una operación cuyo coste depende de la propia
#: operación (un envío) declara su `ActionCost` en vez de depender solo del tipo de acción.
SPENDING_ACTIONS: frozenset[SideEffectAction] = frozenset(
    {
        SideEffectAction.ACTIVATE_ADS,
        SideEffectAction.SPEND_MONEY,
        SideEffectAction.PURCHASE_SUPPLIER,
        SideEffectAction.MAKE_PAYMENT,
    }
)

#: Acciones que **no se juzgan por el producto**: un `NO_GO` legal no impide devolver dinero cobrado, y la
#: economía de un producto no decide si se le devuelve el pago a quien ya lo hizo. Es una obligación, no una
#: decisión comercial. Se aplica en la función pura para que un llamador descuidado no pueda vetarlo.
LEGAL_NOT_CONSULTED: frozenset[SideEffectAction] = frozenset({SideEffectAction.REFUND})
ECONOMICS_NOT_CONSULTED: frozenset[SideEffectAction] = frozenset(
    {SideEffectAction.REFUND, SideEffectAction.COLLECT_PAYMENT}
)


class CostKind(StrEnum):
    #: Cero **declarado**, con su procedencia (el adaptador simulado dice «0 € simulado»).
    ZERO = "ZERO"
    KNOWN = "KNOWN"
    #: No se sabe lo que cuesta. **Nunca significa cero.**
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ActionCost:
    """Lo que cuesta **esta operación**, declarado por quien sabe (el adaptador o el servicio de dominio).

    El tipo de acción dice si una clase de acción suele gastar; esto dice lo que gasta una operación concreta:
    un envío puede costar cero en un adaptador simulado y un importe en uno real. `UNKNOWN` se trata como gasto y
    se deniega (no se inventa un coste ni se ejecuta un gasto real a ciegas); `KNOWN` mayor que cero pasa por la
    misma disciplina económica de siempre (evaluar, reservar, comprometer)."""

    kind: CostKind
    #: Solo con `KNOWN`. En `float` porque el libro de presupuesto lo es (frontera legada, `legacy_float`).
    amount: float | None = None
    provenance: str | None = None

    def __post_init__(self) -> None:
        if self.kind is CostKind.KNOWN and (self.amount is None or self.amount <= 0):
            raise ValueError("a KNOWN cost needs a positive amount: use ZERO for a declared zero")
        if self.kind is not CostKind.KNOWN and self.amount is not None:
            raise ValueError(f"a {self.kind} cost carries no amount")

    @classmethod
    def zero(cls, provenance: str) -> "ActionCost":
        return cls(kind=CostKind.ZERO, provenance=provenance)

    @classmethod
    def known(cls, amount: float, provenance: str | None = None) -> "ActionCost":
        return cls(kind=CostKind.KNOWN, amount=amount, provenance=provenance)

    @classmethod
    def unknown(cls) -> "ActionCost":
        return cls(kind=CostKind.UNKNOWN)

    @property
    def spends(self) -> bool:
        """Si la operación se trata como gasto: coste desconocido o conocido y positivo."""
        return self.kind is CostKind.UNKNOWN or self.kind is CostKind.KNOWN

    def as_amount(self) -> float | None:
        """El importe que se le pregunta al presupuesto: `0.0` si es cero declarado, `None` si no se sabe."""
        if self.kind is CostKind.ZERO:
            return 0.0
        return self.amount


class GateOutcome(StrEnum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"


class HumanApproval(StrEnum):
    """Qué ha dicho una persona sobre **esta** acción concreta."""

    #: Nadie ha decidido todavía.
    NONE = "NONE"
    GRANTED = "GRANTED"
    REJECTED = "REJECTED"


#: Entornos donde una acción de gasto no se ejecuta sola. El plan maestro §33 es
#: explícito: no otorgar autonomía económica todavía.
_ENFORCING: frozenset[Environment] = frozenset({Environment.STAGING, Environment.PRODUCTION})


#: Lo que el presupuesto responde sobre el importe de esta acción. Es la evaluación del
#: libro (`BudgetLedgerService.assess` → `BudgetAssessment`): llega aquí como resultado, no
#: como números sueltos, porque el gate decide y no calcula. Con sus estados (`AVAILABLE`,
#: `EXHAUSTED`, `NO_BUDGET_RECORD`, `UNKNOWN_COST`...) y **cerrada por defecto**: una señal
#: que nadie evaluó (`NOT_EVALUATED`) no aprueba, porque la ausencia de información no es un
#: permiso.
BudgetSignal = BudgetAssessment


def _unevaluated_budget() -> BudgetAssessment:
    return BudgetAssessment(
        approved=False, status=BudgetStatus.NOT_EVALUATED, reason="the budget of this action was not evaluated"
    )


@dataclass(frozen=True)
class GateInput:
    """Todo lo que el gate mira. Las siete entradas del plan maestro §7:
    decisión económica, decisión legal, estado de riesgo, presupuesto,
    aprobación humana, permisos y entorno."""

    action: SideEffectAction
    #: `GO` | `REVIEW` | `NO_GO` | None si ese paso no se ha ejecutado.
    legal_recommendation: str | None = None
    economics_recommendation: str | None = None
    #: El kill switch operativo de la ADR 0006. Apagado, no se ejecuta nada.
    kill_switch_enabled: bool = True
    #: Una operación anterior de este mismo sitio puede haberse ejecutado y no se conoce su resultado
    #: (`UNKNOWN_OUTCOME`). Repetir el efecto sin resolverlo podría duplicarlo.
    unresolved_outcome: bool = False
    budget: BudgetSignal = field(default_factory=_unevaluated_budget)
    human_approval: HumanApproval = HumanApproval.NONE
    #: Lo que `PermissionEngine` responde para el rol de quien lo pidió. None
    #: cuando no hay rol que consultar (una ejecución encolada sin identidad en
    #: desarrollo).
    permission: PermissionResult | None = None
    environment: Environment = Environment.DEVELOPMENT
    #: El coste declarado de esta operación (Milestone 44). `None` = el que corresponde al tipo de acción.
    cost: ActionCost | None = None

    @property
    def is_spending(self) -> bool:
        return self.action in SPENDING_ACTIONS or (self.cost is not None and self.cost.spends)


@dataclass(frozen=True)
class GateDecision:
    outcome: GateOutcome
    reasons: list[str] = field(default_factory=list)

    @property
    def allowed(self) -> bool:
        return self.outcome is GateOutcome.ALLOW

    def as_detail(self) -> dict:
        """Lo que se guarda en el paso y se audita."""
        return {"outcome": self.outcome.value, "reasons": list(self.reasons)}


def evaluate_action(gate_input: GateInput) -> GateDecision:
    """¿Puede ejecutarse esta acción con efecto?

    El orden no es decorativo:

    1. **Los vetos**, que nada levanta: kill switch, `NO_GO` legal, presupuesto
       insuficiente, permiso denegado y un rechazo humano explícito.
    2. **La autorización humana**, que solo puede levantar dudas —y solo si ha
       llegado hasta aquí sin tropezar con un veto—.
    3. **Las dudas**: `REVIEW`, un permiso que pide aprobación, y el gasto en un
       entorno que ya toca sistemas reales.
    4. Si no queda nada que objetar, `ALLOW`.
    """
    reasons: list[str] = []
    legal = None if gate_input.action in LEGAL_NOT_CONSULTED else gate_input.legal_recommendation
    economics = None if gate_input.action in ECONOMICS_NOT_CONSULTED else gate_input.economics_recommendation

    # --- 1. Vetos ---------------------------------------------------------
    if not gate_input.kill_switch_enabled:
        reasons.append("the pipeline kill switch is off")
    if gate_input.unresolved_outcome:
        reasons.append(
            "an earlier external action of this step has an unknown outcome: reconcile it before acting again"
        )
    if legal == "NO_GO":
        reasons.append("legal recommendation is NO_GO")
    if economics == "NO_GO" and gate_input.is_spending:
        reasons.append("economics recommendation is NO_GO and this action spends money")
    if gate_input.is_spending and not gate_input.budget.approved:
        reasons.append(gate_input.budget.reason or "the budget does not cover this action")
    if gate_input.permission is PermissionResult.DENIED:
        reasons.append("the actor is not allowed to perform external spend actions")
    if gate_input.human_approval is HumanApproval.REJECTED:
        reasons.append("a human rejected this action")

    if reasons:
        return GateDecision(outcome=GateOutcome.DENY, reasons=reasons)

    # --- 2. Autorización humana ------------------------------------------
    if gate_input.human_approval is HumanApproval.GRANTED:
        return GateDecision(outcome=GateOutcome.ALLOW, reasons=["a human authorized this action"])

    # --- 3. Dudas ---------------------------------------------------------
    if economics == "NO_GO":
        # No gasta, así que no es un veto — pero publicar algo que las cuentas
        # desaconsejan no lo decide el sistema solo.
        reasons.append("economics recommendation is NO_GO")
    if legal == "REVIEW":
        reasons.append("legal recommendation is REVIEW")
    if economics == "REVIEW":
        reasons.append("economics recommendation is REVIEW")
    if gate_input.permission is PermissionResult.HUMAN_APPROVAL_REQUIRED:
        reasons.append("the actor's role requires human approval for external spend")
    if gate_input.is_spending and gate_input.environment in _ENFORCING:
        reasons.append(f"spending is never automatic in {gate_input.environment}")

    if reasons:
        return GateDecision(outcome=GateOutcome.REQUIRE_APPROVAL, reasons=reasons)

    # --- 4. Nada que objetar ---------------------------------------------
    return GateDecision(outcome=GateOutcome.ALLOW, reasons=[])
