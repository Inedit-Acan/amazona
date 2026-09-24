import assert from "node:assert/strict";
import { test } from "node:test";
import type { Agent } from "./api.ts";
import type { AgentCardView } from "./agents-view.ts";
import type { ApprovalRequest } from "./approvals-view.ts";
import type { Pnl } from "./cfo-view.ts";
import type { Order } from "./operations-view.ts";
import type { ResearchRow } from "./research-view.ts";
import {
  activityRows,
  dashboardKpis,
  decisionRows,
  opportunityRows,
  opportunityStage,
  salesSeries,
  type ProductDepth,
} from "./dashboard-view.ts";

const DAY_MS = 86_400_000;
const TODAY = "2026-09-23";
const TODAY_MS = Date.UTC(2026, 8, 23);

const pnl = (over: Partial<Pnl> = {}): Pnl =>
  ({
    rows: [],
    revenue: 47_320,
    cogs: 23_660,
    grossMargin: 23_660,
    grossMarginPct: 0.5,
    operatingCosts: 9_000,
    ebitda: 14_660,
    ebitdaPct: 0.31,
    tax: 1_820,
    net: 12_840,
    netMarginPct: 0.27,
    spend: 34_480,
    costByCategory: {},
    ...over,
  }) as Pnl;

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

const researchRow = (over: Partial<ResearchRow> = {}): ResearchRow =>
  ({
    productId: "p1",
    name: "AirPure X2",
    category: "electronics",
    categoryLabel: "Electrónica",
    subcategory: "Purificador de aire",
    score: 82,
    demand: "Alta",
    competition: "Media",
    growth: 0.1,
    trend: [1, 2],
    margin: [24, 32],
    risk: "Bajo",
    insights: [],
    rationale: "",
    radar: {} as ResearchRow["radar"],
    isDemo: true,
    ...over,
  }) as ResearchRow;

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

const order = (id: string, at: number, amount: number): Order =>
  ({ id, createdAt: at, amount, productId: "p1", status: "delivered" }) as Order;

// --- KPIs ---------------------------------------------------------------------------

test("dashboardKpis: ventas y beneficio salen del P&L y sus variaciones del mes anterior", () => {
  const kpis = dashboardKpis({
    pnl: pnl(),
    previousPnl: pnl({ revenue: 43_734, net: 11_424 }),
    agents: [agent("a1", "AVAILABLE"), agent("a2", "BUSY"), agent("a3", "OFFLINE")],
    requests: [request(), request({ id: "r2", isDemo: false }), request({ id: "r3", status: "APPROVED" })],
  });
  assert.equal(kpis.sales, 47_320);
  assert.equal(kpis.profit, 12_840);
  assert.ok(Math.abs((kpis.salesDelta ?? 0) - 0.082) < 0.001);
  assert.ok(Math.abs((kpis.profitDelta ?? 0) - 0.124) < 0.001);
  assert.equal(kpis.agentsOnline, 2);
  assert.equal(kpis.agentsTotal, 3);
  // Solo las pendientes cuentan, y se distingue cuántas son reales.
  assert.equal(kpis.pendingDecisions, 2);
  assert.equal(kpis.realDecisions, 1);
});

