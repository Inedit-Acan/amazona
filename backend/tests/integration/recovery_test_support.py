"""Apoyo compartido de las pruebas de recuperación de tareas (M49, Commit 8). Módulo auxiliar, NO un test.

Construye misiones reales con el orquestador y agentes de prueba guionizados (fallan o aciertan en el orden que se
les pide), de modo que cada prueba parte de un estado que el sistema produce de verdad (una tarea FAILED con sus
intentos en el log), no de filas escritas a mano."""

from collections.abc import Iterable

from sqlalchemy.orm import Session

from app.agents.base import Agent, AgentDescriptor, AgentResult
from app.agents.finance import FinanceAgent
from app.agents.legal import LegalAgent
from app.agents.manager import AgentManager
from app.agents.registry import AgentRegistry
from app.agents.supplier import SupplierAgent
from app.ceo.orchestrator import CEOOrchestrator
from app.core.ids import new_id
from app.db.models.agent_execution_log import AgentExecutionLog
from app.db.models.audit import AuditLog
from app.db.models.objective import Objective
from app.db.models.task import Task

CONTEXT = {
    "product_validation": {"estimated_monthly_searches": 12000, "competition_level": "low"},
    "supplier_sourcing": {"unit_cost": 5.0, "lead_time_days": 20, "supplier_verified": True},
    "finance_validation": {
        "unit_cost": 5.0,
        "sale_price": 20.0,
        "monthly_unit_sales": 300,
        "monthly_fixed_costs": 500.0,
    },
    "legal_validation": {"restricted_category": False},
}


class Scripted(Agent):
    """Un agente de `market_validation` que sigue un guion: cada llamada consume un `True` (acierta) o un `False`
    (falla). Pasado el guion, acierta."""

    capability = "market_validation"

    def __init__(self, script: Iterable[bool]) -> None:
        self.script = list(script)
        self.calls = 0

    def run(self, task_input: dict) -> AgentResult:
        self.calls += 1
        ok = self.script[self.calls - 1] if self.calls <= len(self.script) else True
        if not ok:
            raise RuntimeError(f"simulated failure #{self.calls}")
        return AgentResult(
            status="COMPLETED",
            recommendation="GO",
            confidence=0.9,
            evidence=["ok"],
            risks=[],
            assumptions=[],
            data={"opportunity_score": 0.8},
        )


class AlwaysFails(Agent):
    """Un agente que nunca acierta, para la capacidad que se le diga."""

    def __init__(self, capability: str) -> None:
        self.capability = capability
        self.calls = 0

    def run(self, task_input: dict) -> AgentResult:
        self.calls += 1
        raise RuntimeError(f"simulated failure #{self.calls}")


def build_manager(
    product_agents: dict[str, Agent], overrides: dict[str, Agent] | None = None
) -> tuple[AgentRegistry, AgentManager]:
    """Un registro con los agentes de producto que se pidan (el primero es el que elige el registro) y los tres
    especialistas normales; `overrides` sustituye a alguno de los tres por otro ejecutor (mismo id)."""
    registry = AgentRegistry()
    manager = AgentManager(registry)
    specialists = {
        **product_agents,
        "agent-supplier-1": SupplierAgent(),
        "agent-finance-1": FinanceAgent(),
        "agent-legal-1": LegalAgent(),
        **(overrides or {}),
    }
    for index, (agent_id, executor) in enumerate(specialists.items()):
        registry.register(
            AgentDescriptor(
                id=agent_id,
                name=agent_id,
                role="x",
                version="1",
                capabilities=[executor.capability],
                reliability_score=1.0 - index * 0.01 if agent_id.startswith("agent-product") else 1.0,
            )
        )
        manager.register_executor(agent_id, executor)
    return registry, manager


def make_objective(db: Session, context: dict | None = None) -> Objective:
    row = Objective(id=new_id(), title="Recovery", created_by="owner@amazona.local", context=context or CONTEXT)
    db.add(row)
    db.commit()
    return row


def run_mission(db: Session, manager: AgentManager, *, max_task_retries: int = 1):
    """Ejecuta una misión completa. Con `max_task_retries=1`, una tarea que siempre falla deja 2 intentos: FAILED."""
    decision = CEOOrchestrator(db, agent_manager=manager, max_task_retries=max_task_retries).run_objective(
        make_objective(db).id
    )
    return decision


def tasks_by_name(db: Session) -> dict[str, Task]:
    return {task.name: task for task in db.query(Task).all()}


def executions_of(db: Session, task: Task) -> list[AgentExecutionLog]:
    return db.query(AgentExecutionLog).filter_by(task_id=task.id).order_by(AgentExecutionLog.attempt).all()


def audit_actions(db: Session, task: Task | None = None, *, action: str | None = None) -> list[AuditLog]:
    query = db.query(AuditLog)
    if task is not None:
        query = query.filter_by(resource=f"task:{task.id}")
    if action is not None:
        query = query.filter_by(action=action)
    return query.order_by(AuditLog.created_at, AuditLog.id).all()
