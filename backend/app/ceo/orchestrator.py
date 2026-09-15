import datetime

from sqlalchemy.orm import Session

from app.agents.manager import AgentManager
from app.agents.registry import build_default_agent_manager
from app.approvals.service import ApprovalService
from app.audit.service import AuditService
from app.budgets.engine import BudgetEngine, BudgetState
from app.ceo.decision_engine import DecisionInput, evaluate_decision
from app.ceo.planner import plan_product_validation
from app.ceo.schemas import DecisionStatus
from app.ceo.schemas import Objective as ObjectiveSchema
from app.core.errors import NotFoundError
from app.core.ids import new_correlation_id
from app.db.models.approval import Approval as ApprovalModel
from app.db.models.decision import Decision as DecisionModel
from app.db.models.decision import DecisionEvidence as DecisionEvidenceModel
from app.db.models.objective import Objective as ObjectiveModel
from app.db.models.project import Project as ProjectModel
from app.db.models.task import Task as TaskModel
from app.events.bus import EventBus, InProcessEventBus
from app.events.schemas import Event
from app.permissions.engine import PermissionEngine
from app.permissions.policies import ActionType, PermissionResult
from app.tasks.schemas import TaskStatus
from app.tasks.service import TaskService

SPECIALIST_TASK_NAMES = ["product_validation", "supplier_sourcing", "finance_validation", "legal_validation"]

_PROJECT_STATUS_BY_DECISION = {
    DecisionStatus.GO: "APPROVED",
    DecisionStatus.NO_GO: "REJECTED",
    DecisionStatus.REVIEW: "VALIDATING",
    DecisionStatus.HUMAN_APPROVAL: "VALIDATING",
}