test("dashboardKpis: sin mes anterior no se inventa una variación", () => {
  const kpis = dashboardKpis({ pnl: pnl(), previousPnl: pnl({ revenue: 0, net: 0 }), agents: [], requests: [] });
  assert.equal(kpis.salesDelta, null);
  assert.equal(kpis.profitDelta, null);
  assert.equal(kpis.agentsRatio, 0);
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

test("opportunityRows: usa el margen del modelo económico y el de Investigación si no lo hay", () => {
  const rows = opportunityRows(
    [
      researchRow(),
      researchRow({ productId: "p2", name: "EcoBottle", score: 74 }),
      researchRow({ productId: "p3", name: "SolarCharge", score: 70 }),
    ],
    [
      depth({ marginPct: 0.31, marginIsReal: true, economics: 1, quotes: 1 }),
      // Tiene modelo, pero sobre supuestos de demostración: no es margen real.
      depth({ productId: "p2", marginPct: 0.19 }),
      depth({ productId: "p3" }),
    ],
    5,
  );
  assert.equal(rows[0].marginPct, 0.31);
  assert.equal(rows[0].marginIsReal, true);
  assert.equal(rows[0].stage, "Análisis");
  assert.equal(rows[1].marginPct, 0.19);
  assert.equal(rows[1].marginIsReal, false);
  // Sin modelo, el punto medio del rango 24–32 % de Investigación.
  assert.equal(rows[2].marginPct, 0.28);
  assert.equal(rows[2].marginIsReal, false);
  assert.equal(rows[2].stage, "En observación");
});

test("opportunityRows respeta el orden y el tope de Investigación", () => {
  const rows = opportunityRows([researchRow(), researchRow({ productId: "p2", score: 74 }), researchRow({ productId: "p3", score: 60 })], [], 2);
  assert.deepEqual(rows.map((row) => row.productId), ["p1", "p2"]);
  assert.ok(rows.every((row) => row.stage === "En observación"));
});

// --- Serie de ventas ----------------------------------------------------------------

test("salesSeries: a 30 días la gráfica suma exactamente los ingresos del P&L", () => {
  const orders = Array.from({ length: 30 }, (_, k) => order(`o${k}`, TODAY_MS - k * DAY_MS, 100 + k));
  const points = salesSeries(orders, pnl({ revenue: 3_000 }), TODAY, 30);
  assert.equal(points.length, 30);
  assert.ok(Math.abs(points.reduce((sum, p) => sum + p.sales, 0) - 3_000) < 0.5);
});

test("salesSeries: la forma la ponen los pedidos y el nivel la parte del mes que cubre la ventana", () => {
  const orders = [
    order("o1", TODAY_MS, 500),
    order("o2", TODAY_MS, 300),
    order("o3", TODAY_MS - 2 * DAY_MS, 200),
    // Fuera de la ventana: no entra en el reparto.
    order("o4", TODAY_MS - 10 * DAY_MS, 999),
  ];
  // 5 días de un mes de 6.000 € → 1.000 € repartidos 20 % / 80 %.
  const points = salesSeries(orders, pnl({ revenue: 6_000, cogs: 3_000, operatingCosts: 600 }), TODAY, 5);
  assert.equal(points.length, 5);
  assert.deepEqual(points.map((p) => p.sales), [0, 0, 200, 0, 800]);
  assert.equal(points[4].at, TODAY_MS);
  // Un día sin ventas no tiene margen negativo inventado.
  assert.equal(points[0].marginPct, 0);
});

test("salesSeries: sin pedidos en la ventana, el periodo se reparte a partes iguales", () => {
  const points = salesSeries([], pnl({ revenue: 9_000 }), TODAY, 3);
  // 3 días de un mes de 9.000 € → 900 € en tres partes.
  assert.deepEqual(points.map((p) => p.sales), [300, 300, 300]);
});

test("salesSeries: el margen sube con el volumen porque los costes operativos son fijos", () => {
  const points = salesSeries(
    [order("o1", TODAY_MS - DAY_MS, 1_000), order("o2", TODAY_MS, 4_000)],
    // Mes de 37.500 € → 2 días valen 2.500 €, repartidos 20 % / 80 %.
    pnl({ revenue: 37_500, cogs: 18_750, operatingCosts: 6_000 }),
    TODAY,
    2,
  );
  const [low, high] = points;
  assert.deepEqual([low.sales, high.sales], [500, 2_000]);
  assert.ok(high.marginPct > low.marginPct);
  // 1 − 0,5 de coste variable − 200 fijos al día entre 500 de ventas → 10 %.
  assert.ok(Math.abs(low.marginPct - 0.1) < 1e-9);
  assert.ok(Math.abs(high.marginPct - 0.4) < 1e-9);
});
