import assert from "node:assert/strict";
import { test } from "node:test";
import type { Agent, AgentExecution } from "./api.ts";
import { COST_PER_RUN, ROLE_DESCRIPTIONS } from "./demo/agents.ts";
import { AGENT_STATUSES, presentActivity } from "./agent-status.ts";
import {
  activityFeed,
  agentCards,
  costByAgent,
  filterCards,
  fleetAlerts,
  fleetKpis,
  groupCards,
  sortCards,
  usageByDay,
  versionHistory,
} from "./agents-view.ts";

const NOW = Date.parse("2026-09-22T12:00:00Z");
const DAY = 86_400_000;

const AGENTS: Agent[] = [
  { id: "a-product", name: "Product Hunter", role: "product", capabilities: ["market_validation"], status: "BUSY", reliability_score: 1, version: "1.8.3", cost_profile: { simulated_cost_per_task: 0 } },
  { id: "a-supplier", name: "Supplier Finder", role: "supplier", capabilities: ["supplier_sourcing"], status: "AVAILABLE", reliability_score: 0.9, version: "1.9.1", cost_profile: {} },
  { id: "a-legal", name: "Product Compliance", role: "legal", capabilities: ["legal_validation"], status: "AVAILABLE", reliability_score: 0.95, version: "1.7.2", cost_profile: {} },
  { id: "a-unknown", name: "Sandbox Agent", role: "sandbox", capabilities: [], status: "DISABLED", reliability_score: 0.5, version: "0.1.0", cost_profile: {} },
];

const execution = (id: string, agent: string, success: boolean, duration: number, at: number): AgentExecution => ({
  id,
  agent_id: agent,
  capability: "run",
  duration_ms: duration,
  success,
  correlation_id: `c-${id}`,
  created_at: new Date(at).toISOString(),
});

const EXECUTIONS: AgentExecution[] = [
  execution("e1", "a-product", true, 6200, NOW - 3600_000),
  execution("e2", "a-product", true, 5800, NOW - 2 * 3600_000),
  execution("e3", "a-product", false, 15_000, NOW - 3 * 3600_000),
  execution("e4", "a-supplier", true, 11_800, NOW - DAY - 3600_000),
  execution("e5", "a-legal", true, 2200, NOW - 30 * 60_000),
  execution("e6", "a-legal", true, 2400, NOW - 2 * DAY),
];

const CARDS = agentCards(AGENTS, EXECUTIONS, NOW);

test("agentCards: lo medible sale de las ejecuciones y el resto de la demostración", () => {
  assert.equal(CARDS.length, AGENTS.length);
  const product = CARDS.find((c) => c.id === "a-product")!;
  assert.equal(product.team, "Investigación");
  assert.equal(product.description, ROLE_DESCRIPTIONS.product);
  assert.equal(product.runs, 3);
  assert.ok(Math.abs(product.successRate! - 2 / 3) < 1e-9);
  assert.equal(product.avgLatencyMs, (6200 + 5800 + 15_000) / 3);
  assert.equal(product.version, "1.8.3");
  assert.equal(product.activity, "running");
  assert.equal(presentActivity(product.activity).label, "Ejecutando");
  assert.ok(product.currentTask && product.taskProgress! > 0);
  // Las tres ejecuciones son de hoy: coste = ejecuciones × coste del equipo.
  assert.equal(product.runsToday, 3);
  assert.equal(product.costToday, Math.round(3 * COST_PER_RUN["Investigación"] * 100) / 100);

  const supplier = CARDS.find((c) => c.id === "a-supplier")!;
  assert.equal(supplier.activity, "available");
  assert.equal(supplier.currentTask, null);
  assert.equal(supplier.runsToday, 0, "su ejecución es de ayer");
  assert.equal(supplier.costToday, 0);

  const unknown = CARDS.find((c) => c.id === "a-unknown")!;
  assert.equal(unknown.team, "Otros");
  assert.equal(unknown.successRate, null);
  assert.equal(unknown.avgLatencyMs, null);
  assert.equal(unknown.lastActivityAt, null);
  assert.deepEqual(agentCards(AGENTS, EXECUTIONS, NOW), CARDS, "determinista");
});

test("fleetKpis: cuenta estados, éxito ponderado, coste del día y alertas", () => {
  const alerts = fleetAlerts(CARDS);
  const kpis = fleetKpis(CARDS, alerts);
  assert.equal(kpis.registered, 4);
  assert.equal(kpis.running, 1);
  assert.equal(kpis.available, 2);
  // 5 de 6 ejecuciones con éxito.
  assert.ok(Math.abs(kpis.successRate! - 5 / 6) < 1e-9);
  assert.equal(kpis.costToday, Math.round(CARDS.reduce((sum, c) => sum + c.costToday, 0) * 100) / 100);
  assert.equal(kpis.alerts, alerts.length);
  assert.equal(kpis.criticalAlerts, alerts.filter((a) => a.level === "Alta").length);
  assert.equal(fleetKpis(agentCards(AGENTS, [], NOW), []).successRate, null);
});

