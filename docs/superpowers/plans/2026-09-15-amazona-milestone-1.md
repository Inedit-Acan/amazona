# AMAZONA Milestone 1 Implementation Plan

> **For agentic workers:** Implement task-by-task with TDD, small commits, and review after each task.

**Goal:** Build the first functional AMAZONA core in which a CEO Orchestrator can receive a simulated product-validation objective, decompose it into tasks, route those tasks to Product, Supplier, Finance, and Legal agents, collect structured results, run a deterministic decision engine, request human approval when required, and persist the full audit trail.

**Architecture:** Start as a modular monolith with clear internal boundaries. Use Next.js/React/TypeScript for the Control Center, FastAPI/Python/Pydantic for the backend, PostgreSQL/Supabase for persistence, Redis for task/event coordination, pgvector reserved for later semantic memory, and an AI Gateway abstraction so models can be switched without coupling agents to providers.

**Tech Stack:** Next.js, React, TypeScript, Tailwind CSS, shadcn/ui, Python 3.12+, FastAPI, Pydantic v2, SQLAlchemy 2.x, Alembic, PostgreSQL/Supabase, Redis, pytest, pytest-asyncio, httpx, Docker, GitHub Actions.

**Spec:** Implements the approved CEO design blocks 1–10 for Milestone 1 only.

## Global Constraints

- Cloud-ready 24/7 architecture, but local development must work with Docker Compose.
- Modular monolith first; no microservices.
- CEO coordinates; specialist agents do domain work.
- LLM recommendations never override deterministic permissions, budget limits, vetoes, or human-approval requirements.
- No real money, ads, orders, suppliers, or tax submissions in Milestone 1.
- All agent outputs must be structured and validated.
- Every important action must be auditable.
- Human approval remains mandatory for any simulated external spend.
- Agent learning may propose policy changes but may not change permissions automatically.
- Obsidian is not a runtime dependency.
- PostgreSQL is the source of truth for operational state.
- Tests are required before implementation for deterministic core behavior.
- Commit after each independently testable task.

---

## File Structure

```text
amazona/
├── apps/
│   └── control-center/
│       ├── app/
│       │   ├── dashboard/
│       │   ├── approvals/
│       │   ├── projects/
│       │   └── agents/
│       ├── components/
│       └── lib/
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── core/
│   │   │   ├── config.py
│   │   │   ├── logging.py
│   │   │   ├── ids.py
│   │   │   └── errors.py
│   │   ├── db/
│   │   │   ├── base.py
│   │   │   ├── session.py
│   │   │   └── models/
│   │   ├── api/
│   │   │   ├── objectives.py
│   │   │   ├── projects.py
│   │   │   ├── tasks.py
│   │   │   ├── agents.py
│   │   │   ├── decisions.py
│   │   │   └── approvals.py
│   │   ├── events/
│   │   │   ├── schemas.py
│   │   │   └── bus.py
│   │   ├── tasks/
│   │   │   ├── schemas.py
│   │   │   └── service.py
│   │   ├── agents/
│   │   │   ├── base.py
│   │   │   ├── registry.py
│   │   │   ├── manager.py
│   │   │   ├── product.py
│   │   │   ├── supplier.py
│   │   │   ├── finance.py
│   │   │   └── legal.py
│   │   ├── ai/
│   │   │   ├── gateway.py
│   │   │   └── mock_provider.py
│   │   ├── ceo/
│   │   │   ├── planner.py
│   │   │   ├── orchestrator.py
│   │   │   ├── decision_engine.py
│   │   │   └── schemas.py
│   │   ├── permissions/
│   │   │   ├── engine.py
│   │   │   └── policies.py
│   │   ├── budgets/
│   │   │   └── engine.py
│   │   ├── approvals/
│   │   │   └── service.py
│   │   └── audit/
│   │       └── service.py
│   ├── tests/
│   │   ├── unit/
│   │   ├── integration/
│   │   └── e2e/
│   ├── alembic/
│   └── pyproject.toml
├── infra/
│   ├── docker-compose.yml
│   └── env.example
├── docs/
│   ├── architecture/
│   └── milestones/
└── README.md
```

