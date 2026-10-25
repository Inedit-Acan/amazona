"""Propuestas de acción del CEO y su confirmación (M52).

PROPONER no es EJECUTAR. Aquí hay dos mitades que no se tocan:

- `draft_*`: del argumento que pide el modelo sale una `ProposalDraft` — tras COMPROBAR contra el estado real que la
  acción es posible (la tarea está
  FAILED, el intento nombrado es el último, la misión es reanudable, la aprobación sigue pendiente…). Nada se escribe
  más que la propuesta.
- `ActionService.confirm` / `reject`: lo que hace el PROPIETARIO, autenticado, desde una tarjeta. Reclama la propuesta
  con un compare-and-set
  (`PROPOSED → EXECUTING`, una sola sentencia: de N confirmaciones a la vez, una gana), y ejecuta con los MISMOS
  servicios que las rutas existentes
  (`TaskRecoveryService`, `CEOOrchestrator`, `resolve_approval`), que vuelven a validar todo. Ninguna herramienta del
  modelo llega aquí.
"""

import datetime
from dataclasses import dataclass
from typing import Any

from sqlalchemy import update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from app.agents.manager import AgentManager
from app.api.approvals import reserved_for_approval, resolve_approval
from app.auth.actor import Actor
from app.ceo.mission import load_mission, resolve_project_id
from app.ceo.orchestrator import CEOOrchestrator
from app.ceo_chat import store
from app.ceo_chat.redaction import redact, redact_text
from app.ceo_chat.tools import (
    ProposeCreateMissionIn,
    ProposeReassignTaskIn,
    ProposeResolveApprovalIn,
    ProposeResumeMissionIn,
    ProposeRetryTaskIn,
)
from app.core.config import Settings
from app.core.errors import AmazonaError, ConflictError, NotFoundError, ValidationError
from app.core.ids import new_correlation_id, new_id
from app.db.models.approval import Approval
from app.db.models.ceo_chat import CeoActionProposal, CeoConversation
from app.db.models.objective import Objective
from app.db.models.task import Task
from app.tasks.assignment import ORCHESTRATOR_CAPABILITIES, load_relations
from app.tasks.recovery import TaskRecoveryService, describe_recovery
from app.tasks.schemas import TaskStatus

_REASSIGNABLE = (TaskStatus.FAILED.value, TaskStatus.BLOCKED.value, TaskStatus.PENDING.value)


@dataclass(frozen=True)
class ProposalDraft:
    action_type: str
    target: dict[str, Any]
    parameters: dict[str, Any]
    reason: str
    estimated_effects: dict[str, Any]
    risk_level: str
    #: El scope de idempotencia REAL de la operación (`tasks.retry`…); `None` si la operación es un compare-and-set
    #: (aprobaciones).
    idempotency_scope: str | None


def _effects(summary: str, **more: Any) -> dict[str, Any]:
    """Los efectos ESTIMADOS que se le enseñan al propietario. Las misiones del chat no piden gasto: el coste externo
    es 0 y el presupuesto no se mueve,
    salvo una aprobación, que sí liquida lo que ya estaba reservado."""
    return {"summary": summary, "external_cost_eur": 0, "budget_effect": "none", **more}


# --- Propuestas
# ----------------------------------------------------------------------------------------------------------------------


def draft_create_mission(args: ProposeCreateMissionIn) -> ProposalDraft:
    objective_id = new_id()
    return ProposalDraft(
        action_type="create_mission",
        target={"objective_id": objective_id, "title": args.title},
        parameters={
            "objective_id": objective_id,
            "title": args.title,
            "description": args.description,
            "context": args.context or {},
        },
        reason=args.reason,
        estimated_effects=_effects(
            "Crea el objetivo y ejecuta una misión nueva con los agentes simulados: proyecto, cinco tareas y una "
            "decisión. No pide gasto.",
            creates=["objective", "project", "tasks", "decision"],
        ),
        risk_level="medium",
        idempotency_scope="objectives.run",
    )


