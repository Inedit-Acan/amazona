import datetime

from sqlalchemy.orm import Session

from app.agents.manager import AgentManager
from app.agents.registry import build_default_agent_manager
from app.approvals.service import ApprovalService
from app.audit.service import AuditService
from app.budgets.service import BudgetLedgerService
from app.ceo.decision_engine import DecisionInput, evaluate_decision
from app.ceo.planner import plan_product_validation
from app.ceo.schemas import DecisionStatus
from app.ceo.schemas import Objective as ObjectiveSchema
from app.core.config import Settings, get_settings
from app.core.errors import NoAgentAvailableError, NotFoundError
from app.core.ids import new_correlation_id, new_id
from app.db.models.approval import Approval as ApprovalModel
from app.db.models.audit import AuditLog as AuditLogModel
from app.db.models.decision import Decision as DecisionModel
from app.db.models.decision import DecisionEvidence as DecisionEvidenceModel
from app.db.models.objective import Objective as ObjectiveModel
from app.db.models.project import Project as ProjectModel
from app.db.models.task import Task as TaskModel
from app.db.models.task import TaskDependency as TaskDependencyModel
from app.events.bus import EventBus, InProcessEventBus
from app.events.schemas import Event
from app.memory.service import MemoryService
from app.permissions.engine import PermissionEngine
from app.permissions.policies import ActionType, PermissionResult
from app.tasks.assignment import ORCHESTRATOR_CAPABILITIES, TaskAssignmentService
from app.tasks.lifecycle import ensure_transition
from app.tasks.policy import DEFAULT_MAX_TASK_RETRIES
from app.tasks.recovery import TaskRecoveryService
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
        budget_ledger: BudgetLedgerService | None = None,
        settings: Settings | None = None,
        max_task_retries: int = DEFAULT_MAX_TASK_RETRIES,
    ) -> None:
        self._db = db
        self._max_task_retries = max_task_retries
        if agent_manager is None:
            _, agent_manager = build_default_agent_manager()
        self._agent_manager = agent_manager
        self._event_bus = event_bus or InProcessEventBus()
        self.audit_service = audit_service or AuditService()
        self.approval_service = approval_service or ApprovalService()
        self._permissions = permission_engine or PermissionEngine()
        # El presupuesto es el de la base de datos, el mismo que consulta el ActionGate: el
        # orquestador ya no lleva un saldo propio en memoria (nuevo en cada petición, con un
        # límite escrito en el código), que aprobaba cada petición contra el techo entero.
        self._budget_ledger = budget_ledger or BudgetLedgerService(db)
        self._settings = settings or get_settings()
        self._memory = MemoryService(db)
        # La asignación y la ejecución de cada tarea las registra el servicio de asignación: UNA sola implementación
        # (M48, Commit 7).
        self._assignments = TaskAssignmentService(db, agent_manager.agent_ids(), agent_manager.capabilities_by_agent())
        # La recuperación (bloqueo por dependencias, hechos de cada intento) es del mismo servicio que usa el reintento
        # explícito: una sola implementación (M49, Commit 8).
        self._recovery = TaskRecoveryService(db, agent_manager)

    def run_objective(self, objective_id: str) -> DecisionModel:
        correlation_id = new_correlation_id()
        objective = self._db.get(ObjectiveModel, objective_id)
        if objective is None:
            raise NotFoundError(f"objective {objective_id} not found")

        context = objective.context or {}

        project = self._create_project(objective, correlation_id)
        task_service, name_to_domain_id, name_to_db_id = self._create_tasks(project, context, correlation_id)
        self._execute_tasks(task_service, project, name_to_domain_id, name_to_db_id, correlation_id)

        outputs = {
            name: task_service.get_task(name_to_domain_id[name]).output or {} for name in SPECIALIST_TASK_NAMES
        }
        missing = {
            name: task_service.get_task(name_to_domain_id[name]).status.value
            for name in SPECIALIST_TASK_NAMES
            if task_service.get_task(name_to_domain_id[name]).status != TaskStatus.COMPLETED
        }
        decision = self._synthesize_decision(project, context, outputs, correlation_id, missing)
        self._maybe_create_approval(decision, context, correlation_id)

        project.status = _PROJECT_STATUS_BY_DECISION[DecisionStatus(decision.status)]
        self._db.commit()
        return decision

    def _create_project(self, objective: ObjectiveModel, correlation_id: str) -> ProjectModel:
        project = ProjectModel(objective_id=objective.id, name=objective.title, status="VALIDATING")
        self._db.add(project)
        self._db.flush()
        self._audit(
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
            self._assign_at_creation(db_task, domain_task, correlation_id)

        for spec in plan.tasks:
            for dep_name in spec.depends_on:
                self._db.add(
                    TaskDependencyModel(
                        parent_task_id=name_to_db_id[dep_name],
                        child_task_id=name_to_db_id[spec.name],
                    )
                )

        self._audit(
            actor="ceo",
            action="tasks.created",
            resource=f"project:{project.id}",
            before=None,
            after={"task_count": len(plan.tasks)},
            correlation_id=correlation_id,
        )
        return task_service, name_to_domain_id, name_to_db_id

    def _assign_at_creation(self, db_task: TaskModel, domain_task, correlation_id: str) -> None:
        """Asigna la tarea al agente que el REGISTRO elige para su capacidad. Las del orquestador no se asignan a ningún
        agente. Si ahora no hay ningún agente disponible, la tarea queda SIN asignar: no se rellena por la capacidad
        ni por el nombre (la ejecución fallará como siempre)."""
        if db_task.capability in ORCHESTRATOR_CAPABILITIES:
            return
        try:
            agent = self._agent_manager.select_agent(db_task.capability)
        except NoAgentAvailableError:
            return
        self._assignments.assign(
            db_task,
            agent.id,
            actor="ceo",
            reason="selected by capability when the task was created",
            correlation_id=correlation_id,
        )
        domain_task.assigned_agent_id = agent.id

    def _agent_for_attempt(self, db_task: TaskModel, domain_task, correlation_id: str) -> str:
        """El agente que ejecuta ESTE intento: el asignado, si sigue pudiendo. Si no (ya no está disponible), o si la
        tarea no tenía asignación, se elige otro por la capacidad y se deja EXPLÍCITO y auditado (`task.assigned` /
        `task.reassigned`): la ejecución nunca ocurre sin una asignación detrás ni con otro agente sin que conste."""
        capability = domain_task.capability
        assigned = db_task.assigned_agent_id
        if assigned is not None and self._agent_manager.is_routable(assigned, capability):
            return assigned
        selected = self._agent_manager.select_agent(capability)
        if assigned is None:
            self._assignments.assign(
                db_task,
                selected.id,
                actor="ceo",
                reason="no assignment when the task was executed; selected by capability",
                correlation_id=correlation_id,
            )
        else:
            self._assignments.reassign(
                db_task,
                selected.id,
                actor="ceo",
                reason=f"assigned agent {assigned} is not routable for {capability}; selected by capability",
                correlation_id=correlation_id,
            )
        domain_task.assigned_agent_id = selected.id
        return selected.id

    def _execute_tasks(
        self,
        task_service: TaskService,
        project: ProjectModel,
        name_to_domain_id: dict[str, str],
        name_to_db_id: dict[str, str],
        correlation_id: str,
    ) -> None:
        domain_by_db_id = {name_to_db_id[name]: name_to_domain_id[name] for name in name_to_db_id}
        while True:
            runnable = task_service.get_runnable_tasks(project.id)
            if not runnable:
                break

            for domain_task in runnable:
                db_task = self._db.get(TaskModel, name_to_db_id[domain_task.name])
                assert db_task is not None, f"task row for {domain_task.name!r} was not created"

                if domain_task.capability == "decision_synthesis":
                    task_service.mark_running(domain_task.id)
                    db_task.status = ensure_transition(db_task.status, TaskStatus.RUNNING).value
                    task_service.mark_completed(domain_task.id, output={"synthesized": True})
                    db_task.status = ensure_transition(db_task.status, TaskStatus.COMPLETED).value
                    db_task.output = {"synthesized": True}
                    continue

                # Un agente asignado que el registro ya no conoce NO se sustituye por otro de la
                # misma capacidad: la tarea se bloquea hasta que alguien con autoridad la reasigne
                # (un agente conocido pero no disponible sí lo resuelve el propio orquestador, de
                # forma explícita y auditada: `_agent_for_attempt`).
                assigned = db_task.assigned_agent_id
                if assigned is not None and assigned not in self._agent_manager.agent_ids():
                    self._recovery.block_task(
                        db_task, reason="unknown_agent", correlation_id=correlation_id, agent_id=assigned
                    )
                    task_service.mark_blocked(domain_task.id)
                    self._block_dependents(task_service, db_task, domain_by_db_id, correlation_id)
                    continue

                agent_id = self._agent_for_attempt(db_task, domain_task, correlation_id)
                attempt = domain_task.retry_count + 1
                task_service.mark_running(domain_task.id)
                self._recovery.start_attempt(db_task, agent_id, attempt, correlation_id=correlation_id)
                logged_before = len(self._agent_manager.execution_log)
                try:
                    result = self._agent_manager.execute(agent_id, domain_task)
                except Exception as exc:  # noqa: BLE001 - any agent failure is retried/audited, never silent
                    self._record_execution(db_task, domain_task, logged_before, correlation_id)
                    retried_task = task_service.mark_failed(
                        domain_task.id, error=str(exc), max_retries=self._max_task_retries
                    )
                    db_task.status = ensure_transition(db_task.status, TaskStatus.FAILED).value
                    db_task.error = retried_task.error
                    db_task.completed_at = datetime.datetime.now(datetime.UTC)
                    self._recovery.record_failure(db_task, agent_id, attempt, str(exc), correlation_id)
                    will_retry = retried_task.status == TaskStatus.PENDING
                    if will_retry:
                        db_task.status = ensure_transition(db_task.status, TaskStatus.PENDING).value
                    self._audit(
                        actor=agent_id,
                        action="task.retried" if will_retry else "task.failed",
                        resource=f"task:{db_task.id}",
                        before=None,
                        after={"error": str(exc), "retry_count": retried_task.retry_count},
                        correlation_id=correlation_id,
                    )
                    if not will_retry:
                        self._block_dependents(task_service, db_task, domain_by_db_id, correlation_id)
                    continue

                self._record_execution(db_task, domain_task, logged_before, correlation_id)
                task_service.mark_completed(domain_task.id, output=result.model_dump())
                db_task.status = ensure_transition(db_task.status, TaskStatus.COMPLETED).value
                db_task.output = result.model_dump()
                db_task.error = None  # un error de un intento anterior no se queda en una tarea que acabó bien
                db_task.completed_at = datetime.datetime.now(datetime.UTC)

                self._audit(
                    actor=agent_id,
                    action="task.completed",
                    resource=f"task:{db_task.id}",
                    before=None,
                    after={"recommendation": result.recommendation, "confidence": result.confidence},
                    correlation_id=correlation_id,
                )
                self._memory.remember(
                    scope="objective",
                    scope_id=project.objective_id,
                    key=domain_task.capability,
                    value=result.model_dump(),
                    correlation_id=correlation_id,
                )
                self._event_bus.publish(
                    Event(
                        type="task.completed",
                        correlation_id=correlation_id,
                        payload={"task_id": db_task.id, "capability": domain_task.capability},
                    )
                )

    def _block_dependents(
        self,
        task_service: TaskService,
        db_task: TaskModel,
        domain_by_db_id: dict[str, str],
        correlation_id: str,
    ) -> None:
        """Lo que depende de una tarea que no va a completarse queda BLOQUEADO (en la base y en el grafo en memoria): ni
        arranca ni se completa por arrastre."""
        for child in self._recovery.block_dependents(db_task, correlation_id):
            domain_id = domain_by_db_id.get(child.id)
            if domain_id is not None:
                task_service.mark_blocked(domain_id)

    def _synthesize_decision(
        self,
        project: ProjectModel,
        context: dict,
        outputs: dict[str, dict],
        correlation_id: str,
        missing: dict[str, str] | None = None,
    ) -> DecisionModel:
        # `.get(...)` throughout: a task that permanently failed after
        # exhausting its retries never produced output, so its entry in
        # `outputs` is `{}` rather than a real AgentResult dump. That reads
        # as "no data" (confidence 0.0, no veto data) and naturally routes
        # to REVIEW via the confidence threshold below, instead of crashing.
        product_output = outputs["product_validation"]
        finance_output = outputs["finance_validation"]
        legal_output = outputs["legal_validation"]

        opportunity_score = product_output.get("data", {}).get("opportunity_score", 0.0)
        confidence = min(o.get("confidence", 0.0) for o in outputs.values())
        legal_status = legal_output.get("data", {}).get("legal_status", "CLEAR")
        finance_veto = bool(finance_output.get("data", {}).get("finance_veto", False))

        if missing:
            return self._incomplete_decision(project, outputs, correlation_id, missing)

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
                    data={
                        **output.get("data", {}),
                        "recommendation": output.get("recommendation"),
                        "risks": output.get("risks", []),
                    },
                )
            )

        self._audit(
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

    def _incomplete_decision(
        self, project: ProjectModel, outputs: dict[str, dict], correlation_id: str, missing: dict[str, str]
    ) -> DecisionModel:
        """Una tarea necesaria no se completó (FALLÓ o está BLOQUEADA): no hay base para decidir GO ni NO_GO, y NO se
        inventa una evaluación con datos que faltan (nada de «sin veto legal» porque el análisis legal no existe). La
        decisión es REVIEW y dice, en su motivo, qué tareas faltan y en qué estado están. Sin pruebas para lo que no
        se hizo."""
        detail = ", ".join(f"{name}({status})" for name, status in sorted(missing.items()))
        decision = DecisionModel(
            project_id=project.id,
            status=DecisionStatus.REVIEW.value,
            opportunity_score=0.0,
            confidence=0.0,
            rationale=f"incomplete_mission: required tasks not completed: {detail}",
            correlation_id=correlation_id,
        )
        self._db.add(decision)
        self._db.flush()
        for name, output in outputs.items():
            if name in missing:
                continue
            self._db.add(
                DecisionEvidenceModel(
                    decision_id=decision.id,
                    source=name,
                    summary="; ".join(output.get("evidence", [])) or output.get("recommendation", ""),
                    data={
                        **output.get("data", {}),
                        "recommendation": output.get("recommendation"),
                        "risks": output.get("risks", []),
                    },
                )
            )
        self._audit(
            actor="ceo",
            action="decision.made",
            resource=f"decision:{decision.id}",
            before=None,
            after={"status": decision.status, "incomplete": sorted(missing)},
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

        # Sin importe no se sabe cuánto se pide, y eso no es cero: se deniega.
        raw_amount = context.get("spend_amount")
        spend_amount = float(raw_amount) if raw_amount is not None else None
        simulated = self._settings.operating_in_simulation
        assessment = self._budget_ledger.assess(spend_amount, simulated=simulated)

        approval_id = new_id()
        denial = None if assessment.approved else assessment.reason
        if denial is None and spend_amount and self._budget_ledger.find_budget() is not None:
            # La misma comprobación del límite que el ActionGate, pero **en la sentencia que
            # reserva**: con dos peticiones a la vez, solo caben las que caben juntas.
            reserved = self._budget_ledger.reserve(amount=spend_amount, reference=f"approval:{approval_id}")
            if not reserved:
                denial = "the budget was used up by a concurrent request"

        if denial is not None:
            decision.status = DecisionStatus.NO_GO.value
            decision.rationale = f"{decision.rationale}; budget denied: {denial}"
            self._audit(
                actor="ceo",
                action="decision.budget_denied",
                resource=f"decision:{decision.id}",
                before={"status": DecisionStatus.HUMAN_APPROVAL.value},
                after={"status": decision.status, "budget": assessment.status.value},
                correlation_id=correlation_id,
            )
            return

        approval = ApprovalModel(
            id=approval_id,
            decision_id=decision.id,
            action=context.get("spend_action", "simulated_external_spend"),
            amount=spend_amount,
            status="PENDING",
            expires_at=datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=24),
            correlation_id=correlation_id,
        )
        self._db.add(approval)
        self._db.flush()

        self._audit(
            actor="ceo",
            action="approval.requested",
            resource=f"approval:{approval.id}",
            before=None,
            after={"action": approval.action, "amount": approval.amount, "budget": assessment.status.value},
            correlation_id=correlation_id,
        )
        self._event_bus.publish(
            Event(
                type="approval.requested",
                correlation_id=correlation_id,
                payload={"approval_id": approval.id, "decision_id": decision.id},
            )
        )

    def _audit(
        self,
        *,
        actor: str,
        action: str,
        resource: str,
        before: dict | None,
        after: dict | None,
        correlation_id: str,
    ) -> None:
        """Record an audit transition both in the in-process AuditService
        (used by callers within the same run) and in the durable
        `audit_log` table (used by the API, across requests/processes)."""
        self.audit_service.record(
            actor=actor, action=action, resource=resource, before=before, after=after, correlation_id=correlation_id
        )
        self._db.add(
            AuditLogModel(
                actor=actor, action=action, resource=resource, before=before, after=after, correlation_id=correlation_id
            )
        )

    def _record_execution(
        self, db_task: TaskModel, domain_task, logged_before: int, correlation_id: str
    ) -> None:
        """Persiste la medición de la ejecución que acaba de hacer `AgentManager.execute()`, vinculada a SU tarea (con
        la foto de la asignación, el intento y las horas). Si la llamada no llegó a ejecutar nada (no hay ejecutor), no
        hay nada que registrar: no se reutiliza la entrada de otra ejecución."""
        log = self._agent_manager.execution_log
        if len(log) <= logged_before:
            return
        entry = log[-1]
        self._assignments.record_execution(
            db_task,
            executing_agent_id=entry["agent_id"],
            success=entry["success"],
            duration_ms=entry["duration_ms"],
            started_at=entry.get("started_at"),
            completed_at=entry.get("completed_at"),
            attempt=domain_task.retry_count + 1,
            correlation_id=correlation_id,
        )