class CEOOrchestrator:
    """Coordinates one objective end to end: plan -> route tasks to
    specialist agents -> synthesize a deterministic decision -> permission
    and budget checks -> approval if required -> persist everything and
    audit every important transition.
    """

    def __init__(
        self,
        db: Session,
        *,
        agent_manager: AgentManager | None = None,
        event_bus: EventBus | None = None,
        audit_service: AuditService | None = None,
        approval_service: ApprovalService | None = None,
        permission_engine: PermissionEngine | None = None,
        budget_engine: BudgetEngine | None = None,
        budget_state: BudgetState | None = None,
    ) -> None:
        self._db = db
        if agent_manager is None:
            _, agent_manager = build_default_agent_manager()
        self._agent_manager = agent_manager
        self._event_bus = event_bus or InProcessEventBus()
        self.audit_service = audit_service or AuditService()
        self.approval_service = approval_service or ApprovalService()
        self._permissions = permission_engine or PermissionEngine()
        self._budget_engine = budget_engine or BudgetEngine()
        self._budget_state = budget_state or BudgetState(hard_limit=100_000.0)

    def run_objective(self, objective_id: str) -> DecisionModel:
        correlation_id = new_correlation_id()
        objective = self._db.get(ObjectiveModel, objective_id)
        if objective is None:
            raise NotFoundError(f"objective {objective_id} not found")

        context = objective.context or {}

        project = self._create_project(objective, correlation_id)
        task_service, name_to_domain_id, name_to_db_id = self._create_tasks(project, context, correlation_id)
        self._execute_tasks(task_service, project, name_to_domain_id, name_to_db_id, correlation_id)

        outputs = {name: task_service.get_task(name_to_domain_id[name]).output for name in SPECIALIST_TASK_NAMES}
        decision = self._synthesize_decision(project, context, outputs, correlation_id)
        self._maybe_create_approval(decision, context, correlation_id)

        project.status = _PROJECT_STATUS_BY_DECISION[DecisionStatus(decision.status)]
        self._db.commit()
        return decision

    def _create_project(self, objective: ObjectiveModel, correlation_id: str) -> ProjectModel:
        project = ProjectModel(objective_id=objective.id, name=objective.title, status="VALIDATING")
        self._db.add(project)
        self._db.flush()
        self.audit_service.record(
            actor="ceo",
            action="project.created",
            resource=f"project:{project.id}",
            before=None,
            after={"status": project.status},
            correlation_id=correlation_id,
        )
        self._event_bus.publish(
            Event(type="project.created", correlation_id=correlation_id, payload={"project_id": project.id})
        )
        return project

    def _create_tasks(
        self, project: ProjectModel, context: dict, correlation_id: str
    ) -> tuple[TaskService, dict[str, str], dict[str, str]]:
        objective_schema = ObjectiveSchema(id=project.objective_id, title=project.name)
        plan = plan_product_validation(objective_schema)

        task_service = TaskService()
        name_to_domain_id: dict[str, str] = {}
        name_to_db_id: dict[str, str] = {}

        for spec in plan.tasks:
            depends_on_domain_ids = [name_to_domain_id[dep] for dep in spec.depends_on]
            domain_task = task_service.create_task(
                project_id=project.id,
                name=spec.name,
                capability=spec.capability,
                input=context.get(spec.name, {}),
                depends_on=depends_on_domain_ids,
            )
            name_to_domain_id[spec.name] = domain_task.id

            db_task = TaskModel(
                project_id=project.id,
                name=spec.name,
                capability=spec.capability,
                status=TaskStatus.PENDING.value,
                input=domain_task.input,
            )
            self._db.add(db_task)
            self._db.flush()
            name_to_db_id[spec.name] = db_task.id

        self.audit_service.record(
            actor="ceo",
            action="tasks.created",
            resource=f"project:{project.id}",
            before=None,
            after={"task_count": len(plan.tasks)},
            correlation_id=correlation_id,
        )
        return task_service, name_to_domain_id, name_to_db_id

    def _execute_tasks(
        self,
        task_service: TaskService,
        project: ProjectModel,
        name_to_domain_id: dict[str, str],
        name_to_db_id: dict[str, str],
        correlation_id: str,
    ) -> None:
        while True:
            runnable = task_service.get_runnable_tasks(project.id)
            if not runnable:
                break

            for domain_task in runnable:
                db_task = self._db.get(TaskModel, name_to_db_id[domain_task.name])
                task_service.mark_running(domain_task.id)
                db_task.status = TaskStatus.RUNNING.value

                if domain_task.capability == "decision_synthesis":
                    task_service.mark_completed(domain_task.id, output={"synthesized": True})
                    db_task.status = TaskStatus.COMPLETED.value
                    db_task.output = {"synthesized": True}
                    continue

                agent = self._agent_manager.select_agent(domain_task.capability)
                result = self._agent_manager.execute(agent.id, domain_task)
                task_service.mark_completed(domain_task.id, output=result.model_dump())
                db_task.status = TaskStatus.COMPLETED.value
                db_task.output = result.model_dump()

                self.audit_service.record(
                    actor=agent.id,
                    action="task.completed",
                    resource=f"task:{db_task.id}",
                    before=None,
                    after={"recommendation": result.recommendation, "confidence": result.confidence},
                    correlation_id=correlation_id,
                )
                self._event_bus.publish(
                    Event(
                        type="task.completed",
                        correlation_id=correlation_id,
                        payload={"task_id": db_task.id, "capability": domain_task.capability},
                    )
                )

    def _synthesize_decision(
        self, project: ProjectModel, context: dict, outputs: dict[str, dict], correlation_id: str
    ) -> DecisionModel:
        product_output = outputs["product_validation"]
        finance_output = outputs["finance_validation"]
        legal_output = outputs["legal_validation"]

        opportunity_score = product_output["data"].get("opportunity_score", 0.0)
        confidence = min(o["confidence"] for o in outputs.values())
        legal_status = legal_output["data"].get("legal_status", "CLEAR")
        finance_veto = bool(finance_output["data"].get("finance_veto", False))

        requests_spend = bool(context.get("requests_simulated_spend", False))
        human_stop = bool(context.get("human_stop", False))
        requires_human_approval = False
        if requests_spend:
            permission_result = self._permissions.check(actor_role="ceo_agent", action=ActionType.EXTERNAL_SPEND)
            requires_human_approval = permission_result == PermissionResult.HUMAN_APPROVAL_REQUIRED

        decision_status = evaluate_decision(
            DecisionInput(
                opportunity_score=opportunity_score,
                confidence=confidence,
                legal_status=legal_status,
                finance_veto=finance_veto,
                security_veto=False,
                requires_human_approval=requires_human_approval,
                human_stop=human_stop,
            )
        )

        decision = DecisionModel(
            project_id=project.id,
            status=decision_status.value,
            opportunity_score=opportunity_score,
            confidence=confidence,
            rationale=f"legal_status={legal_status} finance_veto={finance_veto} human_stop={human_stop}",
            correlation_id=correlation_id,
        )
        self._db.add(decision)
        self._db.flush()

        for name, output in outputs.items():
            self._db.add(
                DecisionEvidenceModel(
                    decision_id=decision.id,
                    source=name,
                    summary="; ".join(output.get("evidence", [])) or output.get("recommendation", ""),
                    data=output.get("data", {}),
                )
            )

        self.audit_service.record(
            actor="ceo",
            action="decision.made",
            resource=f"decision:{decision.id}",
            before=None,
            after={"status": decision.status},
            correlation_id=correlation_id,
        )
        self._event_bus.publish(
            Event(
                type="decision.made",
                correlation_id=correlation_id,
                payload={"decision_id": decision.id, "status": decision.status},
            )
        )
        return decision

    def _maybe_create_approval(self, decision: DecisionModel, context: dict, correlation_id: str) -> None:
        if DecisionStatus(decision.status) != DecisionStatus.HUMAN_APPROVAL:
            return

        spend_amount = float(context.get("spend_amount", 0.0))
        budget_decision = self._budget_engine.authorize(amount=spend_amount, state=self._budget_state)

        if not budget_decision.approved:
            decision.status = DecisionStatus.NO_GO.value
            decision.rationale = f"{decision.rationale}; budget denied: {budget_decision.reason}"
            self.audit_service.record(
                actor="ceo",
                action="decision.budget_denied",
                resource=f"decision:{decision.id}",
                before={"status": DecisionStatus.HUMAN_APPROVAL.value},
                after={"status": decision.status},
                correlation_id=correlation_id,
            )
            return

        self._budget_engine.reserve(self._budget_state, spend_amount)

        approval = ApprovalModel(
            decision_id=decision.id,
            action=context.get("spend_action", "simulated_external_spend"),
            amount=spend_amount,
            status="PENDING",
            expires_at=datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=24),
            correlation_id=correlation_id,
        )
        self._db.add(approval)
        self._db.flush()

        self.audit_service.record(
            actor="ceo",
            action="approval.requested",
            resource=f"approval:{approval.id}",
            before=None,
            after={"action": approval.action, "amount": approval.amount},
            correlation_id=correlation_id,
        )
        self._event_bus.publish(
            Event(
                type="approval.requested",
                correlation_id=correlation_id,
                payload={"approval_id": approval.id, "decision_id": decision.id},
            )
        )
