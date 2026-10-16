import assert from "node:assert/strict";
import { test } from "node:test";
import type { Agent, AgentExecution } from "./api.ts";
import { areaExecutionsBlock, areaStateOf, EXECUTIONS_API_LIMIT, NO_AREA, strictDomainOfRole, type AreaView } from "./ceo-area-executions.ts";
import { execution, makeAgent, MINUTE, NOW, REGISTRY } from "./ceo-activity-test-support.ts";
import { DOMAINS, domainOfRole } from "./nexus-domains.ts";
import type { ReadState } from "./read-state.ts";

// «Ejecuciones por área» (M47, Commit 5, D-5-3/D-5-4): conteos, «X de Y correctas», latencia media y última ejecución por dominio, sobre
// «las últimas N ejecuciones registradas» (N ≤ 100). Ningún porcentaje, ningún rendimiento, ningún dominio inventado.

const loaded = <T>(data: T[]): ReadState<T[]> => (data.length === 0 ? { kind: "empty" } : { kind: "loaded", data });
const agents = loaded(REGISTRY);
const at = (minutesAgo: number) => new Date(NOW - minutesAgo * MINUTE).toISOString();

function view(executions: AgentExecution[], agentState: ReadState<Agent[]> = agents): AreaView {
  return areaExecutionsBlock({ executions: loaded(executions), agents: agentState });
}
function asLoaded(value: AreaView) {
  assert.equal(value.kind, "loaded", JSON.stringify(value));
  if (value.kind !== "loaded") throw new Error("no cargado");
  return value;
}
const rowOf = (value: AreaView, area: string) => {
  const found = asLoaded(value).rows.find((row) => row.area === area);
  assert.ok(found, `falta la fila ${area}`);
  return found;
};

test("strictDomainOfRole: los 13 roles del registro y su dominio; un rol desconocido es null, no «Operaciones»", () => {
  const expected: Record<string, string> = {
    product: "Investigación",
    research: "Investigación",
    supplier: "Abastecimiento",
    sourcing: "Abastecimiento",
    finance: "Economía",
    economics: "Economía",
    legal: "Legal",
    legal_compliance: "Legal",
    ecommerce: "Comercio",
    marketplace: "Comercio",
    marketing: "Marketing",
    operations: "Operaciones",
    cfo: "Finanzas",
  };
  for (const [role, domain] of Object.entries(expected)) assert.equal(strictDomainOfRole(role), domain, role);
  for (const agent of REGISTRY) assert.ok(strictDomainOfRole(agent.role) !== null, `${agent.id} sin área`);
  for (const role of ["alien", "", "Product", "CFO", "unknown"]) assert.equal(strictDomainOfRole(role), null, role);
});

test("`domainOfRole` del Decision Engine NO cambia: un rol desconocido sigue cayendo en Operaciones (el área nueva es otra función)", () => {
  assert.equal(domainOfRole("alien"), "Operaciones");
  assert.equal(strictDomainOfRole("alien"), null);
});

test("las ocho áreas salen siempre, en el orden de los dominios; «Sin área» solo si hay ejecuciones sin dominio", () => {
  const out = asLoaded(view([execution("e1", "agent-product-1")]));
  assert.deepEqual(out.rows.map((row) => row.area), [...DOMAINS]);
  assert.equal(out.rows.length, 8);
  const withOrphan = asLoaded(view([execution("e1", "agent-product-1"), execution("e2", "agent-desconocido-7")]));
  assert.deepEqual(withOrphan.rows.map((row) => row.area), [...DOMAINS, NO_AREA]);
  assert.equal(NO_AREA, "Sin área");
});

test("Economía y Finanzas son DOS áreas distintas: finance ≠ cfo", () => {
  const out = view([
    execution("e1", "agent-finance-1"),
    execution("e2", "agent-finance-1"),
    execution("e3", "agent-economic-analysis-1"),
    execution("e4", "agent-cfo-1"),
  ]);
  assert.equal(rowOf(out, "Economía").total, 3);
  assert.equal(rowOf(out, "Finanzas").total, 1);
});

