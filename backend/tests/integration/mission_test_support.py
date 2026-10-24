"""Apoyo de las pruebas de reanudación de misiones (M50, Commit 9). Módulo auxiliar, NO un test.

Construye misiones INCOMPLETAS reales con el orquestador (un agente de producto guionizado que falla en el primer
intento deja la tarea FAILED, a sus dependientes BLOQUEADOS y una decisión REVIEW `incomplete_mission`), y las recupera
con el servicio de Commit 8 (`TaskRecoveryService.retry`). Así cada prueba parte de un estado que el sistema produce."""

from collections.abc import Iterable
from dataclasses import dataclass, field

from recovery_test_support import CONTEXT, Scripted, build_manager, make_objective
from sqlalchemy.orm import Session

from app.agents.base import Agent, AgentResult
from app.agents.finance import FinanceAgent
from app.agents.manager import AgentManager
from app.ceo.orchestrator import CEOOrchestrator
from app.db.models.agent_execution_log import AgentExecutionLog
from app.db.models.approval import Approval
from app.db.models.audit import AuditLog
from app.db.models.budget import FinancialEvent
from app.db.models.decision import Decision, DecisionEvidence
from app.db.models.objective import Objective
from app.db.models.project import Project
from app.db.models.task import Task, TaskDependency
from app.tasks.recovery import TaskRecoveryService

P1 = "agent-product-1"


class FlakyFinance(FinanceAgent):
    """El agente de finanzas de siempre, pero sus primeras `failures` llamadas fallan."""

    def __init__(self, failures: int) -> None:
        super().__init__()
        self.failures = failures
        self.calls = 0

    def run(self, task_input: dict) -> AgentResult:
        self.calls += 1
        if self.calls <= self.failures:
            raise RuntimeError(f"simulated finance failure #{self.calls}")
        return super().run(task_input)


SPECIALISTS = ("product_validation", "supplier_sourcing", "legal_validation", "finance_validation")

TABLES = {
    "objectives": Objective,
    "projects": Project,
    "tasks": Task,
    "task_dependencies": TaskDependency,
    "executions": AgentExecutionLog,
    "decisions": Decision,
    "evidence": DecisionEvidence,
    "approvals": Approval,
    "financial_events": FinancialEvent,
}


def counts(db: Session) -> dict[str, int]:
    return {name: db.query(model).count() for name, model in TABLES.items()}


@dataclass
class Mission:
    db: Session
    manager: AgentManager
    product: Scripted
    objective: Objective
    first_decision: Decision
    project: Project
    extra: dict[str, Agent] = field(default_factory=dict)

    def task(self, name: str) -> Task:
        self.db.expire_all()
        return self.db.query(Task).filter_by(project_id=self.project.id, name=name).one()

    def statuses(self) -> dict[str, str]:
        self.db.expire_all()
        return {t.name: t.status for t in self.db.query(Task).filter_by(project_id=self.project.id).all()}

    def decisions(self) -> list[Decision]:
        self.db.expire_all()
        return (
            self.db.query(Decision)
            .filter_by(project_id=self.project.id)
            .order_by(Decision.created_at, Decision.id)
            .all()
        )

    def latest(self) -> Decision:
        return self.decisions()[-1]

    def retry(self, name: str = "product_validation", *, after_attempt: int = 1) -> Task:
        task = self.task(name)
        TaskRecoveryService(self.db, self.manager).retry(task.id, actor="ceo", after_attempt=after_attempt)
        self.db.commit()
        return self.task(name)

    def resume(
        self, *, actor: str = "ceo", after_decision_id: str | None = None, max_task_retries: int = 0
    ) -> Decision:
        """Sin reintentos en línea por defecto: un agente que falla deja la tarea FAILED a la primera, y recuperarla es
        cosa del reintento explícito (Commit 8), no de la reanudación."""
        return CEOOrchestrator(self.db, agent_manager=self.manager, max_task_retries=max_task_retries).resume_project(
            self.project.id, actor=actor, after_decision_id=after_decision_id or self.latest().id
        )

    def audit(self, action: str) -> list[AuditLog]:
        self.db.expire_all()
        return self.db.query(AuditLog).filter_by(action=action).order_by(AuditLog.created_at, AuditLog.id).all()

    def executions(self, name: str) -> list[AgentExecutionLog]:
        task = self.task(name)
        return (
            self.db.query(AgentExecutionLog)
            .filter_by(task_id=task.id)
            .order_by(AgentExecutionLog.attempt, AgentExecutionLog.created_at)
            .all()
        )


def incomplete_mission(
    db: Session,
    *,
    script: Iterable[bool] = (False,),
    context: dict | None = None,
    overrides: dict[str, Agent] | None = None,
    extra_agents: dict[str, Agent] | None = None,
    max_task_retries: int = 0,
) -> Mission:
    """Una misión cuyo agente de producto sigue `script` (por defecto: falla una vez y luego acierta). Con
    `max_task_retries=0` el primer fallo deja `product_validation` FAILED y bloquea a todo lo que depende de ella."""
    product = Scripted(script)
    _, manager = build_manager({P1: product, **(extra_agents or {})}, overrides)
    objective = make_objective(db, context if context is not None else CONTEXT)
    decision = CEOOrchestrator(db, agent_manager=manager, max_task_retries=max_task_retries).run_objective(objective.id)
    project = db.query(Project).filter_by(objective_id=objective.id).one()
    return Mission(db, manager, product, objective, decision, project)


def recovered_mission(db: Session, **kwargs) -> Mission:
    """Incompleta y con la tarea fallida YA reintentada con éxito: lista para reanudar (el escenario principal)."""
    mission = incomplete_mission(db, **kwargs)
    mission.retry()
    return mission
