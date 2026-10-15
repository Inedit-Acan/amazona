import assert from "node:assert/strict";
import { test } from "node:test";
import type { ReadState } from "./read-state.ts";
import { approval, incident, killSwitch, one, product, review } from "./ceo-block-test-support.ts";
import { approvalsContract, incidentsContract, killSwitchContract, productsContract, reviewsContract } from "./ceo-block-contracts.ts";

// El CONTRATO de cada lectura de los bloques ejecutivos (M47, Commit 3B). `readList` solo comprueba que la respuesta es una lista;
// aquí se comprueba cada fila. Una fila que no cumple el contrato rompe la lectura entera: es `error` (visible), nunca una lista vacía,
// una fila sin insignia, un «Media» por defecto ni una fila ignorada en silencio.

const asLoaded = <T>(data: T[]): ReadState<T[]> => ({ kind: "loaded", data });
const bad = (state: ReadState<unknown>) => {
  assert.equal(state.kind, "error");
  return state.kind === "error" ? state.message : "";
};

test("filas válidas pasan tal cual; empty, error y unread pasan sin tocarse", () => {
  const rows = [approval("a1")];
  assert.deepEqual(approvalsContract(asLoaded(rows)), asLoaded(rows));
  for (const state of [{ kind: "empty" }, { kind: "error", message: "m" }, { kind: "unread", reason: "r" }] as const) {
    assert.deepEqual(approvalsContract(state), state);
    assert.deepEqual(reviewsContract(state), state);
    assert.deepEqual(productsContract(state), state);
    assert.deepEqual(incidentsContract(state), state);
  }
});

test("aprobaciones: estado desconocido, acción vacía, importe no numérico, vencimiento ilegible o id ausente ⇒ error", () => {
  const cases: Array<Partial<ReturnType<typeof approval>>> = [
    { status: "PAUSED" as never },
    { action: "" },
    { amount: "12" as never },
    { amount: Number.NaN },
    { expires_at: "mañana" },
    { id: "" },
    { expires_at: 5 as never },
  ];
  for (const over of cases) assert.match(bad(approvalsContract(asLoaded([approval("ok"), approval("x", over)]))), /aprobaciones/, JSON.stringify(over));
});

test("aprobaciones: importe nulo y vencimiento nulo son válidos (no son un contrato roto)", () => {
  assert.equal(approvalsContract(asLoaded([approval("a", { amount: null, expires_at: null })])).kind, "loaded");
});

test("revisiones: tipo o estado desconocido, motivos que no son texto, acción que no es texto ⇒ error", () => {
  const cases: Array<Partial<ReturnType<typeof review>>> = [
    { kind: "OTHER" as never },
    { status: "LOST" as never },
    { reasons: "uno" as never },
    { reasons: [1] as never },
    { action: 3 as never },
    { id: "" },
  ];
  for (const over of cases) assert.match(bad(reviewsContract(asLoaded([review("x", over)]))), /revisiones/, JSON.stringify(over));
  assert.equal(reviewsContract(asLoaded([review("g", { step: null, action: null, reasons: [] })])).kind, "loaded");
  assert.equal(reviewsContract(asLoaded([review("g", { status: "CONSUMED" as never })])).kind, "loaded");
});

test("productos: estado distinto de CANDIDATE u origen desconocido ⇒ error (nada se reinterpreta como oportunidad validada)", () => {
  for (const over of [{ status: "GO" }, { status: "VALIDATED" }, { source: "import" }, { source: "" }, { name: "" }, { id: "" }]) {
    assert.match(bad(productsContract(asLoaded([product("ok"), product("x", over as never)]))), /catálogo/, JSON.stringify(over));
  }
  assert.equal(productsContract(asLoaded([product("a", { source: "manual" }), product("b", { source: "research" })])).kind, "loaded");
});

test("incidencias: severidad desconocida o ausente ⇒ ERROR (nunca «Media», nunca una fila sin insignia)", () => {
  for (const severity of ["URGENT", "", "medium", null, undefined, 3]) {
    const message = bad(incidentsContract(asLoaded([incident("ok"), incident("x", { severity: severity as never })])));
    assert.match(message, /incidencias/);
    assert.doesNotMatch(message, /Media/);
  }
  for (const severity of ["LOW", "MEDIUM", "HIGH", "CRITICAL"] as const) assert.equal(incidentsContract(asLoaded([incident("a", { severity })])).kind, "loaded");
});

test("incidencias: estado desconocido, título vacío, fecha ilegible ⇒ error", () => {
  for (const over of [{ status: "CLOSED" }, { title: "" }, { created_at: "ayer" }, { created_at: null }, { id: "" }]) {
    assert.match(bad(incidentsContract(asLoaded([incident("x", over as never)]))), /incidencias/, JSON.stringify(over));
  }
});

test("kill switch: `enabled` debe ser un booleano de verdad (no «false», no 0, no nulo) y el motivo, texto o nulo", () => {
  assert.equal(killSwitchContract(one(killSwitch({ enabled: false, reason: "x" }))).kind, "loaded");
  assert.equal(killSwitchContract(one(killSwitch({ enabled: true }))).kind, "loaded");
  for (const enabled of ["false", 0, 1, null, undefined]) assert.match(bad(killSwitchContract(one(killSwitch({ enabled: enabled as never })))), /pipeline/);
  assert.match(bad(killSwitchContract(one(killSwitch({ reason: 5 as never })))), /pipeline/);
  assert.match(bad(killSwitchContract({ kind: "loaded", data: null as never })), /pipeline/);
});

test("el mensaje del contrato roto es nuestro, legible y sin detalles técnicos", () => {
  const message = bad(incidentsContract(asLoaded([incident("x", { severity: "URGENT" as never })])));
  assert.doesNotMatch(message, /\b[45]\d\d\b|undefined|\[object|TypeError|Traceback|HTTP/);
  assert.match(message, /severidad/);
});