test("conteos, correctas y fallidas por área, y «X de Y correctas»", () => {
  const out = view([
    execution("e1", "agent-legal-1", { success: true }),
    execution("e2", "agent-legal-compliance-1", { success: false }),
    execution("e3", "agent-legal-1", { success: true }),
    execution("e4", "agent-marketing-campaign-1", { success: false }),
  ]);
  const legal = rowOf(out, "Legal");
  assert.deepEqual([legal.total, legal.ok, legal.failed], [3, 2, 1]);
  assert.equal(legal.okText, "2 de 3 correctas");
  assert.equal(legal.failedText, "1 fallida");
  const marketing = rowOf(out, "Marketing");
  assert.deepEqual([marketing.total, marketing.ok, marketing.failed], [1, 0, 1]);
  assert.equal(marketing.okText, "0 de 1 correctas");
  assert.equal(rowOf(out, "Legal").agents, 2);
});

test("cada fila del log es UNA ejecución: reintentos del mismo agente y misma correlación se cuentan todos (el log es historia, no una foto)", () => {
  const rows = [
    execution("e1", "agent-supplier-1", { correlation_id: "c1", success: false, created_at: at(10) }),
    execution("e2", "agent-supplier-1", { correlation_id: "c1", success: false, created_at: at(9) }),
    execution("e3", "agent-supplier-1", { correlation_id: "c1", success: true, created_at: at(8) }),
  ];
  const row = rowOf(view(rows), "Abastecimiento");
  assert.deepEqual([row.total, row.ok, row.failed], [3, 1, 2]);
});

test("latencia media de las ejecuciones de ESA área; sin ejecuciones, «Sin dato» (nunca 0 ms)", () => {
  const out = view([
    execution("e1", "agent-product-1", { duration_ms: 1000 }),
    execution("e2", "agent-product-research-1", { duration_ms: 3000 }),
    execution("e3", "agent-legal-1", { duration_ms: 50 }),
  ]);
  const research = rowOf(out, "Investigación");
  assert.equal(research.meanLatencyMs, 2000);
  assert.equal(research.latencyText, "2,0 s");
  assert.equal(rowOf(out, "Legal").meanLatencyMs, 50);
  const idle = rowOf(out, "Comercio");
  assert.equal(idle.meanLatencyMs, null);
  assert.equal(idle.latencyText, "Sin dato");
  assert.doesNotMatch(idle.latencyText, /0 ms/);
  assert.equal(idle.total, 0);
  assert.equal(idle.okText, "Sin ejecuciones");
  assert.equal(idle.lastAt, null);
  assert.equal(idle.lastText, "Sin ejecuciones");
});

test("la última ejecución es el máximo `created_at` del área (desempate por id), no la primera ni la última del array", () => {
  const out = view([
    execution("e2", "agent-operations-1", { created_at: at(50) }),
    execution("e9", "agent-operations-1", { created_at: at(5) }),
    execution("e1", "agent-operations-1", { created_at: at(200) }),
    execution("e5", "agent-operations-1", { created_at: at(5) }),
  ]);
  const row = rowOf(out, "Operaciones");
  assert.equal(row.lastAt, at(5));
  assert.equal(row.lastText, "15 oct 2026 · 11:55 UTC");
  assert.equal(row.lastId, "e9");
});

test("el orden en que llegan las filas no cambia nada", () => {
  const rows = [
    execution("e1", "agent-product-1", { duration_ms: 100, created_at: at(1) }),
    execution("e2", "agent-cfo-1", { duration_ms: 200, success: false, created_at: at(2) }),
    execution("e3", "agent-legal-1", { duration_ms: 300, created_at: at(3) }),
    execution("e4", "agent-product-1", { duration_ms: 500, created_at: at(4) }),
  ];
  assert.deepEqual(view([...rows].reverse()), view(rows));
});

test("un agente que no está en el registro ⇒ «Sin área»; un agente con rol sin dominio ⇒ «Sin área»; nunca «Operaciones»", () => {
  const strange = makeAgent("agent-strange-1", "alien", "Agente extraño");
  const out = view([execution("e1", "agent-no-existe"), execution("e2", "agent-strange-1")], loaded([...REGISTRY, strange]));
  const orphan = rowOf(out, NO_AREA);
  assert.equal(orphan.total, 2);
  assert.equal(rowOf(out, "Operaciones").total, 0);
});

test("con el registro vacío, todas las ejecuciones son «Sin área» (el registro leído y vacío es un hecho)", () => {
  const out = areaExecutionsBlock({ executions: loaded([execution("e1", "agent-product-1")]), agents: { kind: "empty" } });
  assert.equal(rowOf(out, NO_AREA).total, 1);
});

