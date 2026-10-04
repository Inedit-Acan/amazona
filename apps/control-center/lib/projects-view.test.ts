import assert from "node:assert/strict";
import { test } from "node:test";
import type { AuditEntry, Decision, DecisionEvidence, Project, ProjectStatus, Task } from "./api.ts";
import {
  NOT_CALCULATED,
  NO_DATA,
  PLAN_ABSENCE_TEXT,
  PROJECT_CODE_PREFIX,
  PROJECT_STATUS_LABEL,
  filterProjects,
  formatPlanAmount,
  formatPlanMargin,
  nextStep,
  portfolioCounts,
  projectCard,
  projectCodeFor,
  statusDistribution,
  type ProjectSource,
} from "./projects-view.ts";

// --- Material de prueba ---------------------------------------------------------------------------------------------

const project = (over: Partial<Project> = {}): Project => ({
  id: "p-1",
  objective_id: "o-1",
  name: "Organizador de cocina de silicona",
  status: "VALIDATING",
  ...over,
});

const task = (name: string, status: Task["status"], id = `t-${name}`): Task => ({
  id,
  project_id: "p-1",
  name,
  capability: name,
  status,
  input: null,
  output: null,
  error: null,
});

const evidence = (source: string, data: Record<string, unknown> | null = null): DecisionEvidence => ({
  source,
  summary: `${source} summary`,
  data,
});

const decision = (over: Partial<Decision> = {}): Decision => ({
  id: "d-1",
  project_id: "p-1",
  status: "GO",
  opportunity_score: 78,
  confidence: 0.85,
  rationale: "Las cuatro validaciones pasan.",
  correlation_id: "c-1",
  evidence: [
    evidence("product_validation", { recommendation: "GO" }),
    evidence("finance_validation", { monthly_profit: 1234.5, margin: 0.42 }),
  ],
  ...over,
});

const audit = (action: string, resource: string, created_at: string, id = `${action}-${resource}`): AuditEntry => ({
  id,
  actor: "ceo",
  action,
  resource,
  before: null,
  after: null,
  correlation_id: "c-1",
  created_at,
});

function source(over: Partial<ProjectSource> = {}): ProjectSource {
  return {
    project: project(),
    tasks: [
      task("product_validation", "COMPLETED"),
      task("supplier_sourcing", "COMPLETED"),
      task("finance_validation", "RUNNING"),
      task("legal_validation", "PENDING"),
    ],
    decision: decision(),
    audit: [
      audit("project.created", "project:p-1", "2026-09-12T10:00:00Z"),
      audit("tasks.created", "project:p-1", "2026-09-12T10:00:05Z"),
      audit("task.completed", "task:t-product_validation", "2026-09-12T10:01:00Z"),
      audit("decision.made", "decision:d-1", "2026-09-12T10:05:00Z"),
    ],
    ...over,
  };
}

// --- El proyecto -----------------------------------------------------------------------------------------------------

test("projectCard: cada campo sale del backend, con el estado que el backend guarda", () => {
  const card = projectCard(source());
  assert.equal(card.id, "p-1");
  assert.equal(card.name, "Organizador de cocina de silicona");
  assert.equal(card.status, "VALIDATING");
  assert.equal(card.statusLabel, "En validación");
  assert.equal(card.group, "validation");
  assert.equal(card.stages.length, 4);
  assert.deepEqual(
    card.stages.map((stage) => stage.state),
    ["done", "done", "current", "todo"],
  );
  assert.equal(card.stages[0].recommendation, "GO", "la recomendación es la de la evidencia, no una nuestra");
  assert.deepEqual(card.progress, { done: 2, total: 4, ratio: 0.5 });
  assert.equal(card.decisionStatus, "GO");
  assert.equal(card.decisionLabel, "Aprobada");
  assert.equal(card.confidence, 0.85);
  assert.equal(card.opportunityScore, 78);
});

test("projectCard: el inicio es la entrada `project.created` de la auditoría, nunca una fecha calculada", () => {
  const card = projectCard(source());
  assert.equal(card.startedAt, Date.parse("2026-09-12T10:00:00Z"));

  const withoutAudit = projectCard(source({ audit: [] }));
  assert.equal(withoutAudit.startedAt, null, "sin auditoría no hay fecha: se dice «Sin datos»");

  // Una entrada de OTRO proyecto no sirve para fechar éste.
  const other = projectCard(source({ audit: [audit("project.created", "project:p-2", "2026-01-01T00:00:00Z")] }));
  assert.equal(other.startedAt, null);
});

