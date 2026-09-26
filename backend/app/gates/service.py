"""Quien le da al ActionGate sus entradas reales (Milestone 33).

La función `evaluate_action` es pura a propósito. Este servicio es la parte
sucia: lee el kill switch, pregunta al presupuesto, mira qué dijeron los pasos
de análisis de esta misma ejecución, consulta el permiso del rol que la pidió,
mira en qué entorno estamos, y **audita el resultado**.

No decide nada por su cuenta. Si aquí apareciera un `if` de negocio, estaría en
el sitio equivocado.
"""

from sqlalchemy.orm import Session

from app.budgets.engine import BudgetEngine, BudgetState
from app.core.config import Settings, get_settings
from app.db.models.audit import AuditLog
from app.db.models.budget import Budget, BudgetAllocation
from app.gates.action_gate import (
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
    ) -> GateDecision:
        gate_input = GateInput(
            action=action,
            legal_recommendation=legal_recommendation,
            economics_recommendation=economics_recommendation,
            kill_switch_enabled=self._kill_switch.is_enabled(),
            budget=self._budget_signal(amount),
            human_approval=human_approval,
            permission=self._permission(actor_role),
            environment=self._settings.environment,
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

    def _permission(self, actor_role: str | None) -> PermissionResult | None:
        """Lo que la política dice del rol que pidió esto. Sin rol no hay nada
        que consultar: en desarrollo una ejecución puede no llevar identidad, y
        eso no es lo mismo que un rol sin permiso."""
        if actor_role is None:
            return None
        return PermissionEngine().check(actor_role=actor_role, action=ActionType.EXTERNAL_SPEND)

    def _budget_signal(self, amount: float | None) -> BudgetSignal:
        """El presupuesto real, con la misma matemática que ya usa el
        orquestador (`BudgetEngine`): no se reimplementa aquí."""
        if amount is None:
            return BudgetSignal()

        budget = self._db.query(Budget).order_by(Budget.created_at).first()
        if budget is None:
            # Nadie ha fijado presupuesto todavía. No es lo mismo que un
            # presupuesto a cero: no hay límite que oponer.
            return BudgetSignal()

        allocation = self._db.query(BudgetAllocation).filter_by(budget_id=budget.id).first()
        # `budgets` no tiene límite por acción: `BudgetState` lo deja en None y
        # `BudgetEngine` solo comprueba el techo duro y el aviso del blando.
        state = BudgetState(
            hard_limit=float(budget.hard_limit),
            soft_limit=float(budget.soft_limit) if budget.soft_limit is not None else None,
            reserved=float(allocation.reserved) if allocation else 0.0,
            committed=float(allocation.committed) if allocation else 0.0,
            spent=float(allocation.spent) if allocation else 0.0,
        )
        decision = BudgetEngine().authorize(amount=float(amount), state=state)
        return BudgetSignal(approved=decision.approved, reason=decision.reason)