---

## Task 1: Repository bootstrap and local runtime

**Files:**
- Create: `README.md`
- Create: `infra/docker-compose.yml`
- Create: `infra/env.example`
- Create: `backend/pyproject.toml`
- Create: `backend/app/main.py`
- Create: `backend/tests/unit/test_health.py`

**Produces:**
- `GET /health`
- Local PostgreSQL + Redis via Docker Compose
- Python test environment

- [ ] Write failing health endpoint test.
- [ ] Run `pytest backend/tests/unit/test_health.py -v` and verify failure.
- [ ] Implement FastAPI app and `/health`.
- [ ] Run tests and verify pass.
- [ ] Start Docker Compose and verify PostgreSQL/Redis are healthy.
- [ ] Commit: `chore: bootstrap amazona backend and local infra`

**Acceptance:**
`curl http://localhost:8000/health` returns HTTP 200 with service status.

---

## Task 2: Core configuration, IDs, and structured logging

**Files:**
- Create: `backend/app/core/config.py`
- Create: `backend/app/core/ids.py`
- Create: `backend/app/core/logging.py`
- Create: `backend/tests/unit/test_ids.py`
- Create: `backend/tests/unit/test_config.py`

**Produces:**
- Typed settings
- UUID/correlation-id helpers
- JSON structured logs

- [ ] Write tests for stable settings loading and unique IDs.
- [ ] Run tests, verify failure.
- [ ] Implement minimal config and ID helpers.
- [ ] Add request correlation-id middleware.
- [ ] Run tests.
- [ ] Commit: `feat: add configuration and correlation ids`

**Acceptance:**
Every API request receives a correlation ID and log output includes it.

---

## Task 3: Database foundation and migrations

**Files:**
- Create: `backend/app/db/base.py`
- Create: `backend/app/db/session.py`
- Create: `backend/app/db/models/*.py`
- Create: `backend/alembic/*`
- Create: `backend/tests/integration/test_database.py`

**Initial tables:**
- `objectives`
- `projects`
- `tasks`
- `task_dependencies`
- `agents`
- `agent_capabilities`
- `events`
- `decisions`
- `decision_evidence`
- `approvals`
- `budgets`
- `budget_allocations`
- `financial_events`
- `policies`
- `incidents`
- `audit_log`

**Produces:**
SQLAlchemy models and Alembic migration.

- [ ] Write integration test that opens a transaction and persists an objective.
- [ ] Run and verify failure.
- [ ] Implement DB session + models needed for objective persistence.
- [ ] Expand models to all initial tables.
- [ ] Generate first Alembic migration.
- [ ] Apply migration to local PostgreSQL.
- [ ] Run integration tests.
- [ ] Commit: `feat: add operational database schema`

**Acceptance:**
A clean database can be created from migrations with no manual steps.

---

## Task 4: Domain enums and shared schemas

**Files:**
- Create: `backend/app/ceo/schemas.py`
- Create: `backend/app/tasks/schemas.py`
- Create: `backend/app/events/schemas.py`
- Create: `backend/app/agents/base.py`
- Create: `backend/tests/unit/test_schemas.py`

**Required enums:**
- Task: `PENDING`, `QUEUED`, `RUNNING`, `WAITING`, `WAITING_APPROVAL`, `COMPLETED`, `FAILED`, `CANCELLED`, `BLOCKED`
- Project: `DRAFT`, `VALIDATING`, `APPROVED`, `EXECUTING`, `MONITORING`, `PAUSED`, `COMPLETED`, `REJECTED`, `FAILED`
- Decision: `GO`, `REVIEW`, `NO_GO`, `HUMAN_APPROVAL`
- Agent: `AVAILABLE`, `BUSY`, `WAITING`, `BLOCKED`, `DEGRADED`, `DISABLED`, `FAILED`
- Approval: `PENDING`, `APPROVED`, `REJECTED`, `EXPIRED`, `CANCELLED`

