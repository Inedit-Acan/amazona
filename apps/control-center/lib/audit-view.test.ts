import assert from "node:assert/strict";
import { test } from "node:test";
import type { Agent, AuditEntry, Product } from "./api.ts";
import { EVENTS_PER_DAY, EVIDENCE_COMPLETE_RATE, WINDOW_DAYS } from "./demo/audit.ts";
import {
  actorActivity,
  anomalies,
  auditKpis,
  auditRows,
  correlationTrace,
  demoRows,
  detailFields,
  filterOptions,
  filterRows,
  paginate,
  projectActivity,
  rowChanges,
  rowFromEntry,
  rowsByDay,
  typeOf,
  EMPTY_FILTERS,
} from "./audit-view.ts";

const NOW = Date.parse("2026-09-22T12:00:00Z");
const DAY = 86_400_000;

const PRODUCTS: Product[] = [
  { id: "p-led", name: "LED strip lights", category: "home", status: "CANDIDATE", created_by: "agent", source: "research" },
  { id: "p-silicone", name: "Silicone kitchen organizer", category: "home", status: "CANDIDATE", created_by: "agent", source: "research" },
];

const AGENTS: Agent[] = [
  { id: "a-marketing", name: "Acquisition Agent", role: "marketing", capabilities: [], status: "AVAILABLE", reliability_score: 1, version: "1.8.5", cost_profile: {} },
  { id: "a-cfo", name: "CFO Controller", role: "cfo", capabilities: [], status: "AVAILABLE", reliability_score: 1, version: "1.9.0", cost_profile: {} },
];

const ENTRIES: AuditEntry[] = [
  {
    id: "e-1",
    actor: "agent-economic-analysis-1",
    action: "economics.run",
    resource: "economics:p-silicone",
    before: { sale_price: 45 },
    after: { sale_price: 50 },
    correlation_id: "c-1",
    created_at: new Date(NOW - 2 * DAY).toISOString(),
  },
  {
    id: "e-2",
    actor: "owner@amazona.local",
    action: "approval.completed",
    resource: "approval:1",
    before: null,
    after: { status: "APPROVED" },
    correlation_id: "c-1",
    created_at: new Date(NOW - 3600_000).toISOString(),
  },
];

const ROWS = auditRows(ENTRIES, PRODUCTS, AGENTS, NOW);

test("typeOf: el tipo sale del prefijo de la acción", () => {
  assert.equal(typeOf("approval.completed"), "Aprobación");
  assert.equal(typeOf("cfo.budget_validated"), "Finanzas");
  assert.equal(typeOf("auth.login"), "Seguridad");
  assert.equal(typeOf("pricing.price_changed"), "Precio");
  assert.equal(typeOf("unknown.thing"), "Otros");
});

test("rowFromEntry: la entrada real conserva actor, correlación y cambios", () => {
  const row = rowFromEntry(ENTRIES[0], 0, PRODUCTS);
  assert.equal(row.isDemo, false);
  assert.equal(row.actor, "agent-economic-analysis-1");
  assert.equal(row.actorKind, "Agente");
  assert.equal(row.type, "Finanzas");
  assert.equal(row.correlationId, "c-1");
  assert.equal(row.projectCode, "AMZ-0023", "el recurso apunta al segundo producto");
  assert.equal(row.productName, "Silicone kitchen organizer");
  assert.deepEqual(rowChanges(row), [{ key: "sale_price", before: "45", after: "50" }]);

  const approval = rowFromEntry(ENTRIES[1], 1, PRODUCTS);
  assert.equal(approval.criticality, "Alta");
  assert.equal(approval.actorKind, "Persona");
  assert.equal(approval.projectCode, null);
});

test("demoRows y auditRows: llenan el registro sin tapar lo real", () => {
  const demo = demoRows(PRODUCTS, AGENTS, NOW, 1);
  assert.equal(demo.length, EVENTS_PER_DAY * WINDOW_DAYS);
  assert.deepEqual(demoRows(PRODUCTS, AGENTS, NOW, 1), demo, "determinista");
  assert.ok(demo.every((row) => row.isDemo));
  assert.ok(demo.some((row) => row.actor === "Acquisition Agent"), "usa los agentes reales");
  assert.ok(demo.every((row) => row.at <= NOW));

  assert.equal(ROWS.length, ENTRIES.length + demo.length);
  assert.equal(ROWS.filter((row) => !row.isDemo).length, ENTRIES.length);
  for (let k = 1; k < ROWS.length; k++) assert.ok(ROWS[k - 1].at >= ROWS[k].at, "del más reciente al más antiguo");
  assert.equal(new Set(ROWS.map((row) => row.code)).size, ROWS.length);
});

