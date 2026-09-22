import assert from "node:assert/strict";
import { test } from "node:test";
import { DEMO_CLOSED_PROJECTS, DEMO_PROJECTS } from "./demo/projects.ts";
import { buildOrders, startOfDay, type ProductInput, type SupplierInput } from "./operations-view.ts";
import {
  PHASES,
  demoProjects,
  filterProjects,
  learnings,
  nextDecision,
  phaseDistribution,
  plannedVsActual,
  portfolioCounts,
  profitByMarket,
  projectFromProduct,
  projectMilestones,
  projectRisks,
  type ProductProjectInput,
} from "./projects-view.ts";
import type { AuditEntry, EconomicAnalysis, LegalAnalysis, Product, Storefront, SupplierQuote } from "./api.ts";

const TODAY = startOfDay("2026-09-22");

const PRODUCT: Product = { id: "917ef890", name: "Silicone kitchen organizer", category: "home", status: "CANDIDATE", created_by: "agent", source: "research" };

const QUOTE: SupplierQuote = {
  id: "q1",
  product_id: PRODUCT.id,
  supplier_id: "sup-eu",
  unit_price: 3.4,
  moq: 10,
  lead_time_days: 10,
  verified: true,
  reliability_score: 0.9,
  logistics_cost_per_unit: 1.2,
  total_landed_cost_per_unit: 4.6,
  data: { name: "Bratislava Homeware Supply", region: "eu" },
};

const ANALYSIS: EconomicAnalysis = {
  correlation_id: "c-eco",
  product_id: PRODUCT.id,
  supplier_quote_id: "q1",
  sale_price: 50,
  monthly_fixed_costs: 500,
  margin_percent: 0.93,
  recommendation: "GO",
  confidence: 0.85,
  data: {
    scenarios: {
      conservative: { monthly_unit_sales: 186, margin_percent: 0.93, monthly_revenue: 9318, monthly_profit: 8197 },
      base: { monthly_unit_sales: 266, margin_percent: 0.93, monthly_revenue: 13312, monthly_profit: 11924 },
      optimistic: { monthly_unit_sales: 346, margin_percent: 0.93, monthly_revenue: 17306, monthly_profit: 15651 },
    },
  },
};

const LEGAL: LegalAnalysis = {
  correlation_id: "c-legal",
  product_id: PRODUCT.id,
  supplier_quote_id: "q1",
  market: "eu",
  restricted: false,
  recommendation: "GO",
  confidence: 0.8,
  data: { required_certifications: ["CE"], known_risks: ["documentación pendiente"], recent_changes: [] },
};

const STOREFRONT: Storefront = {
  correlation_id: "c-store",
  product_id: PRODUCT.id,
  market: "eu",
  store_slug: "silicone",
  launch_status: "READY",
  recommendation: "GO",
  confidence: 0.8,
  data: null,
};

const AUDIT: AuditEntry[] = [
  { id: "a1", actor: "agent", action: "research.run", resource: "research:1", before: null, after: null, correlation_id: "c1", created_at: "2026-09-12T10:00:00Z" },
  { id: "a2", actor: "agent", action: "sourcing.run", resource: "sourcing:1", before: null, after: null, correlation_id: "c2", created_at: "2026-09-13T11:00:00Z" },
  { id: "a3", actor: "agent", action: "economics.run", resource: "economics:1", before: null, after: null, correlation_id: "c3", created_at: "2026-09-14T09:00:00Z" },
];

const SUPPLIERS: SupplierInput[] = [
  { id: "sup-eu", name: "Bratislava Homeware Supply", region: "eu", leadTimeDays: 10, reliability: 0.9, verified: true, isDemo: false },
];
const ORDERS = buildOrders([{ id: PRODUCT.id, name: PRODUCT.name, sku: "AMZ-HOM-917", price: 50, suppliers: SUPPLIERS }], "2026-09-22");

function input(overrides: Partial<ProductProjectInput> = {}): ProductProjectInput {
  return {
    product: PRODUCT,
    quotes: [QUOTE],
    economics: [ANALYSIS],
    legal: [LEGAL],
    storefronts: [STOREFRONT],
    campaigns: [],
    operations: [],
    orders: ORDERS,
    audit: AUDIT,
    market: "eu",
    ...overrides,
  };
}