test("usageByDay: un punto por día con ejecuciones y coste", () => {
  const points = usageByDay(AGENTS, EXECUTIONS, 7, NOW);
  assert.equal(points.length, 7);
  assert.equal(points.at(-1)!.offset, 0);
  assert.equal(points.at(-1)!.runs, 4, "hoy: tres del product y una del legal");
  assert.equal(points.at(-2)!.runs, 1);
  assert.ok(points.at(-1)!.cost > 0);
  assert.equal(usageByDay(AGENTS, [], 7, NOW).reduce((sum, p) => sum + p.runs, 0), 0);
});

test("costByAgent: solo agentes con coste hoy, de mayor a menor", () => {
  const rows = costByAgent(CARDS);
  assert.ok(rows.length > 0 && rows.every((r) => r.value > 0));
  for (let k = 1; k < rows.length; k++) assert.ok(rows[k - 1].value >= rows[k].value);
  assert.equal(rows[0].label, "Product Hunter");
});

test("fleetAlerts: error, latencia y coste desviado, con las críticas primero", () => {
  const alerts = fleetAlerts(CARDS);
  assert.ok(alerts.some((a) => a.key === "a-product-error" && a.level === "Alta"));
  assert.ok(alerts.every((a) => a.message.length > 5));
  for (let k = 1; k < alerts.length; k++) {
    if (alerts[k - 1].level === "Media") assert.equal(alerts[k].level, "Media");
  }
  assert.deepEqual(fleetAlerts(agentCards(AGENTS, [], NOW)), []);
});

test("activityFeed: las ejecuciones más recientes con su agente y equipo", () => {
  const feed = activityFeed(AGENTS, EXECUTIONS, 3);
  assert.equal(feed.length, 3);
  for (let k = 1; k < feed.length; k++) assert.ok(feed[k - 1].at >= feed[k].at);
  assert.equal(feed[0].agent, "Product Compliance");
  assert.equal(feed[0].team, "Legal");
  assert.equal(activityFeed([], EXECUTIONS, 2)[0].agent, "a-legal", "sin registro, el id");
});

test("versionHistory: la versión real primero y las anteriores de demostración", () => {
  const product = CARDS.find((c) => c.id === "a-product")!;
  const rows = versionHistory(product, 3);
  assert.equal(rows.length, 3);
  assert.deepEqual(rows.map((r) => r.version), ["1.8.3", "1.8.2", "1.8.1"]);
  assert.equal(rows[0].current, true);
  assert.ok(rows.slice(1).every((r) => !r.current && r.note.length > 5));
  const zero = versionHistory({ ...product, version: "2.0.0" }, 3);
  assert.deepEqual(zero.map((r) => r.version), ["2.0.0", "1.9.9", "1.9.8"]);
});

test("filterCards, sortCards y groupCards: filtros, orden y equipos", () => {
  assert.equal(filterCards(CARDS, { team: "Legal" }).length, 1);
  assert.equal(filterCards(CARDS, { query: "supplier" }).length, 1, "busca por nombre o capacidad");
  assert.equal(filterCards(CARDS, { team: "all", query: "" }).length, CARDS.length);

  assert.deepEqual(sortCards(CARDS, "name").map((c) => c.name)[0], "Product Compliance");
  assert.equal(sortCards(CARDS, "cost")[0].id, "a-product");
  assert.equal(sortCards(CARDS, "runs")[0].id, "a-product");
  assert.equal(sortCards(CARDS, "success")[0].successRate, 1);

  const groups = groupCards(CARDS);
  assert.deepEqual(groups.map((g) => g.team), ["Investigación", "Abastecimiento", "Legal", "Otros"]);
  assert.equal(groups.reduce((sum, g) => sum + g.agents.length, 0), CARDS.length);
});

// --- M47 · Commit 1b: el estado del registro, tal cual -----------------------------------------------------------------

const withStatus = (status: string): Agent => ({
  id: `a-${status}`,
  name: `Agente ${status}`,
  role: "product",
  capabilities: [],
  status,
  reliability_score: 1,
  version: "1.0.0",
  cost_profile: {},
});