**AgentResult fields:**
- `status`
- `recommendation`
- `confidence`
- `evidence`
- `risks`
- `assumptions`
- `data`

- [ ] Write schema-validation tests.
- [ ] Verify invalid confidence values fail.
- [ ] Implement Pydantic schemas.
- [ ] Run tests.
- [ ] Commit: `feat: define core domain schemas`

**Acceptance:**
Inter-agent communication cannot use arbitrary free-form payloads for decision-critical results.

---

## Task 5: Event bus abstraction

**Files:**
- Create: `backend/app/events/bus.py`
- Create: `backend/tests/unit/test_event_bus.py`

**Interfaces:**
- `publish(event: Event) -> None`
- `subscribe(event_type: str, handler: Callable) -> None`

**V1 implementation:**
In-process bus with a Redis adapter interface reserved but not required yet.

- [ ] Write test for publish/subscribe.
- [ ] Write test preserving correlation ID.
- [ ] Implement in-process event bus.
- [ ] Run tests.
- [ ] Commit: `feat: add internal event bus`

**Acceptance:**
An event emitted by one module can trigger a handler without direct module coupling.

---

## Task 6: Task service and dependency graph

**Files:**
- Create: `backend/app/tasks/service.py`
- Create: `backend/tests/unit/test_task_service.py`

**Interfaces:**
- `create_task(...)`
- `add_dependency(parent_id, child_id)`
- `mark_running(task_id)`
- `mark_completed(task_id, output)`
- `mark_failed(task_id, error)`
- `get_runnable_tasks(project_id)`

- [ ] Test a task with unmet dependency is not runnable.
- [ ] Test dependency completion unlocks child task.
- [ ] Implement minimal DAG logic.
- [ ] Run tests.
- [ ] Commit: `feat: add task dependency engine`

**Acceptance:**
Parallel and sequential tasks can be represented deterministically.

---

## Task 7: Agent Registry

**Files:**
- Create: `backend/app/agents/registry.py`
- Create: `backend/tests/unit/test_agent_registry.py`

**Interfaces:**
- `register(agent_descriptor)`
- `find_by_capability(capability, region=None)`
- `set_status(agent_id, status)`
- `get_health(agent_id)`

**Descriptor fields:**
- id
- name
- role
- version
- capabilities
- permissions
- reliability score
- cost profile
- latency profile
- supported regions/languages

- [ ] Test registration.
- [ ] Test capability routing.
- [ ] Test disabled agents are excluded.
- [ ] Implement.
- [ ] Commit: `feat: add agent registry`

**Acceptance:**
The CEO never hardcodes a concrete agent implementation by name.

---

## Task 8: Agent Manager

**Files:**
- Create: `backend/app/agents/manager.py`
- Create: `backend/tests/unit/test_agent_manager.py`

**Interfaces:**
- `select_agent(capability, context) -> AgentDescriptor`
- `execute(agent_id, task) -> AgentResult`

**Selection factors V1:**
- capability match
- status
- reliability
- simulated cost
- load

- [ ] Test healthy high-reliability agent wins.
- [ ] Test unavailable agent is skipped.
- [ ] Implement routing.
- [ ] Commit: `feat: add capability based agent manager`

**Acceptance:**
Agent selection is deterministic for the same registry state.

---

## Task 9: AI Gateway abstraction with mock provider

**Files:**
- Create: `backend/app/ai/gateway.py`
- Create: `backend/app/ai/mock_provider.py`
- Create: `backend/tests/unit/test_ai_gateway.py`

**Interfaces:**
- `execute(task_type, prompt, schema, limits) -> structured result`