test("projectFromProduct: una fase por etapa con el estado que enseña su pantalla", () => {
  const project = projectFromProduct(input(), 0, TODAY);
  assert.equal(project.phases.length, PHASES.length);
  const byKey = Object.fromEntries(project.phases.map((p) => [p.key, p]));
  assert.equal(byKey.research.state, "done");
  assert.equal(byKey.suppliers.state, "done");
  assert.equal(byKey.economics.state, "done");
  // El Legal Gate es el mismo cálculo que la pantalla de Legal: con el catálogo de
  // requisitos aún sin evidencias, un análisis GO sigue dejando el gate bloqueado.
  assert.equal(byKey.legal.detail, "Bloqueado");
  assert.equal(byKey.store.state, "done");
  assert.equal(byKey.marketing.state, "todo");
  assert.equal(byKey.scale.state, "blocked");
  assert.equal(project.phase, "legal", "la fase actual es la primera sin cerrar");
  assert.equal(project.status, "Bloqueado");
  assert.ok(project.health > 0 && project.health <= 100);
  assert.ok(project.progress > 0 && project.progress < 1);
  assert.equal(project.productId, PRODUCT.id);
  assert.equal(project.isDemo, false);
  assert.equal(project.startedAt, Date.parse("2026-09-12T10:00:00Z"));
  assert.ok(project.capitalExposed > 0);
});

test("projectFromProduct: sin análisis las fases quedan pendientes y el proyecto no se bloquea", () => {
  const project = projectFromProduct(input({ quotes: [], economics: [], legal: [], storefronts: [], audit: [] }), 1, TODAY);
  const byKey = Object.fromEntries(project.phases.map((p) => [p.key, p]));
  assert.equal(byKey.economics.state, "todo");
  assert.equal(byKey.legal.detail, "Pendiente");
  assert.equal(project.phase, "suppliers");
  assert.equal(project.startedAt, TODAY - 30 * 86_400_000);
  assert.notEqual(project.status, "Bloqueado");
});

test("projectFromProduct: un Legal Gate bloqueado bloquea el proyecto", () => {
  const blocked = projectFromProduct(
    input({ legal: [{ ...LEGAL, recommendation: "NO_GO" }] }),
    0,
    TODAY,
  );
  assert.equal(blocked.phases.find((p) => p.key === "legal")!.state, "blocked");
  assert.equal(blocked.status, "Bloqueado");
});

test("demoProjects: completan la cartera con códigos distintos y fases coherentes", () => {
  const rows = demoProjects(TODAY, 23);
  assert.equal(rows.length, DEMO_PROJECTS.length + DEMO_CLOSED_PROJECTS.length);
  assert.equal(new Set(rows.map((r) => r.code)).size, rows.length);
  assert.ok(rows.every((r) => r.isDemo));
  assert.deepEqual(demoProjects(TODAY, 23), rows, "determinista");
  const closed = rows.filter((r) => r.status === "Cerrado");
  assert.equal(closed.length, DEMO_CLOSED_PROJECTS.length + 1, "PetTracker también está cerrado");
  assert.ok(closed.every((r) => r.progress === 1 || r.phase === "scale"));
});

test("portfolioCounts y phaseDistribution: activos, riesgo y reparto por bloque", () => {
  const projects = [projectFromProduct(input(), 0, TODAY), ...demoProjects(TODAY, 23)];
  const counts = portfolioCounts(projects);
  assert.equal(counts.active, projects.filter((p) => p.status !== "Cerrado").length);
  assert.equal(counts.validation + counts.launch + counts.operating, counts.active);
  assert.ok(counts.atRisk >= 1);
  assert.ok(counts.projectedProfit > 0);
  const distribution = phaseDistribution(projects);
  assert.equal(distribution.reduce((sum, d) => sum + d.value, 0), counts.active + counts.closed);
});

