import assert from "node:assert/strict";
import { test } from "node:test";
import type { Agent, AgentExecution, Incident } from "./api.ts";
import { DEMO_INCIDENTS, DEMO_SERVICES, HOUR_MS } from "./demo/status.ts";
import {
  costLines,
  costTotal,
  cronRows,
  healthScores,
  hourlySeries,
  incidentsView,
  integrationRows,
  migrationView,
  overallHealth,
  runtimeView,
  serviceRows,
  serviceSummary,
  statusKpis,
} from "./status-view.ts";
import type { HealthSignal, WorkerSignal } from "./status.ts";

const DAY_MS = 86_400_000;
const NOW = Date.UTC(2026, 8, 23, 14, 37, 0);

const signal = (over: Partial<HealthSignal> = {}): HealthSignal => ({
  apiReachable: true,
  latencyMs: 42,
  health: { database: "ok", supabase_configured: true },
  ...over,
});

const workers = (over: Partial<WorkerSignal> = {}): WorkerSignal => ({
  runs: 100,
  failures: 1,
  avgDurationMs: 118,
  ...over,
});

const agent = (id: string, role: string, status: string): Agent => ({
  id,
  name: id,
  role,
  capabilities: ["run"],
  status,
  reliability_score: 0.9,
  version: "1.0.0",
  cost_profile: {},
});

const execution = (id: string, agentId: string, at: number, success = true): AgentExecution => ({
  id,
  agent_id: agentId,
  capability: "run",
  duration_ms: 1000,
  success,
  correlation_id: id,
  created_at: new Date(at).toISOString(),
});

// --- Servicios ----------------------------------------------------------------------

test("serviceRows: los 18 servicios del mockup; solo seis llevan estado real", () => {
  const rows = serviceRows(signal(), workers());
  assert.equal(rows.length, 18);
  assert.deepEqual(rows.map((r) => r.id), DEMO_SERVICES.map((s) => s.id));
  assert.deepEqual(
    rows.filter((r) => !r.isDemo).map((r) => r.id),
    ["frontend", "api", "postgres", "auth", "storage", "workers"],
  );
  // La latencia medida solo existe donde se mide de verdad.
  assert.equal(rows.find((r) => r.id === "api")?.measuredMs, 42);
  assert.equal(rows.find((r) => r.id === "workers")?.measuredMs, 118);
  assert.equal(rows.find((r) => r.id === "cdn")?.measuredMs, null);
  // Uptime y p95 son siempre de demostración, también en los servicios reales.
  assert.equal(rows.find((r) => r.id === "api")?.p95Ms, 182);
  assert.equal(rows.find((r) => r.id === "backup")?.p95Ms, null);
  assert.equal(rows.find((r) => r.id === "backup")?.trend.length, 0);
});

test("serviceRows: el backend caído tumba la API y deja sin señal a Postgres y Supabase", () => {
  const rows = serviceRows(signal({ apiReachable: false, latencyMs: null }), workers({ runs: 0, failures: 0, avgDurationMs: null }));
  const state = (id: string) => rows.find((r) => r.id === id)?.state;
  assert.equal(state("api"), "down");
  assert.equal(state("postgres"), "no_signal");
  assert.equal(state("auth"), "no_signal");
  assert.equal(state("storage"), "no_signal");
  assert.equal(state("workers"), "no_signal");
  assert.equal(state("frontend"), "operational");
  // Los servicios de demostración no fingen enterarse de la caída.
  assert.equal(state("cdn"), "operational");
});

test("serviceRows: la base de datos con error cae y Supabase sin configurar se queda sin señal", () => {
  const rows = serviceRows(signal({ health: { database: "error", supabase_configured: false } }), workers());
  assert.equal(rows.find((r) => r.id === "postgres")?.state, "down");
  assert.equal(rows.find((r) => r.id === "auth")?.state, "no_signal");
});

test("serviceSummary cuenta operativos, caídos, sin señal y con señal real", () => {
  assert.deepEqual(serviceSummary(serviceRows(signal(), workers())), {
    operational: 18,
    down: 0,
    noSignal: 0,
    total: 18,
    withRealSignal: 6,
  });
  const broken = serviceSummary(serviceRows(signal({ apiReachable: false, latencyMs: null }), workers({ runs: 0, failures: 0, avgDurationMs: null })));
  assert.equal(broken.down, 1);
  assert.equal(broken.noSignal, 4);
  assert.equal(broken.operational, 13);
});

// --- KPIs ---------------------------------------------------------------------------

test("statusKpis: servicios e incidentes salen de las filas y de la vista de incidentes", () => {
  const rows = serviceRows(signal(), workers());
  const runtime = runtimeView([], [], NOW);
  const incidents = incidentsView([], NOW);
  const kpis = statusKpis(rows, runtime, incidents, NOW);
  assert.equal(kpis.servicesOperational, 18);
  assert.equal(kpis.servicesTotal, 18);
  assert.equal(kpis.openIncidents, 0);
  assert.equal(kpis.queuedJobs, runtime.pendingJobs);
  assert.ok(kpis.uptime > 0.999 && kpis.uptime < 1);
  assert.equal(kpis.deployVersion, "v0.8.42");
  assert.equal(kpis.deployAt, NOW - 2 * HOUR_MS);
});