**V1 behavior:**
- only mock provider required
- records estimated token/cost metadata
- enforces timeout/cost ceiling fields structurally

- [ ] Test provider independence.
- [ ] Test cost limit rejection.
- [ ] Implement mock provider and gateway.
- [ ] Commit: `feat: add model agnostic ai gateway`

**Acceptance:**
No agent imports provider SDKs directly.

---

## Task 10: Four simulated specialist agents

**Files:**
- Create: `backend/app/agents/product.py`
- Create: `backend/app/agents/supplier.py`
- Create: `backend/app/agents/finance.py`
- Create: `backend/app/agents/legal.py`
- Create: `backend/tests/unit/test_simulated_agents.py`

**Capabilities:**
- Product: `market_validation`
- Supplier: `supplier_sourcing`
- Finance: `financial_validation`
- Legal: `legal_validation`

**V1 behavior:**
Deterministic fixtures driven by test inputs; no live web.

- [ ] Write test for each agent returning valid `AgentResult`.
- [ ] Implement minimal deterministic logic.
- [ ] Register all agents.
- [ ] Run tests.
- [ ] Commit: `feat: add milestone one specialist agents`

**Acceptance:**
Each agent returns structured evidence, confidence, risks, assumptions, and domain output.

---

## Task 11: CEO Planner

**Files:**
- Create: `backend/app/ceo/planner.py`
- Create: `backend/tests/unit/test_planner.py`

**Interface:**
`plan_product_validation(objective) -> ProjectPlan`

**Expected DAG:**
1. Product validation
2. Supplier sourcing
3. Finance validation
4. Legal validation
5. Decision synthesis

Supplier, Finance, and Legal may be configured to run after Product; Finance may depend on Supplier if landed cost is needed.

- [ ] Write expected-plan test.
- [ ] Verify exact task dependencies.
- [ ] Implement planner.
- [ ] Commit: `feat: add ceo project planner`

**Acceptance:**
One objective deterministically becomes a valid project/task graph.

---

## Task 12: Decision Engine

**Files:**
- Create: `backend/app/ceo/decision_engine.py`
- Create: `backend/tests/unit/test_decision_engine.py`

**Inputs:**
- opportunity score
- confidence
- risk
- legal status
- finance veto
- security veto
- human-policy requirement

**Outputs:**
`GO | REVIEW | NO_GO | HUMAN_APPROVAL`

**Mandatory rules:**
- Legal BLOCKED -> `NO_GO`
- Finance insolvency/negative certain margin veto -> `NO_GO`
- Insufficient data -> `REVIEW`
- External simulated spend with autonomy B -> `HUMAN_APPROVAL`
- High score cannot bypass veto
- Human stop always wins

- [ ] Write veto tests first.
- [ ] Write confidence threshold tests.
- [ ] Write human-approval test.
- [ ] Implement deterministic engine.
- [ ] Run full unit suite.
- [ ] Commit: `feat: add deterministic ceo decision engine`

**Acceptance:**
The decision engine needs no LLM to enforce critical rules.

---

## Task 13: Permission Engine

**Files:**
- Create: `backend/app/permissions/policies.py`
- Create: `backend/app/permissions/engine.py`
- Create: `backend/tests/unit/test_permission_engine.py`

**V1 policy:**
- research/read actions: allowed
- simulated draft creation: allowed
- any simulated external spend: human approval
- policy editing: owner only
- permission self-escalation: forbidden

- [ ] Write permission tests.
- [ ] Test agent cannot grant itself permissions.
- [ ] Implement.
- [ ] Commit: `feat: add policy based permission engine`

**Acceptance:**
Permissions are deterministic and external to LLM outputs.

---

## Task 14: Budget Engine

**Files:**
- Create: `backend/app/budgets/engine.py`
- Create: `backend/tests/unit/test_budget_engine.py`