test("auditKpis: cuenta lo de hoy por criticidad, tipo y resultado", () => {
  const kpis = auditKpis(ROWS, NOW);
  const today = ROWS.filter((row) => row.at >= NOW - (NOW % DAY));
  assert.equal(kpis.today, today.length);
  assert.equal(kpis.critical, today.filter((row) => row.criticality === "Alta").length);
  assert.equal(kpis.approvals, today.filter((row) => row.type === "Aprobación").length);
  assert.equal(kpis.errors, today.filter((row) => row.result === "Error").length);
  assert.equal(kpis.evidenceRate, EVIDENCE_COMPLETE_RATE);
  assert.ok(kpis.today > 0 && kpis.approvals >= 0);
});

test("filterRows: ventana, tipo, actor, proyecto, criticidad y búsqueda", () => {
  assert.ok(filterRows(ROWS, { ...EMPTY_FILTERS, window: "24h" }, NOW).every((row) => NOW - row.at <= DAY));
  assert.ok(filterRows(ROWS, { ...EMPTY_FILTERS, type: "Aprobación" }, NOW).every((row) => row.type === "Aprobación"));
  assert.ok(filterRows(ROWS, { ...EMPTY_FILTERS, criticality: "Alta" }, NOW).every((row) => row.criticality === "Alta"));
  assert.ok(filterRows(ROWS, { ...EMPTY_FILTERS, project: "AMZ-0024" }, NOW).every((row) => row.projectCode === "AMZ-0024"));
  assert.ok(filterRows(ROWS, { ...EMPTY_FILTERS, actor: "CFO Controller" }, NOW).every((row) => row.actor === "CFO Controller"));
  const search = filterRows(ROWS, { ...EMPTY_FILTERS, window: "all", query: "legal gate" }, NOW);
  assert.ok(search.length > 0 && search.every((row) => row.title.toLowerCase().includes("legal gate")));
  assert.equal(filterRows(ROWS, { ...EMPTY_FILTERS, window: "all" }, NOW).length, ROWS.length);
});

test("paginate: páginas, rango mostrado y límites", () => {
  const first = paginate(ROWS, 0, 12);
  assert.equal(first.items.length, 12);
  assert.equal(first.from, 1);
  assert.equal(first.to, 12);
  assert.equal(first.total, ROWS.length);
  assert.equal(first.pages, Math.ceil(ROWS.length / 12));
  const last = paginate(ROWS, 999, 12);
  assert.equal(last.page, first.pages - 1);
  assert.equal(last.to, ROWS.length);
  const empty = paginate([], 0, 12);
  assert.deepEqual([empty.items.length, empty.pages, empty.from, empty.total], [0, 1, 0, 0]);
});

test("detailFields y correlationTrace: lo real separado de lo de demostración", () => {
  const row = ROWS.find((r) => !r.isDemo)!;
  const fields = detailFields(row);
  assert.ok(fields.real.some((field) => field.label === "ID de correlación" && field.value === row.correlationId));
  assert.ok(fields.demo.some((field) => field.label === "Hash" && field.value.length === 16));

  const trace = correlationTrace(ROWS, "c-1");
  assert.equal(trace.length, 2, "los dos eventos reales comparten correlación");
  assert.ok(trace[0].at <= trace[1].at);
  assert.deepEqual(correlationTrace(ROWS, "no-existe"), []);
});

test("actorActivity, projectActivity y rowsByDay: agrupaciones del registro", () => {
  const actors = actorActivity(ROWS);
  assert.equal(actors.reduce((sum, row) => sum + row.events, 0), ROWS.length);
  for (let k = 1; k < actors.length; k++) assert.ok(actors[k - 1].events >= actors[k].events);

  const projects = projectActivity(ROWS);
  assert.ok(projects.length > 0 && projects.every((row) => row.projectCode.startsWith("AMZ-")));

  const days = rowsByDay(ROWS);
  assert.equal(days.reduce((sum, day) => sum + day.rows.length, 0), ROWS.length);
  for (let k = 1; k < days.length; k++) assert.ok(days[k - 1].day > days[k].day);
});

test("anomalies y filterOptions: anomalías de la semana y opciones de filtro", () => {
  const list = anomalies(ROWS, NOW);
  assert.ok(list.length >= 3 && list.every((item) => item.count > 0));
  const options = filterOptions(ROWS);
  assert.ok(options.types.includes("Aprobación") && options.actors.length > 1);
  assert.ok(options.projects.every((code) => code.startsWith("AMZ-")));
});