def draft_retry_task(db: Session, manager: AgentManager, args: ProposeRetryTaskIn) -> ProposalDraft:
    task = db.get(Task, args.task_id)
    if task is None:
        raise NotFoundError(f"task {args.task_id} not found")
    if task.capability in ORCHESTRATOR_CAPABILITIES:
        raise ValidationError(f"task {task.name!r} belongs to the orchestrator: it is never retried through an agent")
    if task.status != TaskStatus.FAILED:
        raise ConflictError(f"task {task.name!r} is {task.status}: only a FAILED task can be retried")
    known = manager.agent_ids()
    relation = load_relations(db, [task], known)[task.id]
    recovery = describe_recovery(
        task_status=task.status,
        assigned_agent_id=task.assigned_agent_id,
        known_agent_ids=known,
        traces=relation.executions,
        relation_status=relation.status,
    )
    last_attempt = recovery.next_attempt - 1
    if args.after_attempt != last_attempt:
        raise ConflictError(
            f"the last attempt of task {task.name!r} is {last_attempt}, not {args.after_attempt}: "
            f"propose it again with after_attempt={last_attempt}"
        )
    if not recovery.can_retry:
        raise ConflictError(f"task {task.name!r} cannot be retried now: its recovery state is {recovery.kind.value}")
    return ProposalDraft(
        action_type="retry_task",
        target={"task_id": task.id, "task_name": task.name, "agent_id": task.assigned_agent_id},
        parameters={"task_id": task.id, "after_attempt": args.after_attempt, "reason": args.reason},
        reason=args.reason,
        estimated_effects=_effects(
            f"Un intento más de {task.name} con {task.assigned_agent_id} (simulado): intento {recovery.next_attempt}. "
            "No reasigna ni ejecuta lo que depende de ella.",
            next_attempt=recovery.next_attempt,
        ),
        risk_level="low",
        idempotency_scope="tasks.retry",
    )


def draft_reassign_task(db: Session, manager: AgentManager, args: ProposeReassignTaskIn) -> ProposalDraft:
    task = db.get(Task, args.task_id)
    if task is None:
        raise NotFoundError(f"task {args.task_id} not found")
    if task.capability in ORCHESTRATOR_CAPABILITIES:
        raise ValidationError(f"task {task.name!r} belongs to the orchestrator and is never assigned to an agent")
    if task.status not in _REASSIGNABLE:
        raise ConflictError(
            f"task {task.name!r} is {task.status}: it can only be reassigned while FAILED, BLOCKED or PENDING"
        )
    capabilities = manager.capabilities_by_agent().get(args.agent_id)
    if capabilities is None:
        raise ValidationError(f"agent {args.agent_id!r} is not in the registry")
    if task.capability not in capabilities:
        raise ValidationError(f"agent {args.agent_id!r} does not declare the capability {task.capability!r}")
    if task.assigned_agent_id == args.agent_id:
        raise ConflictError(f"task {task.name!r} is already assigned to {args.agent_id!r}")
    return ProposalDraft(
        action_type="reassign_task",
        target={
            "task_id": task.id,
            "task_name": task.name,
            "from_agent_id": task.assigned_agent_id,
            "to_agent_id": args.agent_id,
        },
        parameters={"task_id": task.id, "agent_id": args.agent_id, "reason": args.reason},
        reason=args.reason,
        estimated_effects=_effects(
            f"Cambia el agente de {task.name} de {task.assigned_agent_id} a {args.agent_id}. "
            "No la ejecuta: reintentar es otra propuesta."
        ),
        risk_level="low",
        idempotency_scope="tasks.reassign",
    )


def draft_resume_mission(db: Session, manager: AgentManager, args: ProposeResumeMissionIn) -> ProposalDraft:
    project_id = resolve_project_id(db, args.objective_id, args.project_id)
    view = load_mission(db, manager, project_id)
    if not view.resumable:
        blockers = ", ".join(f"{b.task_name} ({b.reason.value})" for b in view.blockers) or "ninguno"
        raise ConflictError(
            f"the mission is {view.state.value}: it cannot be resumed. Blockers: {blockers}. "
            "Recover its tasks first (retry or reassign)."
        )
    assert view.current_decision_id is not None  # una misión reanudable tiene al menos una decisión
    return ProposalDraft(
        action_type="resume_mission",
        target={"objective_id": args.objective_id, "project_id": project_id},
        parameters={
            "objective_id": args.objective_id,
            "project_id": project_id,
            "after_decision_id": view.current_decision_id,
            "reason": args.reason,
        },
        reason=args.reason,
        estimated_effects=_effects(
            f"Ejecuta solo lo pendiente ({', '.join(view.pending_tasks)}) y escribe una decisión nueva; "
            "la anterior queda intacta.",
            pending_tasks=list(view.pending_tasks),
        ),
        risk_level="medium",
        idempotency_scope="objectives.resume",
    )


