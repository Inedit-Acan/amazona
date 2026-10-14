import assert from "node:assert/strict";
import { test } from "node:test";
import type { Agent } from "./api.ts";
import type { AgentCardView } from "./agents-view.ts";
import type { ApprovalRequest } from "./approvals-view.ts";
import {
  activityRows,
  dashboardKpis,
  decisionRows,
  opportunityStage,
  type ProductDepth,
} from "./dashboard-view.ts";

const DAY_MS = 86_400_000;
const TODAY_MS = Date.UTC(2026, 8, 23);

const agent = (id: string, status: string): Pick<Agent, "status"> & { id: string } => ({ id, status });

const request = (over: Partial<ApprovalRequest> = {}): ApprovalRequest =>
  ({
    id: "r1",
    code: "APR-0001",
    kind: "suppliers",
    kindLabel: "Abastecimiento",
    title: "Nuevo proveedor",
    severity: "Alta",
    projectCode: "AMZ-0001",
    productName: "AirPure X2",
    requestedBy: "Supplier Agent",
    amount: 1000,
    amountLabel: "Volumen inicial",
    requestedAt: TODAY_MS - 3_600_000,
    expiresAt: TODAY_MS + 3_600_000,
    status: "PENDING",
    fields: [],
    validations: [],
    opinions: [],
    findings: [],
    risks: [],
    approveImpact: ["Aprueba el alta del proveedor"],
    rejectImpact: [],
    budget: null,
    source: "demo",
    isDemo: true,
    ...over,
  }) as ApprovalRequest;

const card = (over: Partial<AgentCardView> = {}): AgentCardView =>
  ({
    id: "a1",
    name: "Product Hunter",
    role: "product",
    team: "Investigación",
    description: "",
    activity: "available",
    registry: { kind: "known", status: "AVAILABLE" },
    capabilities: [],
    version: "1.0.0",
    successRate: 0.98,
    evalScore: 90,
    avgLatencyMs: 1000,
    runs: 10,
    runsToday: 2,
    costToday: 0.2,
    lastActivityAt: TODAY_MS,
    currentTask: null,
    taskProgress: null,
    tools: [],
    ...over,
  }) as AgentCardView;

const depth = (over: Partial<ProductDepth> = {}): ProductDepth => ({
  productId: "p1",
  quotes: 0,
  economics: 0,
  legal: 0,
  storefronts: 0,
  campaigns: 0,
  marginPct: null,
  marginIsReal: false,
  ...over,
});

// --- KPIs ---------------------------------------------------------------------------

test("dashboardKpis: solo cuenta agentes y decisiones; ya no lleva ventas ni beneficio modelados", () => {
  const kpis = dashboardKpis({
    agents: [agent("a1", "AVAILABLE"), agent("a2", "BUSY"), agent("a3", "DISABLED")],
    requests: [request(), request({ id: "r2", isDemo: false }), request({ id: "r3", status: "APPROVED" })],
  });
  assert.equal(kpis.agentsOperational, 2);
  assert.equal(kpis.agentsNotOperational, 1);
  assert.equal(kpis.agentsUnknown, 0);
  assert.equal(kpis.agentsTotal, 3);
  // Solo las pendientes cuentan, y se distingue cuántas son reales.
  assert.equal(kpis.pendingDecisions, 2);
  assert.equal(kpis.realDecisions, 1);
  // Los ingresos los da el registro (lib/revenue-view.ts): aquí no queda ninguna cifra económica inventada.
  assert.deepEqual(Object.keys(kpis).sort(), ["agentsNotOperational", "agentsOperational", "agentsTotal", "agentsUnknown", "pendingDecisions", "realDecisions"]);
});

test("dashboardKpis: sin agentes no hay cociente ni NaN: todo a cero", () => {
  const kpis = dashboardKpis({ agents: [], requests: [] });
  assert.equal(kpis.agentsTotal, 0);
  assert.equal(kpis.agentsOperational, 0);
  assert.equal(kpis.pendingDecisions, 0);
});

// --- Actividad ----------------------------------------------------------------------

test("activityRows: primero los que están ejecutando, luego por actividad más reciente", () => {
  const rows = activityRows(
    [
      card({ id: "a1", lastActivityAt: TODAY_MS - 10 * 60_000 }),
      card({ id: "a2", activity: "running", currentTask: "Comparando cotizaciones", lastActivityAt: TODAY_MS - DAY_MS }),
      card({ id: "a3", lastActivityAt: TODAY_MS }),
      card({ id: "a4", lastActivityAt: null, runs: 0, successRate: null }),
    ],
    3,
  );
  assert.deepEqual(rows.map((row) => row.id), ["a2", "a3", "a1"]);
  assert.equal(rows[0].currentTask, "Comparando cotizaciones");
  assert.equal(rows[1].currentTask, null);
  assert.equal(rows[0].state, "running");
});

// --- Decisiones ---------------------------------------------------------------------

test("decisionRows: solo pendientes, por severidad y luego por recientes", () => {
  const rows = decisionRows(
    [
      request({ id: "r1", severity: "Media", requestedAt: TODAY_MS }),
      request({ id: "r2", severity: "Crítica", requestedAt: TODAY_MS - DAY_MS }),
      request({ id: "r3", severity: "Alta", requestedAt: TODAY_MS - 60_000 }),
      request({ id: "r4", severity: "Crítica", requestedAt: TODAY_MS }),
      request({ id: "r5", severity: "Crítica", status: "APPROVED" }),
    ],
    4,
  );
  assert.deepEqual(rows.map((row) => row.id), ["r4", "r2", "r3", "r1"]);
  assert.equal(rows[0].detail, "Aprueba el alta del proveedor");
  assert.equal(rows[0].kindLabel, "Abastecimiento");
});

test("decisionRows: sin impacto ni hallazgos, el detalle no se queda vacío", () => {
  const rows = decisionRows([request({ approveImpact: [], findings: [], fields: [] })], 1);
  assert.equal(rows[0].detail, "Requiere tu decisión.");
});

// --- Oportunidades ------------------------------------------------------------------

test("opportunityStage sigue hasta dónde ha llegado de verdad el pipeline del producto", () => {
  assert.equal(opportunityStage(depth()), "En observación");
  assert.equal(opportunityStage(depth({ quotes: 2 })), "Evaluación");
  assert.equal(opportunityStage(depth({ quotes: 2, economics: 1 })), "Análisis");
  assert.equal(opportunityStage(depth({ quotes: 2, economics: 1, legal: 1 })), "Validación");
  assert.equal(opportunityStage(depth({ quotes: 2, economics: 1, legal: 1, storefronts: 1 })), "Lanzamiento");
  assert.equal(opportunityStage(depth({ campaigns: 1 })), "Lanzamiento");
});

// `opportunityRows` se sustituyó por `opportunitiesView` (M46, Commit 6): sus pruebas viven en `lib/dashboard-states.test.ts`.
