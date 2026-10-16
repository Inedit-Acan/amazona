import assert from "node:assert/strict";
import { test } from "node:test";
import { agentsContract, auditContract, executionsContract } from "./ceo-activity-contracts.ts";
import { auditAscending, entry, execution, REGISTRY } from "./ceo-activity-test-support.ts";
import type { ReadState } from "./read-state.ts";

// El CONTRATO de cada lectura de «Actividad registrada» y «Ejecuciones por área» (M47, Commit 5): una fila que no cumple rompe la
// lectura entera y es `error` con un texto nuestro; nunca una fila ignorada, un valor por defecto ni una lista vacía.

const loadedOf = <T>(data: T[]): ReadState<T[]> => ({ kind: "loaded", data });
const broken = (value: unknown) => [value] as never[];

test("filas válidas pasan tal cual; un vacío o un error se respetan", () => {
  const rows = auditAscending(3);
  assert.deepEqual(auditContract(loadedOf(rows)), { kind: "loaded", data: rows });
  assert.deepEqual(auditContract({ kind: "empty" }), { kind: "empty" });
  assert.deepEqual(auditContract({ kind: "error", message: "x" }), { kind: "error", message: "x" });
});

test("auditoría: una fecha rota, sin zona rara o ausente es `error` (no se omite la fila)", () => {
  for (const bad of ["no es una fecha", "", "2026-13-45T99:99:99", undefined, null, 12345]) {
    const state = auditContract(loadedOf([entry("a1"), entry("a2", { created_at: bad as never })]));
    assert.equal(state.kind, "error", String(bad));
  }
});

test("auditoría: una fecha de SQLite sin sufijo de zona es válida (se lee como UTC)", () => {
  assert.equal(auditContract(loadedOf([entry("a1", { created_at: "2026-09-21T21:49:34" })])).kind, "loaded");
});

test("auditoría: sin id, actor, acción o recurso de texto ⇒ error", () => {
  for (const patch of [{ id: "" }, { id: 7 }, { actor: "" }, { actor: null }, { action: "" }, { action: 3 }, { resource: null }, { resource: 5 }]) {
    assert.equal(auditContract(loadedOf([entry("a1", patch as never)])).kind, "error", JSON.stringify(patch));
  }
  assert.equal(auditContract(loadedOf(broken(null))).kind, "error");
  assert.equal(auditContract(loadedOf(broken("texto"))).kind, "error");
});

test("ejecuciones: id, agente, capacidad, duración finita ≥ 0, éxito booleano y fecha válida", () => {
  assert.equal(executionsContract(loadedOf([execution("e1", "agent-product-1")])).kind, "loaded");
  const patches: Array<Record<string, unknown>> = [
    { id: "" },
    { agent_id: "" },
    { agent_id: null },
    { capability: 3 },
    { duration_ms: "1200" },
    { duration_ms: Number.NaN },
    { duration_ms: Number.POSITIVE_INFINITY },
    { duration_ms: -1 },
    { duration_ms: null },
    { success: "true" },
    { success: 1 },
    { success: null },
    { created_at: "ayer" },
    { created_at: undefined },
  ];
  for (const patch of patches) {
    assert.equal(executionsContract(loadedOf([execution("e1", "agent-product-1", patch as never)])).kind, "error", JSON.stringify(patch));
  }
});

test("agentes: id, nombre y rol de texto; un rol vacío o ausente ⇒ error", () => {
  assert.equal(agentsContract(loadedOf(REGISTRY)).kind, "loaded");
  for (const patch of [{ id: "" }, { name: "" }, { name: null }, { role: "" }, { role: null }, { role: 4 }]) {
    assert.equal(agentsContract(loadedOf([{ ...REGISTRY[0], ...patch } as never])).kind, "error", JSON.stringify(patch));
  }
});

test("el mensaje de un contrato roto es nuestro, nombra la fila y no es técnico", () => {
  const state = auditContract(loadedOf([entry("a1"), entry("a2", { created_at: "ayer" })]));
  assert.equal(state.kind, "error");
  if (state.kind !== "error") return;
  assert.match(state.message, /fila 2/);
  assert.match(state.message, /auditor/i);
  assert.doesNotMatch(state.message, /undefined|\[object|Traceback|HTTP/);
});