test("projectCard: un hito se fecha con `task.completed` de SU tarea, o no se fecha", () => {
  const card = projectCard(source());
  const byTask = Object.fromEntries(card.milestones.map((milestone) => [milestone.task, milestone]));
  assert.equal(byTask.product_validation.at, Date.parse("2026-09-12T10:01:00Z"));
  assert.equal(byTask.supplier_sourcing.at, null, "completada pero sin entrada de auditoría: sin fecha");
  assert.equal(byTask.finance_validation.at, null);
  assert.equal(card.milestones.length, 4);
});

test("projectCard: la proyección es PLAN y lleva su procedencia en el tipo", () => {
  const card = projectCard(source());
  assert.equal(card.plannedMonthlyProfit?.provenance, "planned");
  assert.equal(card.plannedMonthlyProfit?.value, 1234.5);
  assert.equal(card.plannedMargin?.provenance, "planned");
  assert.equal(card.plannedMargin?.value, 0.42);
  assert.equal(card.planAbsence, null);
});

test("projectCard: sin fuente para la proyección se dice por qué, y nunca es cero", () => {
  const noDecision = projectCard(source({ decision: null }));
  assert.equal(noDecision.plannedMonthlyProfit, null);
  assert.equal(noDecision.planAbsence, "no_decision");
  assert.equal(noDecision.confidence, null, "sin decisión la confianza no es cero");
  assert.equal(noDecision.opportunityScore, null);
  assert.deepEqual(noDecision.risks, []);

  const noEvidence = projectCard(source({ decision: decision({ evidence: [evidence("product_validation")] }) }));
  assert.equal(noEvidence.plannedMonthlyProfit, null);
  assert.equal(noEvidence.planAbsence, "no_finance_evidence");

  // El agente de finanzas devuelve la evidencia sin `monthly_profit` cuando le faltan datos del objetivo.
  const notProjected = projectCard(
    source({ decision: decision({ evidence: [evidence("finance_validation", { finance_veto: false })] }) }),
  );
  assert.equal(notProjected.plannedMonthlyProfit, null);
  assert.equal(notProjected.planAbsence, "not_projected");

  for (const absence of Object.values(PLAN_ABSENCE_TEXT)) assert.ok(absence.length > 20, "cada ausencia explica su motivo");
});

test("projectCard: un beneficio proyectado de cero es cero, no «sin datos»", () => {
  const zero = projectCard(source({ decision: decision({ evidence: [evidence("finance_validation", { monthly_profit: 0 })] }) }));
  assert.equal(zero.plannedMonthlyProfit?.value, 0);
  assert.equal(zero.planAbsence, null);
  assert.equal(zero.plannedMargin, null, "sin margen declarado, el margen no se deduce del beneficio");
});

test("projectCard: los riesgos son el texto literal de la evidencia, sin nivel inventado", () => {
  const card = projectCard(
    source({
      decision: decision({
        evidence: [evidence("legal_validation", { risks: ["documentación pendiente"] }), evidence("finance_validation", { monthly_profit: 10 })],
      }),
    }),
  );
  assert.deepEqual(card.risks, [{ stage: "Legal", risk: "documentación pendiente" }]);
  assert.ok(!Object.keys(card.risks[0]).includes("level"));
});

// --- La cartera -------------------------------------------------------------------------------------------------------

const STATUSES: ProjectStatus[] = [
  "DRAFT",
  "VALIDATING",
  "APPROVED",
  "EXECUTING",
  "MONITORING",
  "PAUSED",
  "COMPLETED",
  "REJECTED",
  "FAILED",
];

const everyStatus = () =>
  STATUSES.map((status, index) => projectCard(source({ project: project({ id: `p-${index}`, status }), audit: [], decision: null })));