test("filterProjects: pestañas, búsqueda y filtros combinan", () => {
  const projects = [projectFromProduct(input(), 0, TODAY), ...demoProjects(TODAY, 23)];
  assert.equal(filterProjects(projects, { tab: "all" }).length, projects.length);
  assert.ok(filterProjects(projects, { tab: "closed" }).every((p) => p.status === "Cerrado"));
  assert.ok(filterProjects(projects, { tab: "validation" }).every((p) => p.status !== "Cerrado"));
  assert.deepEqual(
    filterProjects(projects, { tab: "all", query: "ecobottle" }).map((p) => p.name),
    ["EcoBottle"],
  );
  assert.ok(filterProjects(projects, { tab: "all", market: "us" }).every((p) => p.market === "us"));
  assert.ok(filterProjects(projects, { tab: "all", status: "En riesgo" }).every((p) => p.status === "En riesgo"));
  assert.equal(filterProjects(projects, { tab: "all", market: "us", category: "home" }).length, 0);
});

test("profitByMarket: suma el beneficio previsto de los proyectos abiertos", () => {
  const projects = demoProjects(TODAY, 23);
  const rows = profitByMarket(projects);
  const expected = projects.filter((p) => p.status !== "Cerrado").reduce((sum, p) => sum + (p.projectedProfit ?? 0), 0);
  assert.ok(Math.abs(rows.reduce((sum, r) => sum + r.value, 0) - expected) < 0.01);
  for (let k = 1; k < rows.length; k++) assert.ok(rows[k - 1].value >= rows[k].value);
});

test("nextDecision: título por fase y puertas con el estado de cada una", () => {
  const project = projectFromProduct(input(), 0, TODAY);
  const decision = nextDecision(project, { maxCac: 8.1, amount: 1500 });
  assert.equal(decision.title, "Cerrar el Legal Gate");
  assert.equal(decision.href, "/legal");
  assert.deepEqual(decision.gates.map((g) => g.label), ["Legal", "Economía", "Tienda"]);
  assert.deepEqual(decision.gates.map((g) => g.state), ["bad", "ok", "ok"]);
  assert.equal(decision.amount, 1500);
});

test("projectMilestones: marca lo hecho y fecha lo que la auditoría registró", () => {
  const project = projectFromProduct(input(), 0, TODAY);
  const rows = projectMilestones(project, AUDIT);
  assert.equal(rows.length, 8);
  assert.equal(rows[0].done, true);
  assert.equal(rows[0].at, Date.parse("2026-09-12T10:00:00Z"));
  assert.equal(rows.at(-1)!.done, false);
  assert.equal(rows.at(-1)!.at, null);
});

test("plannedVsActual y learnings: comparan con los pedidos reales del producto", () => {
  const rows = plannedVsActual({
    projectId: PRODUCT.id,
    plannedOrders: 266,
    plannedRevenue: 13312,
    plannedCac: 3.2,
    plannedMargin: 0.34,
    plannedReturnRate: 0.038,
    plannedDeliveryDays: 4,
    orders: ORDERS,
    today: TODAY,
  });
  assert.deepEqual(rows.map((r) => r.key), ["orders", "revenue", "cac", "margin", "returns", "delivery"]);
  assert.ok(rows.every((r) => r.planned > 0 && r.actual >= 0));
  const lessons = learnings(rows);
  assert.equal(lessons.length, rows.length);
  assert.ok(lessons.every((l) => l.text.length > 5 && ["ok", "warn"].includes(l.tone)));
  // Una desviación a peor en una métrica donde menos es mejor sale como aviso.
  assert.equal(learnings([{ key: "cac", label: "CAC", planned: 3, actual: 4, lowerIsBetter: true, format: "euro" }])[0].tone, "warn");
  assert.equal(learnings([{ key: "cac", label: "CAC", planned: 3, actual: 2, lowerIsBetter: true, format: "euro" }])[0].tone, "ok");
});

test("projectRisks: riesgos de los agentes más el Legal Gate y el capital", () => {
  const project = projectFromProduct(input(), 0, TODAY);
  const rows = projectRisks({
    analyses: [{ source: "Legal", risks: ["documentación pendiente"] }],
    project,
    capitalExposed: 210,
    capitalLimit: 1000,
  });
  assert.equal(rows.length, 3);
  assert.equal(rows[0].text, "documentación pendiente");
  assert.equal(rows[1].text, "Legal Gate bloqueado");
  assert.equal(rows[1].level, "Alto");
  assert.equal(rows[2].level, "Bajo");
  const overLimit = projectRisks({ analyses: [], project, capitalExposed: 5000, capitalLimit: 1000 });
  assert.equal(overLimit.at(-1)!.level, "Alto");
});