def draft_resolve_approval(db: Session, args: ProposeResolveApprovalIn) -> ProposalDraft:
    approval = db.get(Approval, args.approval_id)
    if approval is None:
        raise NotFoundError(f"approval {args.approval_id} not found")
    if approval.status != "PENDING":
        raise ConflictError(f"approval {approval.id} is {approval.status}: only a PENDING approval can be resolved")
    amount = float(approval.amount) if approval.amount is not None else None
    reserved = reserved_for_approval(db, approval.id)
    approve = args.decision == "approve"
    if reserved > 0:
        budget = f"{'compromete' if approve else 'libera'} {reserved:.2f} reservados en el presupuesto"
        budget_effect = "commit" if approve else "release"
    else:
        budget, budget_effect = "no mueve el presupuesto (no hay nada reservado para ella)", "none"
    return ProposalDraft(
        action_type="approve_approval" if approve else "reject_approval",
        target={"approval_id": approval.id, "decision_id": approval.decision_id, "action": approval.action},
        parameters={"approval_id": approval.id, "decision": args.decision, "reason": args.reason},
        reason=args.reason,
        estimated_effects={
            "summary": f"{'Aprueba' if approve else 'Rechaza'} la aprobación «{approval.action}»: {budget}.",
            "external_cost_eur": 0,
            "budget_effect": budget_effect,
            "approval_amount": amount,
        },
        risk_level="high" if amount else "medium",
        idempotency_scope=None,
    )


# --- Confirmación
# --------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Outcome:
    proposal: CeoActionProposal
    result_message_id: str | None


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


