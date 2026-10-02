"""Quien le da al ActionGate sus entradas reales (Milestone 33).

La función `evaluate_action` es pura a propósito. Este servicio es la parte
sucia: lee el kill switch, pregunta al presupuesto, mira qué dijeron los pasos
de análisis de esta misma ejecución, consulta el permiso del rol que la pidió,
mira en qué entorno estamos, y **audita el resultado**.

No decide nada por su cuenta. Si aquí apareciera un `if` de negocio, estaría en
el sitio equivocado.
"""

from sqlalchemy.orm import Session

from app.budgets.engine import BudgetStatus
from app.budgets.service import BudgetLedgerService
from app.core.config import Settings, get_settings
from app.db.models.audit import AuditLog
from app.gates.action_gate import (
    SPENDING_ACTIONS,
    ActionCost,
    BudgetSignal,
    GateDecision,
    GateInput,
    GateOutcome,
    HumanApproval,
    SideEffectAction,
    evaluate_action,
)
from app.permissions.engine import PermissionEngine
from app.permissions.policies import ActionType, PermissionResult
from app.pipeline.kill_switch import PipelineKillSwitchService

#: Cómo se llama en la auditoría cada resultado del gate. Buscar
#: `action_gate.deny` responde «qué ha impedido el sistema, y por qué».
AUDIT_ACTION: dict[GateOutcome, str] = {
    GateOutcome.ALLOW: "action_gate.allow",
    GateOutcome.DENY: "action_gate.deny",
    GateOutcome.REQUIRE_APPROVAL: "action_gate.require_approval",
}

GATE_ACTOR = "action-gate"

#: Qué permiso consulta cada acción. Todas pedían `EXTERNAL_SPEND` (cuya política por defecto es pedir aprobación
#: humana): correcto para gastar, y un bloqueo permanente para abrir un cobro o devolver un pago (Milestone 44,
#: ADR 0028 §7). Lo que no esté aquí sigue consultando `EXTERNAL_SPEND`.
ACTION_PERMISSION: dict[SideEffectAction, ActionType] = {
    SideEffectAction.COLLECT_PAYMENT: ActionType.PAYMENT_COLLECT,
    SideEffectAction.REFUND: ActionType.MONEY_REFUND,
}


class ActionGateService:
    def __init__(
        self,
        db: Session,
        *,
        settings: Settings | None = None,
        kill_switch: PipelineKillSwitchService | None = None,
    ) -> None:
        self._db = db
        self._settings = settings or get_settings()
        self._kill_switch = kill_switch or PipelineKillSwitchService(db)

    def evaluate(
        self,
        action: SideEffectAction,
        *,
        legal_recommendation: str | None = None,
        economics_recommendation: str | None = None,
        amount: float | None = None,
        human_approval: HumanApproval = HumanApproval.NONE,
        actor_role: str | None = None,
        unresolved_outcome: bool = False,
        cost: ActionCost | None = None,
    ) -> GateDecision:
        """`cost` es lo que cuesta **esta operación** (Milestone 44). Sin él, manda el tipo de acción y `amount`
        como siempre. Con él, una operación de un tipo que no gasta pero cuyo coste es conocido y positivo, o
        desconocido, se trata como gasto: el desconocido se deniega y nunca equivale a cero."""
        simulated = self._settings.operating_in_simulation
        gate_input = GateInput(
            action=action,
            legal_recommendation=legal_recommendation,
            economics_recommendation=economics_recommendation,
            kill_switch_enabled=self._kill_switch.is_enabled(),
            unresolved_outcome=unresolved_outcome,
            budget=self._budget_signal(action, amount, cost, simulated=simulated),
            human_approval=human_approval,
            permission=self._permission(actor_role, action, simulated=simulated),
            environment=self._settings.environment,
            cost=cost,
        )
        return evaluate_action(gate_input)

    def audit(
        self,
        decision: GateDecision,
        *,
        action: SideEffectAction,
        resource: str,
        correlation_id: str,
        actor: str = GATE_ACTOR,
    ) -> None:
        """Deja constancia. Un `DENY` sin rastro es indistinguible de un fallo:
        alguien tiene que poder preguntar después qué se impidió y por qué."""
        self._db.add(
            AuditLog(
                actor=actor,
                action=AUDIT_ACTION[decision.outcome],
                resource=resource,
                before=None,
                after={"side_effect_action": action.value, **decision.as_detail()},
                correlation_id=correlation_id,
            )
        )

    # --- Entradas ----------------------------------------------------------

    def _permission(
        self, actor_role: str | None, action: SideEffectAction, *, simulated: bool
    ) -> PermissionResult | None:
        """Lo que la política dice del rol que pidió esto.

        Sin rol no hay nada que consultar, y eso significa cosas distintas según el
        despliegue: en una **simulación** (desarrollo, todos los proveedores `MOCK`) una
        ejecución puede no llevar identidad y se sigue como siempre; fuera de ella, no saber
        quién pide no es un permiso, y el motor de permisos ya responde `DENIED` a un rol
        ausente: aquí no se le pregunta con una respuesta distinta solo porque el
        solicitante no se identificó."""
        if actor_role is None:
            return None if simulated else PermissionResult.DENIED
        return PermissionEngine().check(
            actor_role=actor_role, action=ACTION_PERMISSION.get(action, ActionType.EXTERNAL_SPEND)
        )

    def _budget_signal(
        self, action: SideEffectAction, amount: float | None, cost: ActionCost | None = None, *, simulated: bool
    ) -> BudgetSignal:
        """Lo que el presupuesto **real** —el de la base de datos, el mismo que consulta el
        CEO— dice de esta acción. Una acción que no gasta no le pregunta nada; una que gasta
        recibe su estado (`AVAILABLE`, `EXHAUSTED`, `NO_BUDGET_RECORD`, `UNKNOWN_COST`...): la
        ausencia de presupuesto o de importe no es un permiso."""
        spends = action in SPENDING_ACTIONS or (cost is not None and cost.spends)
        if not spends:
            return BudgetSignal(approved=True, status=BudgetStatus.NOT_APPLICABLE)
        # Con coste declarado, manda el coste de la operación: `None` si no se sabe (y eso deniega).
        declared = cost.as_amount() if cost is not None else amount
        return BudgetLedgerService(self._db).assess(declared, simulated=simulated)