test("statusKpis: sin respuesta del backend los incidentes quedan en null, no en cero", () => {
  const kpis = statusKpis(serviceRows(signal(), workers()), runtimeView([], [], NOW), incidentsView(null, NOW), NOW);
  assert.equal(kpis.openIncidents, null);
  assert.equal(kpis.incidents30d, null);
});

// --- System Health ------------------------------------------------------------------

test("healthScores: las cinco primeras son reales y la de workers sale de la tasa de éxito", () => {
  const scores = healthScores(signal(), workers({ runs: 200, failures: 4 }));
  assert.deepEqual(scores.filter((s) => !s.isDemo).map((s) => s.key), ["api", "database", "auth", "storage", "workers"]);
  assert.equal(scores.find((s) => s.key === "api")?.score, 100);
  assert.equal(scores.find((s) => s.key === "workers")?.score, 98);
  assert.equal(scores.find((s) => s.key === "security")?.isDemo, true);
});

test("healthScores: lo que no tiene señal puntúa null y no entra en la media", () => {
  const scores = healthScores(signal({ health: { database: "ok", supabase_configured: false } }), workers({ runs: 0, failures: 0, avgDurationMs: null }));
  assert.equal(scores.find((s) => s.key === "auth")?.score, null);
  assert.equal(scores.find((s) => s.key === "workers")?.score, null);
  const known = scores.filter((s) => s.score !== null);
  assert.equal(known.length, 6);
  assert.equal(overallHealth(scores), Math.round(known.reduce((sum, s) => sum + (s.score ?? 0), 0) / known.length));
  assert.equal(overallHealth([{ key: "x", label: "X", score: null, isDemo: false }]), null);
});

test("healthScores: la base de datos caída puntúa 0", () => {
  const scores = healthScores(signal({ health: { database: "error", supabase_configured: true } }), workers());
  assert.equal(scores.find((s) => s.key === "database")?.score, 0);
});

// --- Agent Runtime ------------------------------------------------------------------

test("runtimeView: workers reales, colas de demostración y fallos de hoy reales", () => {
  const agents = [agent("a1", "research", "BUSY"), agent("a2", "legal", "AVAILABLE"), agent("a3", "cfo", "OFFLINE")];
  const runs = [
    execution("e1", "a1", NOW - HOUR_MS, false),
    execution("e2", "a1", NOW - 2 * HOUR_MS),
    // De ayer: no cuenta como fallo de hoy.
    execution("e3", "a2", NOW - 2 * DAY_MS, false),
  ];
  const view = runtimeView(agents, runs, NOW);
  assert.equal(view.workersActive, 2);
  assert.equal(view.workersBusy, 1);
  assert.equal(view.workersTotal, 10);
  assert.equal(view.busyRatio, 0.5);
  assert.equal(view.failedJobs, 1);
  assert.equal(view.queues.length, 5);
  assert.equal(view.pendingJobs, view.queues.reduce((sum, q) => sum + q.depth, 0));
  assert.ok(view.queues.every((q) => q.depth >= 0));
});

test("runtimeView: las colas son deterministas dentro de la misma hora", () => {
  const first = runtimeView([], [], NOW);
  const same = runtimeView([], [], NOW + 60_000);
  assert.deepEqual(first.queues, same.queues);
  // A lo largo del día la profundidad se mueve: alguna hora tiene que diferir.
  const later = Array.from({ length: 12 }, (_, k) => runtimeView([], [], NOW + (k + 1) * HOUR_MS).pendingJobs);
  assert.ok(later.some((pending) => pending !== first.pendingJobs));
});

// --- Métricas principales -----------------------------------------------------------

test("hourlySeries: 24 puntos consecutivos que acaban en la hora en curso", () => {
  const points = hourlySeries("latency", NOW);
  assert.equal(points.length, 24);
  assert.deepEqual(points.map((p) => p.x), Array.from({ length: 24 }, (_, k) => k));
  assert.equal(points[23].hour, new Date(NOW).getUTCHours());
  assert.equal(points[0].hour, new Date(NOW - 23 * HOUR_MS).getUTCHours());
  assert.ok(points.every((p) => p.value > 100 && p.value < 250));
});

test("hourlySeries: cada métrica tiene su escala y repite el mismo valor en la misma hora", () => {
  assert.ok(hourlySeries("requests", NOW).every((p) => p.value > 1000 && p.value < 3000));
  assert.ok(hourlySeries("errors", NOW).every((p) => p.value >= 0 && p.value < 0.01));
  assert.deepEqual(hourlySeries("latency", NOW), hourlySeries("latency", NOW + 60_000));
});

// --- Integraciones, cron, migraciones y despliegues ---------------------------------

test("integrationRows: las siete integraciones del mockup, todas operativas", () => {
  const rows = integrationRows();
  assert.equal(rows.length, 7);
  assert.ok(rows.every((row) => row.state === "operational" && row.latencyMs > 0));
});

