"""Las lecturas del chat con el CEO (M52): lo que el modelo puede VER del sistema, y nada más.

Cada función corresponde a una herramienta de lectura y es SOLO LECTURA: no escribe, no hace `commit`, no llama a un
proveedor. Reutilizan las lecturas
reales del sistema (`load_mission`, `describe_recovery`, `BudgetLedgerService.summary`) en vez de volver a calcular
nada.

Lo que sale de aquí es una pequeña estructura JSON, acotada, y el servicio la redacta antes de dárselo al modelo o
guardarla (`redaction.redact`). Se
deja fuera, a propósito, lo que no responde a una pregunta del CEO y puede ser grande o sensible: la entrada y la
salida completas de una tarea, los
datos de las evidencias, el contexto del objetivo.
"""

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agents.manager import AgentManager
from app.budgets.service import BudgetLedgerService
from app.ceo.mission import MissionState, decision_versions, load_mission, ordered_decisions
from app.core.errors import NotFoundError
from app.db.models.approval import Approval
from app.db.models.audit import AuditLog
from app.db.models.decision import DecisionEvidence
from app.db.models.objective import Objective
from app.db.models.project import Project
from app.db.models.task import Task, TaskDependency
from app.tasks.assignment import load_relations
from app.tasks.recovery import describe_recovery

#: Cuántos proyectos recientes se revisan para el estado general.
RECENT_PROJECTS = 20
MAX_TEXT = 300


def _clip(value: str | None, limit: int = MAX_TEXT) -> str | None:
    if value is None:
        return None
    return value if len(value) <= limit else value[:limit] + "…"


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def _money(value: Any) -> str | None:
    return None if value is None else f"{value:.2f}"


def latest_project(db: Session) -> tuple[Objective, Project] | None:
    """La misión más reciente: el proyecto último (por fecha) con su objetivo."""
    project = db.scalars(select(Project).order_by(Project.created_at.desc(), Project.id.desc()).limit(1)).first()
    if project is None:
        return None
    objective = db.get(Objective, project.objective_id)
    return (objective, project) if objective is not None else None


def _mission_summary(db: Session, manager: AgentManager, objective: Objective, project: Project) -> dict[str, Any]:
    view = load_mission(db, manager, project.id)
    return {
        "objective_id": objective.id,
        "project_id": project.id,
        "title": _clip(objective.title, 120),
        "state": view.state.value,
        "resumed": view.resumed,
        "resumable": view.resumable,
        "decisions": view.decisions,
        "current_decision_id": view.current_decision_id,
        "pending_tasks": list(view.pending_tasks),
        "completed_tasks": list(view.completed_tasks),
        "blockers": [blocker.as_audit() | {"task_id": blocker.task_id} for blocker in view.blockers],
    }


def read_system_status(db: Session, manager: AgentManager) -> dict[str, Any]:
    projects = db.scalars(
        select(Project).order_by(Project.created_at.desc(), Project.id.desc()).limit(RECENT_PROJECTS)
    ).all()
    missions = []
    for project in projects:
        objective = db.get(Objective, project.objective_id)
        if objective is not None:
            missions.append(_mission_summary(db, manager, objective, project))
    closed = {MissionState.COMPLETE.value, MissionState.CANCELLED.value}
    counts = db.execute(select(Task.status, func.count()).group_by(Task.status))
    by_status: dict[str, int] = {status: count for status, count in counts}
    pending_approvals = db.scalar(select(func.count()).select_from(Approval).where(Approval.status == "PENDING")) or 0
    return {
        "backend": "operativo",
        "missions": {
            "recent_reviewed": len(missions),
            "complete": sum(1 for m in missions if m["state"] == MissionState.COMPLETE.value),
            "incomplete": [m for m in missions if m["state"] not in closed],
        },
        "tasks_by_status": by_status,
        "agents": [
            {"id": agent_id, "capabilities": sorted(capabilities)}
            for agent_id, capabilities in sorted(manager.capabilities_by_agent().items())
        ],
        "pending_approvals": pending_approvals,
    }


def _decisions(db: Session, project_id: str) -> list[dict[str, Any]]:
    decisions = ordered_decisions(db, project_id)
    versions = decision_versions(decisions)
    out = []
    for decision in decisions:
        version = versions[decision.id]
        evidence = db.scalars(
            select(DecisionEvidence).where(DecisionEvidence.decision_id == decision.id).limit(10)
        ).all()
        out.append(
            {
                "decision_id": decision.id,
                "version": version.version,
                "is_current": version.is_current,
                "supersedes_decision_id": version.supersedes_decision_id,
                "status": decision.status,
                "opportunity_score": decision.opportunity_score,
                "confidence": decision.confidence,
                "rationale": _clip(decision.rationale),
                "created_at": _iso(decision.created_at),
                "evidence": [{"source": item.source, "summary": _clip(item.summary, 200)} for item in evidence],
            }
        )
    return out