**Interfaces:**
- `authorize(request, budget_state) -> BudgetDecision`
- `reserve(amount)`
- `release(amount)`
- `commit(amount)`

**Mandatory behavior:**
- hard limit blocks
- soft limit warns
- committed funds reduce availability
- reserved tax/locked funds unavailable
- single-action limit enforced
- no overspend via repeated rapid requests

- [ ] Write hard-limit tests.
- [ ] Write committed-vs-spent test.
- [ ] Write velocity-limit test.
- [ ] Implement.
- [ ] Commit: `feat: add budget guardrails`

**Acceptance:**
A repeated task cannot exceed the configured budget envelope.

---

## Task 15: Approval service

**Files:**
- Create: `backend/app/approvals/service.py`
- Create: `backend/tests/unit/test_approvals.py`

**Interfaces:**
- `create_approval(decision_id, action, amount, expiry)`
- `approve(id, actor)`
- `reject(id, actor)`
- `expire_pending(now)`

**Mandatory behavior:**
- approvals are contextual
- expired approvals cannot execute
- approval cannot be reused
- all transitions audited

- [ ] Write lifecycle tests.
- [ ] Test expiry.
- [ ] Test replay prevention.
- [ ] Implement.
- [ ] Commit: `feat: add human approval workflow`

**Acceptance:**
A human approval authorizes one explicit action only.

---

## Task 16: Audit service

**Files:**
- Create: `backend/app/audit/service.py`
- Create: `backend/tests/unit/test_audit.py`

**Audit fields:**
- actor
- action
- resource
- before
- after
- timestamp
- correlation_id

- [ ] Write audit append test.
- [ ] Ensure audit entries are never updated in-place.
- [ ] Implement.
- [ ] Commit: `feat: add immutable audit trail`

**Acceptance:**
The complete simulated workflow can be reconstructed from audit events.

---

## Task 17: CEO Orchestrator

**Files:**
- Create: `backend/app/ceo/orchestrator.py`
- Create: `backend/tests/integration/test_ceo_orchestrator.py`

**Interface:**
`run_objective(objective_id) -> Decision`

**Flow:**
1. load objective
2. create project
3. ask planner for DAG
4. create tasks
5. route runnable tasks to Agent Manager
6. persist outputs/evidence
7. run decision engine
8. run permission + budget checks
9. create approval if required
10. persist decision
11. emit events
12. audit all important transitions

- [ ] Write failing integration test for complete simulated objective.
- [ ] Implement orchestration minimally.
- [ ] Run integration test.
- [ ] Add failure-path test where Legal vetoes.
- [ ] Commit: `feat: orchestrate simulated product validation`

**Acceptance:**
One call produces a persisted project, tasks, agent results, evidence, final decision, and approval request where required.

---

## Task 18: REST API for Milestone 1

**Files:**
- Create: API modules under `backend/app/api/`
- Modify: `backend/app/main.py`
- Create: `backend/tests/integration/test_api.py`

**Required endpoints:**
- `POST /api/objectives`
- `POST /api/objectives/{id}/run`
- `GET /api/projects/{id}`
- `GET /api/tasks?project_id=`
- `GET /api/agents`
- `GET /api/decisions/{id}`
- `GET /api/approvals`
- `POST /api/approvals/{id}/approve`
- `POST /api/approvals/{id}/reject`
- `GET /api/audit?correlation_id=`

- [ ] Write API tests.
- [ ] Implement endpoints.
- [ ] Run tests.
- [ ] Commit: `feat: expose milestone one api`

**Acceptance:**
Milestone 1 can be operated without direct DB access.

---

## Task 19: Control Center shell

**Files:**
- Create Next.js app under `apps/control-center/`
- Create dashboard, projects, approvals, agents pages.

**V1 visual goal:**
Premium internal dashboard even though data is still simulated.

**Pages:**
- Dashboard
- CEO
- Projects
- Agents
- Approvals
- Audit