class ActionService:
    def __init__(self, db: Session, manager: AgentManager, settings: Settings) -> None:
        self._db = db
        self._manager = manager
        self._settings = settings

    def get_owned(self, actor: Actor, proposal_id: str) -> CeoActionProposal:
        """La propuesta, si la conversación es de quien pregunta. De otro usuario es «no existe», no «prohibido»."""
        self._db.expire_all()
        proposal = self._db.get(CeoActionProposal, proposal_id)
        conversation = self._db.get(CeoConversation, proposal.conversation_id) if proposal is not None else None
        if proposal is None or conversation is None or conversation.owner_subject != actor.subject:
            raise NotFoundError(f"proposal {proposal_id} not found")
        return proposal

    def _transition(self, proposal_id: str, *, to: str, expected: str, by: str | None) -> bool:
        """Compare-and-set en UNA sentencia: solo la petición que cambia la fila obtiene `True`."""
        result = self._db.execute(
            update(CeoActionProposal)
            .where(CeoActionProposal.id == proposal_id, CeoActionProposal.status == expected)
            .values(status=to, resolved_by=by, resolved_at=_now())
            .execution_options(synchronize_session=False)
        )
        return isinstance(result, CursorResult) and result.rowcount == 1

    def _claim(self, actor: Actor, proposal: CeoActionProposal, *, to: str) -> None:
        if not self._transition(proposal.id, to=to, expected="PROPOSED", by=actor.subject):
            self._db.rollback()
            self._db.expire_all()
            current = self._db.get(CeoActionProposal, proposal.id)
            state = current.status if current else "unknown"
            raise ConflictError(f"proposal {proposal.id} is {state}: a proposal is resolved once")
        self._db.commit()

    def reject(self, actor: Actor, proposal_id: str) -> Outcome:
        proposal = self.get_owned(actor, proposal_id)
        self._claim(actor, proposal, to="REJECTED")
        proposal = self.get_owned(actor, proposal_id)
        message = store.add_message(
            self._db,
            proposal.conversation_id,
            "assistant",
            "Has rechazado la propuesta. No se ha ejecutado nada.",
            {"kind": "action_result", "proposal_id": proposal.id, "status": "REJECTED"},
        )
        proposal.result_message_id = message.id
        store.audit(
            self._db,
            actor,
            "ceo.action_rejected",
            f"ceo_action:{proposal.id}",
            {
                "proposal_id": proposal.id,
                "action_type": proposal.action_type,
                "conversation_id": proposal.conversation_id,
            },
            proposal.correlation_id or new_correlation_id(),
        )
        self._db.commit()
        return Outcome(proposal, message.id)

    def confirm(self, actor: Actor, proposal_id: str) -> Outcome:
        proposal = self.get_owned(actor, proposal_id)
        correlation_id = proposal.correlation_id or new_correlation_id()
        self._claim(actor, proposal, to="EXECUTING")
        proposal = self.get_owned(actor, proposal_id)
        store.audit(
            self._db,
            actor,
            "ceo.action_confirmed",
            f"ceo_action:{proposal.id}",
            {
                "proposal_id": proposal.id,
                "action_type": proposal.action_type,
                "conversation_id": proposal.conversation_id,
            },
            correlation_id,
        )
        self._db.commit()
        try:
            result = self._execute(actor, proposal)
        except AmazonaError as exc:
            # Una negativa del dominio (la tarea ya no está FAILED, otro reintentó antes…): el servicio real ya la
            # validó y NO ejecutó nada.
            self._db.rollback()
            return self._finish(actor, proposal_id, correlation_id, error=redact_text(str(exc)))
        except Exception as exc:
            # Falló sin que sepamos si llegó a producir efecto: la propuesta se queda en EXECUTING (no se puede volver a
            # confirmar) y queda dicho.
            self._db.rollback()
            proposal = self.get_owned(actor, proposal_id)
            store.audit(
                self._db,
                actor,
                "ceo.action_failed",
                f"ceo_action:{proposal.id}",
                {
                    "proposal_id": proposal.id,
                    "action_type": proposal.action_type,
                    "outcome": "unknown",
                    "error_class": type(exc).__name__,
                },
                correlation_id,
            )
            self._db.commit()
            raise
        return self._finish(actor, proposal_id, correlation_id, result=redact(result))

    def _finish(
        self,
        actor: Actor,
        proposal_id: str,
        correlation_id: str,
        *,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> Outcome:
        proposal = self.get_owned(actor, proposal_id)
        proposal.status = "FAILED" if error else "EXECUTED"
        proposal.execution_result = result
        proposal.error = error
        text = (
            f"No se ha podido ejecutar la acción: {error}"
            if error
            else f"Acción ejecutada: {proposal.estimated_effects.get('summary', proposal.action_type)}"
        )
        message = store.add_message(
            self._db,
            proposal.conversation_id,
            "assistant",
            text,
            {
                "kind": "action_result",
                "proposal_id": proposal.id,
                "status": proposal.status,
                "result": result,
                "error": error,
            },
        )
        proposal.result_message_id = message.id
        store.audit(
            self._db,
            actor,
            "ceo.action_failed" if error else "ceo.action_executed",
            f"ceo_action:{proposal.id}",
            {
                "proposal_id": proposal.id,
                "action_type": proposal.action_type,
                "conversation_id": proposal.conversation_id,
                "message_id": message.id,
                "error": error,
            },
            correlation_id,
        )
        self._db.commit()
        return Outcome(proposal, message.id)

    def _task(self, task_id: str) -> Task:
        task = self._db.get(Task, task_id)
        if task is None:
            raise NotFoundError(f"task {task_id} not found")
        self._db.refresh(task)
        return task

    def _execute(self, actor: Actor, proposal: CeoActionProposal) -> dict[str, Any]:
        p = proposal.parameters
        db = self._db
        match proposal.action_type:
            case "retry_task":
                TaskRecoveryService(db, self._manager).retry(
                    p["task_id"], actor=actor.subject, after_attempt=p["after_attempt"], reason=p["reason"]
                )
                db.commit()
                task = self._task(p["task_id"])
                return {"task_id": task.id, "status": task.status, "attempt": p["after_attempt"] + 1}
            case "reassign_task":
                TaskRecoveryService(db, self._manager).reassign(
                    p["task_id"], agent_id=p["agent_id"], actor=actor.subject, reason=p["reason"]
                )
                db.commit()
                task = self._task(p["task_id"])
                return {"task_id": task.id, "status": task.status, "assigned_agent_id": task.assigned_agent_id}
            case "resume_mission":
                project_id = resolve_project_id(db, p["objective_id"], p.get("project_id"))
                resumed = CEOOrchestrator(db, agent_manager=self._manager).resume_mission(
                    project_id, actor=actor.subject, after_decision_id=p["after_decision_id"], reason=p["reason"]
                )
                view = load_mission(db, self._manager, project_id)
                return {
                    "decision_id": resumed.decision.id,
                    "decision_status": resumed.decision.status,
                    "previous_decision_id": resumed.previous_decision_id,
                    "executed_tasks": list(resumed.executed_tasks),
                    "mission_state": view.state.value,
                }
            case "create_mission":
                if db.get(Objective, p["objective_id"]) is not None:
                    raise ConflictError(
                        f"objective {p['objective_id']} already exists: this proposal was already executed"
                    )
                db.add(
                    Objective(
                        id=p["objective_id"],
                        title=p["title"],
                        description=p.get("description"),
                        created_by=actor.subject,
                        context=p.get("context") or {},
                        status="RECEIVED",
                    )
                )
                db.commit()
                decision = CEOOrchestrator(db, agent_manager=self._manager).run_objective(p["objective_id"])
                view = load_mission(db, self._manager, decision.project_id)
                return {
                    "objective_id": p["objective_id"],
                    "project_id": decision.project_id,
                    "decision_id": decision.id,
                    "decision_status": decision.status,
                    "mission_state": view.state.value,
                }
            case "approve_approval" | "reject_approval":
                approval = resolve_approval(p["approval_id"], p["decision"], db, actor, self._settings)
                return {"approval_id": approval.id, "status": approval.status}
        raise ValidationError(f"unknown action type {proposal.action_type!r}")