def read_latest_mission(db: Session, manager: AgentManager) -> dict[str, Any]:
    found = latest_project(db)
    if found is None:
        return {"available": False, "reason": "todavía no se ha ejecutado ninguna misión"}
    objective, project = found
    tasks = db.scalars(select(Task).where(Task.project_id == project.id).order_by(Task.created_at, Task.id)).all()
    return {
        "mission": _mission_summary(db, manager, objective, project),
        "tasks": [
            {
                "task_id": task.id,
                "name": task.name,
                "capability": task.capability,
                "status": task.status,
                "assigned_agent_id": task.assigned_agent_id,
            }
            for task in tasks
        ],
        "decisions": _decisions(db, project.id),
    }


def read_budget(db: Session) -> dict[str, Any]:
    summary = BudgetLedgerService(db).summary()
    if summary is None:
        return {"available": False, "reason": "no hay un presupuesto autorizado"}
    return {
        "available": True,
        "name": summary.name,
        "period": summary.period,
        "currency": summary.currency,
        "hard_limit": _money(summary.hard_limit),
        "soft_limit": _money(summary.soft_limit),
        "reserved": _money(summary.reserved),
        "committed": _money(summary.committed),
        "spent": _money(summary.spent),
        "remaining": _money(summary.remaining),
    }


def read_pending_approvals(db: Session, *, include_resolved: bool, limit: int) -> dict[str, Any]:
    query = select(Approval).order_by(Approval.requested_at.desc(), Approval.id)
    if not include_resolved:
        query = query.where(Approval.status == "PENDING")
    approvals = db.scalars(query.limit(limit)).all()
    return {
        "approvals": [
            {
                "approval_id": approval.id,
                "decision_id": approval.decision_id,
                "action": _clip(approval.action, 120),
                "amount": _money(approval.amount),
                "status": approval.status,
                "requested_at": _iso(approval.requested_at),
                "expires_at": _iso(approval.expires_at),
                "resolved_at": _iso(approval.resolved_at),
            }
            for approval in approvals
        ]
    }


def read_task_details(db: Session, manager: AgentManager, task_id: str) -> dict[str, Any]:
    task = db.get(Task, task_id)
    if task is None:
        raise NotFoundError(f"task {task_id} not found")
    known = manager.agent_ids()
    relation = load_relations(db, [task], known)[task.id]
    recovery = describe_recovery(
        task_status=task.status,
        assigned_agent_id=task.assigned_agent_id,
        known_agent_ids=known,
        traces=relation.executions,
        relation_status=relation.status,
    )
    depends_on = db.scalars(select(TaskDependency.parent_task_id).where(TaskDependency.child_task_id == task.id)).all()
    return {
        "task_id": task.id,
        "project_id": task.project_id,
        "name": task.name,
        "capability": task.capability,
        "status": task.status,
        "error": _clip(task.error),
        "depends_on": list(depends_on),
        "assigned_agent_id": task.assigned_agent_id,
        "assignment": relation.status.value,
        "executed_by_agent_id": relation.executed_by_agent_id,
        "reassigned": relation.reassigned,
        "attempts": [
            {"attempt": item.attempt, "agent_id": item.agent_id, "success": item.success, "source": item.source}
            for item in relation.executions
        ],
        "recovery": {
            "kind": recovery.kind.value,
            "can_retry": recovery.can_retry,
            "next_attempt": recovery.next_attempt,
            "attempts_current_assignment": recovery.attempts_current_assignment,
            "max_attempts_per_assignment": recovery.max_attempts_per_assignment,
            "attempts_total": recovery.attempts_total,
            "max_attempts_per_task": recovery.max_attempts_per_task,
        },
    }


def read_decision_history(db: Session, project_id: str | None) -> dict[str, Any]:
    if project_id is None:
        found = latest_project(db)
        if found is None:
            return {"available": False, "reason": "todavía no se ha ejecutado ninguna misión"}
        project_id = found[1].id
    elif db.get(Project, project_id) is None:
        raise NotFoundError(f"project {project_id} not found")
    return {"project_id": project_id, "decisions": _decisions(db, project_id)}


def read_audit_summary(db: Session, *, limit: int, correlation_id: str | None) -> dict[str, Any]:
    """Acción, actor, recurso y hora. NO el antes/después de cada evento: es donde más fácil se cuela algo que no debe
    verse."""
    query = select(AuditLog).order_by(AuditLog.created_at.desc(), AuditLog.id)
    if correlation_id is not None:
        query = query.where(AuditLog.correlation_id == correlation_id)
    events = db.scalars(query.limit(limit)).all()
    return {
        "events": [
            {
                "action": event.action,
                "actor": _clip(event.actor, 80),
                "resource": _clip(event.resource, 120),
                "at": _iso(event.created_at),
                "correlation_id": event.correlation_id,
            }
            for event in events
        ]
    }


__all__ = [
    "latest_project",
    "read_audit_summary",
    "read_budget",
    "read_decision_history",
    "read_latest_mission",
    "read_pending_approvals",
    "read_system_status",
    "read_task_details",
]