- [ ] Scaffold Next.js + TypeScript.
- [ ] Add Tailwind + shadcn/ui.
- [ ] Build static shell using mock data.
- [ ] Connect API client.
- [ ] Replace mock data page-by-page.
- [ ] Commit: `feat: add amazona control center shell`

**Acceptance:**
The owner can inspect current business state and approvals from desktop/mobile.

---

## Task 20: Mobile approval flow

**Files:**
- Modify approval page/components.
- Create approval card component.
- Add responsive tests where practical.

**Card must show:**
- action
- project/product
- amount
- risk
- confidence
- finance status
- legal status
- CEO recommendation
- expiry

**Actions:**
- Approve
- Reject
- More information (V1 may show expanded evidence instead of starting a new AI workflow)

- [ ] Build mobile-first approval card.
- [ ] Wire approve/reject actions.
- [ ] Verify expired approval cannot be approved.
- [ ] Commit: `feat: add mobile approval experience`

**Acceptance:**
An approval can be reviewed and resolved from a phone-sized viewport.

---

## Task 21: End-to-end simulation

**Files:**
- Create: `backend/tests/e2e/test_product_validation_flow.py`
- Create: `docs/milestones/milestone-1-demo.md`

**Scenario A — Human approval:**
- Product: attractive
- Supplier: viable
- Finance: profitable
- Legal: clear
- Simulated marketing spend requested
- Result: `HUMAN_APPROVAL`

**Scenario B — Legal veto:**
- Same product
- Legal: BLOCKED
- Result: `NO_GO`
- No approval request created

**Scenario C — Insufficient confidence:**
- Weak data
- Result: `REVIEW`

- [ ] Write E2E tests.
- [ ] Run and verify all pass.
- [ ] Document demo commands.
- [ ] Commit: `test: verify milestone one end to end flows`

**Acceptance:**
The complete CEO workflow is reproducible from a clean environment.

---

## Task 22: CI, quality gates, and Milestone 1 release

**Files:**
- Create GitHub Actions workflow.
- Update README.

**CI must run:**
- Python lint/type checks
- pytest
- frontend lint/typecheck/build

**Release gate:**
- all tests green
- clean database migration
- no real provider credentials required
- no real external side effects
- audit trail verified
- budget/permission veto tests green

- [ ] Add CI.
- [ ] Run locally.
- [ ] Fix failures.
- [ ] Tag `milestone-1`.
- [ ] Commit: `ci: enforce milestone one quality gates`

---

# Milestone 1 Definition of Done

Milestone 1 is complete only when all of the following are true:

1. An owner can create a product-validation objective from the Control Center or API.
2. The CEO Planner creates a project and dependency-aware tasks.
3. Product, Supplier, Finance, and Legal agents execute as independent modules.
4. The Agent Manager routes tasks by capability.
5. Results are structured and persisted.
6. Evidence is stored separately from conclusions.
7. The deterministic Decision Engine returns `GO`, `REVIEW`, `NO_GO`, or `HUMAN_APPROVAL`.
8. Legal/Finance vetoes cannot be overridden by a high opportunity score.
9. The Permission Engine prevents unauthorized external actions.
10. The Budget Engine enforces hard limits.
11. Human approvals expire and cannot be replayed.
12. Every material action is traceable by correlation ID.
13. The Control Center shows projects, agents, decisions, approvals, and audit history.
14. The complete simulated flow passes E2E tests.
15. No real money or external commercial action can occur.

# After Milestone 1

Do **not** immediately build all remaining agents. Next milestone should be:

**Milestone 2 — Real read-only product research**

Add live public data/search integrations to Product and Supplier agents while preserving:
- no spending
- no order placement
- no advertising
- no contract acceptance

Only after Milestone 2 produces trustworthy real-world decisions should AMAZONA progress to autonomous product discovery, marketing, ecommerce, payments, and the first controlled real sale.