test("cronRows: una tarea ejecutándose, las demás con su última ejecución y la nocturna a su hora", () => {
  const rows = cronRows(NOW);
  const running = rows.filter((row) => row.running);
  assert.equal(running.length, 1);
  assert.equal(running[0].id, "competitor");
  assert.equal(running[0].lastRunAt, null);
  assert.equal(rows.find((row) => row.id === "markets")?.lastRunAt, NOW - 12 * 60_000);
  const backup = rows.find((row) => row.id === "backup")!;
  assert.equal(new Date(backup.lastRunAt!).getUTCHours(), 4);
  assert.ok(backup.lastRunAt! <= NOW);
});

test("cronRows: la tarea nocturna cae en el día anterior si todavía no ha llegado su hora", () => {
  const earlyMorning = Date.UTC(2026, 8, 23, 2, 0, 0);
  const backup = cronRows(earlyMorning).find((row) => row.id === "backup")!;
  assert.ok(backup.lastRunAt! < earlyMorning);
  assert.equal(new Date(backup.lastRunAt!).getUTCDate(), 22);
});

test("migrationView usa la migración real cuando existe y la de demostración si no", () => {
  const real = migrationView("202609171142_add_agent_metrics", NOW);
  assert.equal(real.currentIsReal, true);
  assert.equal(real.current, "202609171142_add_agent_metrics");
  assert.equal(migrationView(null, NOW).currentIsReal, false);
  assert.equal(real.pending, 0);
  assert.equal(real.failed, 0);
});

// --- Costes -------------------------------------------------------------------------

test("costLines: la inferencia de IA usa las ejecuciones de hoy y el coste por equipo de Agentes", () => {
  const agents = [agent("a1", "research", "AVAILABLE"), agent("a2", "marketing", "AVAILABLE")];
  const runs = [
    execution("e1", "a1", NOW - HOUR_MS),
    execution("e2", "a1", NOW - 2 * HOUR_MS),
    execution("e3", "a2", NOW - HOUR_MS),
    // De ayer: fuera del coste de hoy.
    execution("e4", "a2", NOW - DAY_MS - HOUR_MS),
  ];
  const lines = costLines(agents, runs, NOW);
  // Investigación 0,09 × 2 + Marketing 0,11 = 0,29
  assert.equal(lines[0].amount, 0.29);
  assert.equal(lines[0].isEstimate, true);
  assert.equal(lines.length, 5);
  assert.ok(lines.slice(1).every((line) => !line.isEstimate));
  assert.equal(costTotal(lines), 4.94);
});

test("costLines: sin ejecuciones, la inferencia de IA es cero y no se inventa", () => {
  assert.equal(costLines([], [], NOW)[0].amount, 0);
});

// --- Incidentes ---------------------------------------------------------------------

const incident = (id: string, status: "OPEN" | "RESOLVED", at: number, resolvedAt: number | null): Incident => ({
  id,
  title: `Incidente ${id}`,
  description: null,
  severity: "MEDIUM",
  status,
  resolved_at: resolvedAt === null ? null : new Date(resolvedAt).toISOString(),
  created_at: new Date(at).toISOString(),
});

test("incidentsView: con incidentes reales no aparece ninguno de demostración", () => {
  const view = incidentsView(
    [
      incident("0001", "RESOLVED", NOW - 3 * DAY_MS, NOW - 3 * DAY_MS + 600_000),
      incident("0002", "OPEN", NOW - DAY_MS, null),
      // Fuera de la ventana de 30 días.
      incident("0003", "RESOLVED", NOW - 40 * DAY_MS, NOW - 40 * DAY_MS + 60_000),
    ],
    NOW,
  );
  assert.equal(view.usingDemo, false);
  assert.equal(view.rows.length, 2);
  assert.equal(view.total30d, 2);
  // El abierto de ayer va primero: se ordena por fecha descendente.
  assert.equal(view.rows[0].open, true);
  assert.equal(view.rows[0].resolvedInMinutes, null);
  assert.equal(view.rows[1].resolvedInMinutes, 10);
  assert.equal(view.rows[1].code, "INC-0001");
  // El abierto cuenta aunque el de hace 40 días quede fuera de la lista.
  assert.equal(view.open, 1);
});

test("incidentsView: con la lista real vacía enseña los de demostración y lo declara", () => {
  const view = incidentsView([], NOW);
  assert.equal(view.usingDemo, true);
  assert.equal(view.open, 0);
  assert.equal(view.total30d, 0);
  assert.deepEqual(view.rows.map((row) => row.code), DEMO_INCIDENTS.map((row) => row.code));
  assert.ok(view.rows.every((row) => row.isDemo && !row.open));
});

test("incidentsView: si el backend no respondió no hay filas ni ceros", () => {
  const view = incidentsView(null, NOW);
  assert.equal(view.reachable, false);
  assert.equal(view.open, null);
  assert.equal(view.total30d, null);
  assert.equal(view.rows.length, 0);
});