test("el registro de agentes que falla ⇒ error COMPLETO (no se reparte nada por defecto); lo mismo si falla el log", () => {
  const rows = loaded([execution("e1", "agent-product-1")]);
  const noRegistry = areaExecutionsBlock({ executions: rows, agents: { kind: "error", message: "No se pudieron cargar los agentes." } });
  assert.equal(noRegistry.kind, "error");
  const noLog = areaExecutionsBlock({ executions: { kind: "error", message: "No se pudo cargar el log de ejecuciones." }, agents });
  assert.equal(noLog.kind, "error");
  const both = areaExecutionsBlock({ executions: { kind: "error", message: "a" }, agents: { kind: "error", message: "b" } });
  assert.equal(both.kind === "error" && both.message, "a b");
  // Un error con el log vacío tampoco es «vacío».
  assert.equal(areaExecutionsBlock({ executions: { kind: "empty" }, agents: { kind: "error", message: "x" } }).kind, "error");
});

test("sin leer ⇒ sin leer (nunca vacío)", () => {
  const out = areaExecutionsBlock({ executions: { kind: "unread", reason: "pendiente" }, agents });
  assert.equal(out.kind, "unread");
  assert.notEqual(out.kind, "empty");
});

test("log vacío válido ⇒ vacío («Sin ejecuciones registradas»), no ocho filas de ceros", () => {
  const out = areaExecutionsBlock({ executions: { kind: "empty" }, agents });
  assert.deepEqual(out, { kind: "empty", text: "Sin ejecuciones registradas" });
  assert.equal(areaStateOf(out).kind, "empty");
});

test("la ventana es explícita: «Últimas N ejecuciones registradas»; con 100 dice «las últimas 100, no el total»", () => {
  assert.equal(EXECUTIONS_API_LIMIT, 100);
  const four = asLoaded(view(Array.from({ length: 4 }, (_unused, i) => execution(`e${i}`, "agent-product-1"))));
  assert.equal(four.total, 4);
  assert.equal(four.windowText, "Últimas 4 ejecuciones registradas");
  assert.equal(four.truncated, false);
  const one = asLoaded(view([execution("e1", "agent-product-1")]));
  assert.equal(one.windowText, "Última ejecución registrada");

  const hundred = asLoaded(view(Array.from({ length: 100 }, (_unused, i) => execution(`e${String(i).padStart(3, "0")}`, "agent-product-1", { created_at: at(i) }))));
  assert.equal(hundred.total, 100);
  assert.equal(hundred.truncated, true);
  assert.match(hundred.windowText, /Últimas 100 ejecuciones registradas/);
  assert.match(hundred.windowText, /no el total/);
  assert.doesNotMatch(hundred.windowText, /100 ejecuciones totales|en total/i);
});

test("ningún porcentaje, rendimiento, eficiencia, SLA, uptime, coste ni tendencia en nada de lo que la vista dice", () => {
  const rows = [execution("e1", "agent-product-1"), execution("e2", "agent-cfo-1", { success: false }), execution("e3", "agent-legal-1")];
  const text = JSON.stringify(view(rows));
  assert.doesNotMatch(text, /%/);
  assert.doesNotMatch(text, /rendimiento|eficiencia|\bSLA\b|uptime|coste|tendencia|periodo anterior|tasa de/i);
  for (const mock of ["92", "78", "65", "88", "90", "76", "81"]) assert.doesNotMatch(text, new RegExp(`\\b${mock}\\b`));
});

test("la latencia no se llama «rendimiento» ni «velocidad del área»; el texto fijo la define", () => {
  const out = asLoaded(view([execution("e1", "agent-product-1")]));
  assert.match(out.footnote, /Latencia media de las ejecuciones registradas/);
  assert.doesNotMatch(out.footnote, /rendimiento|velocidad/i);
});

test("procedencia: la fila de ejecución y la última ejecución son registradas; conteos, «X de Y», media y área son derivados", () => {
  const row = rowOf(view([execution("e1", "agent-product-1")]), "Investigación");
  assert.deepEqual(row.provenance.recorded, ["created_at"]);
  assert.deepEqual(row.provenance.derived, ["total", "ok", "failed", "meanLatencyMs", "area"]);
  assert.equal(row.provenance.source, "agent_execution_log");
  assert.doesNotMatch(JSON.stringify(row), /Verificad/);
});

test("el estado que entiende la tarjeta", () => {
  assert.equal(areaStateOf(view([execution("e1", "agent-product-1")])).kind, "loaded");
  assert.equal(areaStateOf({ kind: "error", message: "x" }).kind, "error");
  assert.equal(areaStateOf({ kind: "unread", reason: "x" }).kind, "unread");
});