test("agentCards: cada estado del backend se ve como lo que es, y solo AVAILABLE es «Disponible»", () => {
  const expected: Record<string, [string, string]> = {
    AVAILABLE: ["available", "Disponible"],
    BUSY: ["running", "Ejecutando"],
    WAITING: ["waiting", "En espera"],
    BLOCKED: ["blocked", "Bloqueado"],
    DEGRADED: ["degraded", "Degradado"],
    DISABLED: ["disabled", "Deshabilitado"],
    FAILED: ["failed", "Fallido"],
  };
  assert.deepEqual(Object.keys(expected).sort(), [...AGENT_STATUSES].sort(), "la prueba cubre los siete estados del backend");
  for (const [status, [activity, label]] of Object.entries(expected)) {
    const card = agentCards([withStatus(status)], [], NOW)[0];
    assert.equal(card.activity, activity, status);
    assert.equal(presentActivity(card.activity).label, label, status);
    assert.equal(card.activity === "available", status === "AVAILABLE", `${status} no puede aparecer como «Disponible»`);
  }
});

test("agentCards: un estado que el backend no envía es «Desconocido», jamás «Disponible»", () => {
  for (const raw of ["OFFLINE", "ERROR", "ONLINE", "available", ""]) {
    const card = agentCards([withStatus(raw)], [], NOW)[0];
    assert.equal(card.activity, "unknown", raw);
    assert.equal(presentActivity(card.activity).label, "Desconocido");
    assert.equal(card.registry.kind, "unknown");
  }
});

test("fleetKpis: «Disponibles» solo cuenta AVAILABLE; «Ejecutando» solo BUSY", () => {
  const cards = agentCards(["AVAILABLE", "BUSY", "WAITING", "BLOCKED", "DEGRADED", "DISABLED", "FAILED", "OFFLINE"].map(withStatus), [], NOW);
  const kpis = fleetKpis(cards, fleetAlerts(cards));
  assert.equal(kpis.registered, 8);
  assert.equal(kpis.available, 1);
  assert.equal(kpis.running, 1);
});

test("fleetAlerts: FAILED y BLOCKED = Alta, DEGRADED = Media; DISABLED, AVAILABLE, BUSY, WAITING y desconocido, ninguna", () => {
  const level = (status: string) => fleetAlerts(agentCards([withStatus(status)], [], NOW)).map((alert) => alert.level);
  assert.deepEqual(level("FAILED"), ["Alta"]);
  assert.deepEqual(level("BLOCKED"), ["Alta"]);
  assert.deepEqual(level("DEGRADED"), ["Media"]);
  for (const quiet of ["DISABLED", "AVAILABLE", "BUSY", "WAITING", "OFFLINE", "ERROR"]) assert.deepEqual(level(quiet), [], quiet);
  const [failed] = fleetAlerts(agentCards([withStatus("FAILED")], [], NOW));
  assert.equal(failed.message, "Estado del registro: Fallido");
  assert.equal(failed.agent, "Agente FAILED");
});

test("fleetAlerts: con los siete estados salen exactamente tres alertas y las Altas van primero", () => {
  const cards = agentCards(AGENT_STATUSES.map(withStatus), [], NOW);
  const alerts = fleetAlerts(cards);
  assert.deepEqual(alerts.map((alert) => `${alert.level}:${alert.message}`), [
    "Alta:Estado del registro: Bloqueado",
    "Alta:Estado del registro: Fallido",
    "Media:Estado del registro: Degradado",
  ]);
  assert.equal(fleetKpis(cards, alerts).criticalAlerts, 2);
});

test("fleetAlerts: la alerta del estado convive con las de ejecuciones y no las sustituye", () => {
  const agents = [{ ...withStatus("DEGRADED"), id: "a-deg" }];
  const runs = [execution("x1", "a-deg", false, 1000, NOW - 3600_000), execution("x2", "a-deg", false, 1000, NOW - 7200_000)];
  const alerts = fleetAlerts(agentCards(agents, runs, NOW));
  assert.ok(alerts.some((alert) => alert.message === "Estado del registro: Degradado"));
  assert.ok(alerts.some((alert) => alert.message.startsWith("Tasa de error")));
});

test("fleetAlerts: las alertas del estado del registro van antes que las de ejecuciones dentro de su nivel (no quedan ocultas tras el tope de la tarjeta)", () => {
  // Siete agentes sanos con una latencia alta (alertas Media de ejecuciones, que por nombre irían antes) y uno DEGRADED.
  const healthy = Array.from({ length: 7 }, (_, index) => ({ ...withStatus("AVAILABLE"), id: `h${index}`, name: `A${index} Sano` }));
  const slow = healthy.map((agent) => execution(`s-${agent.id}`, agent.id, true, 60_000, NOW - 3600_000));
  const degraded = { ...withStatus("DEGRADED"), id: "z-deg", name: "Zeta Degradado" };
  const alerts = fleetAlerts(agentCards([...healthy, degraded], slow, NOW));
  assert.ok(alerts.filter((alert) => alert.message.startsWith("Latencia")).length >= 5, "hay al menos cinco alertas de latencia");
  assert.equal(alerts[0].message, "Estado del registro: Degradado", "la del estado va primera dentro de Media");
});