test("portfolioCounts: reparte los estados del backend y no suma ni una cifra de dinero", () => {
  const counts = portfolioCounts(everyStatus());
  assert.equal(counts.total, STATUSES.length);
  assert.equal(counts.validation, 2);
  assert.equal(counts.execution, 3);
  assert.equal(counts.paused, 1);
  assert.equal(counts.closed, 3);
  assert.equal(counts.validation + counts.execution + counts.paused + counts.closed, counts.total);
  assert.equal(counts.withPlan, 0, "ninguno tiene decisión, así que ninguno tiene proyección");
  assert.deepEqual(Object.keys(counts).sort(), ["closed", "execution", "paused", "total", "validation", "withPlan"].sort());

  const withPlan = portfolioCounts([projectCard(source())]);
  assert.equal(withPlan.withPlan, 1);
});

test("statusDistribution: el reparto suma exactamente los proyectos que hay", () => {
  const projects = everyStatus();
  const distribution = statusDistribution(projects);
  assert.equal(
    distribution.reduce((sum, item) => sum + item.value, 0),
    projects.length,
  );
});

test("filterProjects: pestañas, búsqueda por id o nombre y estado del backend", () => {
  const projects = everyStatus();
  assert.equal(filterProjects(projects, { tab: "all" }).length, projects.length);
  assert.ok(filterProjects(projects, { tab: "closed" }).every((p) => ["COMPLETED", "REJECTED", "FAILED"].includes(p.status)));
  assert.ok(filterProjects(projects, { tab: "paused" }).every((p) => p.status === "PAUSED"));
  assert.deepEqual(filterProjects(projects, { tab: "all", query: "p-3" }).map((p) => p.id), ["p-3"]);
  assert.equal(filterProjects(projects, { tab: "all", query: "silicona" }).length, projects.length, "busca también por nombre");
  assert.deepEqual(filterProjects(projects, { tab: "all", status: "PAUSED" }).map((p) => p.status), ["PAUSED"]);
  assert.equal(filterProjects(projects, { tab: "closed", status: "PAUSED" }).length, 0);
});

test("PROJECT_STATUS_LABEL cubre todos los estados del backend, sin inventar ninguno", () => {
  assert.deepEqual(Object.keys(PROJECT_STATUS_LABEL).sort(), [...STATUSES].sort());
});

// --- Detalle ----------------------------------------------------------------------------------------------------------

test("nextStep: la primera etapa que el backend no tiene completada", () => {
  const step = nextStep(projectCard(source()));
  assert.equal(step.stage?.task, "finance_validation");
  assert.equal(step.title, "Validar la economía");
  assert.equal(step.href, "/economics");
  assert.equal(step.decision, "Aprobada");

  const done = nextStep(
    projectCard(
      source({
        tasks: ["product_validation", "supplier_sourcing", "finance_validation", "legal_validation"].map((name) =>
          task(name, "COMPLETED"),
        ),
      }),
    ),
  );
  assert.equal(done.stage, null);
  assert.equal(done.href, null);
});

// --- Presentación -----------------------------------------------------------------------------------------------------

test("formatPlanAmount no pone símbolo de moneda: la evidencia financiera no declara ninguna", () => {
  // es-ES no agrupa los millares de un numero de cuatro digitos; con cinco si.
  const text = formatPlanAmount(1234.5);
  assert.equal(text, "1234,50");
  assert.equal(formatPlanAmount(12345.5), "12.345,50");
  assert.ok(!/[€$£]|EUR|USD/.test(text));
  // Intl separa el porcentaje con un espacio estrecho que no se rompe, no con un espacio normal.
  assert.ok(/^42\s%$/.test(formatPlanMargin(0.42)), formatPlanMargin(0.42));
});

test("projectCodeFor no cambia: Aprobaciones, el Panel y Auditoría dependen de él", () => {
  assert.equal(PROJECT_CODE_PREFIX, "AMZ-");
  assert.equal(projectCodeFor(0), "AMZ-0024");
  assert.equal(projectCodeFor(1), "AMZ-0023");
  assert.equal(projectCodeFor(11), "AMZ-0013");
});

test("NOT_CALCULATED dice qué falta y por qué, y «Sin datos» es el vocabulario de siempre", () => {
  assert.ok(NOT_CALCULATED.length >= 5);
  for (const item of NOT_CALCULATED) {
    assert.ok(item.label.length > 5);
    assert.ok(item.reason.length > 30, `«${item.label}» no explica su motivo`);
  }
  assert.ok(NOT_CALCULATED.some((item) => /ingresos|ventas/i.test(item.label)));
  assert.ok(NOT_CALCULATED.some((item) => /capital/i.test(item.label)));
  assert.equal(NO_DATA, "Sin datos");
});
