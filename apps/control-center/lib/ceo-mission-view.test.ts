import assert from "node:assert/strict";
import { test } from "node:test";
import type { Decision } from "./api.ts";
import { missionOutcome, NOT_AVAILABLE } from "./ceo-mission-view.ts";
import { unreadState, type ReadState } from "./read-state.ts";
import { agent, execution } from "./read-test-support.ts";
import type { Settled } from "./revenue-view.ts";

// El resumen de una misión ejecutada (M47, Commit 2). Antes, tres lecturas en «mejor esfuerzo» con `.catch(() => [])`: un fallo
// salía como «Agentes ejecutados: 0».

const decision: Decision = {
  id: "d1",
  project_id: "p1",
  status: "GO",
  opportunity_score: 0.9,
  confidence: 0.8,
  rationale: null,
  correlation_id: "corr-1",
  evidence: [],
};
const okDecision: Settled<Decision> = { ok: true, data: decision };
const badDecision: Settled<Decision> = { ok: false, message: "No se pudo cargar la decisión." };
const loaded = <T>(data: T): ReadState<T> => ({ kind: "loaded", data });
const failed = (): ReadState<never> => ({ kind: "error", message: "No se pudo cargar el log de ejecuciones." });

const own = (id: string, agentId: string) => ({ ...execution(id, agentId), correlation_id: "corr-1" });
const other = (id: string, agentId: string) => ({ ...execution(id, agentId), correlation_id: "otra" });

test("con todo leído: cuenta solo las ejecuciones de ESTA misión, con el nombre del agente", () => {
  const view = missionOutcome({
    correlationId: "corr-1",
    decision: okDecision,
    executions: loaded([own("e1", "a1"), own("e2", "a2"), other("e3", "a1")]),
    agents: loaded([agent("a1"), agent("a2")]),
  });
  assert.deepEqual(view.executed, { kind: "value", count: 2 });
  assert.deepEqual(view.rows.map((row) => row.agent), ["Agente a1", "Agente a2"]);
  assert.equal(view.agentNamesUnavailable, false);
  assert.equal(view.decisionNote, null);
  assert.deepEqual(view.decision, { kind: "loaded", decision });
});

test("el log de ejecuciones falla: «No disponible», NO 0, y sin filas", () => {
  const view = missionOutcome({ correlationId: "corr-1", decision: okDecision, executions: failed(), agents: loaded([agent("a1")]) });
  assert.deepEqual(view.executed, { kind: "unavailable", text: NOT_AVAILABLE });
  assert.deepEqual(view.rows, []);
});

test("el log sin leer (`unread`) tampoco es cero", () => {
  const view = missionOutcome({ correlationId: "corr-1", decision: okDecision, executions: unreadState("no se intentó"), agents: loaded([]) });
  assert.equal(view.executed.kind, "unavailable");
});

test("el log VÁLIDO y vacío sí es un cero (un hecho)", () => {
  const view = missionOutcome({ correlationId: "corr-1", decision: okDecision, executions: { kind: "empty" }, agents: loaded([]) });
  assert.deepEqual(view.executed, { kind: "value", count: 0 });
});

test("los agentes fallan: las filas llevan el id y se dice; no se inventan nombres", () => {
  const view = missionOutcome({ correlationId: "corr-1", decision: okDecision, executions: loaded([own("e1", "a1")]), agents: failed() });
  assert.deepEqual(view.rows.map((row) => row.agent), ["a1"]);
  assert.equal(view.agentNamesUnavailable, true);
  assert.deepEqual(view.executed, { kind: "value", count: 1 });
});

test("la decisión falla: se dice y el grafo recibe `unavailable` (no `none`: la misión SÍ se ejecutó)", () => {
  const view = missionOutcome({ correlationId: "corr-1", decision: badDecision, executions: loaded([]), agents: loaded([]) });
  assert.match(view.decisionNote!, /no se pudo leer su decisión completa/);
  assert.deepEqual(view.decision, { kind: "unavailable" });
});

test("nada de esto produce un resumen con cifras de relleno", () => {
  const view = missionOutcome({ correlationId: "corr-1", decision: badDecision, executions: failed(), agents: failed() });
  assert.doesNotMatch(JSON.stringify(view), /demo|AMZ-2026|"count":0/);
});
