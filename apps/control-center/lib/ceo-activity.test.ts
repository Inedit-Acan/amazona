import assert from "node:assert/strict";
import { test } from "node:test";
import { activityBlock, activityStateOf, AUDIT_API_LIMIT, VISIBLE_ACTIVITY, type ActivityView } from "./ceo-activity.ts";
import { auditAscending, entry, MINUTE, NOW, REGISTRY } from "./ceo-activity-test-support.ts";
import type { AuditEntry } from "./api.ts";
import type { ReadState } from "./read-state.ts";

// «Actividad registrada» (M47, Commit 5, D-5-1/D-5-2): las últimas cinco entradas del registro de auditoría SI Y SOLO SI la lectura es
// completa. La API devuelve las 500 entradas más ANTIGUAS en orden ascendente: con 500 filas no puede garantizar las más recientes.

const loaded = <T>(data: T[]): ReadState<T[]> => (data.length === 0 ? { kind: "empty" } : { kind: "loaded", data });
const agents = loaded(REGISTRY);
const view = (rows: AuditEntry[], agentState: ReadState<typeof REGISTRY> = agents): ActivityView => activityBlock({ audit: loaded(rows), agents: agentState });
const asLoaded = (value: ActivityView) => {
  assert.equal(value.kind, "loaded", JSON.stringify(value));
  if (value.kind !== "loaded") throw new Error("no cargado");
  return value;
};

test("la API ordena ASCENDENTE y la vista enseña las ÚLTIMAS cinco: 27 filas ⇒ las ids 23..27, la más nueva primero", () => {
  const out = asLoaded(view(auditAscending(27)));
  assert.equal(VISIBLE_ACTIVITY, 5);
  assert.deepEqual(
    out.visible.map((row) => row.key),
    ["audit:a0027", "audit:a0026", "audit:a0025", "audit:a0024", "audit:a0023"],
  );
  assert.equal(out.total, 27);
  assert.equal(out.more, 22);
});

test("el orden de la API no importa: la misma lista barajada o invertida da el mismo resultado", () => {
  const ascending = auditAscending(27);
  const reversed = [...ascending].reverse();
  const shuffled = [...ascending].sort((a, b) => (a.id.charCodeAt(4) * 7) % 5 - (b.id.charCodeAt(4) * 7) % 5 || (a.id < b.id ? 1 : -1));
  const keys = (rows: AuditEntry[]) => asLoaded(view(rows)).visible.map((row) => row.key);
  assert.deepEqual(keys(reversed), keys(ascending));
  assert.deepEqual(keys(shuffled), keys(ascending));
});

test("con el mismo `created_at`, desempata el `id` DESCENDENTE", () => {
  const at = new Date(NOW - 5 * MINUTE).toISOString();
  const rows = [entry("b", { created_at: at }), entry("c", { created_at: at }), entry("a", { created_at: at }), entry("z", { created_at: new Date(NOW - 9 * MINUTE).toISOString() })];
  assert.deepEqual(asLoaded(view(rows)).visible.map((row) => row.key), ["audit:c", "audit:b", "audit:a", "audit:z"]);
});

test("una fecha con y sin sufijo de zona del mismo instante son el mismo instante (UTC)", () => {
  const rows = [entry("m", { created_at: "2026-10-15T10:00:00" }), entry("n", { created_at: "2026-10-15T10:00:00Z" }), entry("old", { created_at: "2026-10-15T09:59:59Z" })];
  assert.deepEqual(asLoaded(view(rows)).visible.map((row) => row.key), ["audit:n", "audit:m", "audit:old"]);
});

test("la fila lleva su fecha y hora ABSOLUTAS en UTC; nunca «hace X», «hoy» ni «esta semana»", () => {
  const out = asLoaded(view([entry("a1", { created_at: "2026-10-14T14:05:00Z" })]));
  assert.equal(out.visible[0].atText, "14 oct 2026 · 14:05 UTC");
  const text = JSON.stringify(out);
  assert.doesNotMatch(text, /\bhace\b|\bhoy\b|esta semana|ayer|reciente/i);
});

test("el subtítulo dice «Últimas 5 de N entradas del registro de auditoría»; con menos de cinco, las que hay", () => {
  assert.equal(asLoaded(view(auditAscending(27))).subtitle, "Últimas 5 de 27 entradas del registro de auditoría");
  assert.equal(asLoaded(view(auditAscending(3))).subtitle, "Últimas 3 de 3 entradas del registro de auditoría");
  assert.equal(asLoaded(view(auditAscending(1))).subtitle, "Última 1 de 1 entrada del registro de auditoría");
});

test("«y N más» solo con lectura completa y más de cinco", () => {
  assert.equal(asLoaded(view(auditAscending(5))).more, 0);
  assert.equal(asLoaded(view(auditAscending(6))).more, 1);
});

test("499 filas ⇒ lectura completa (cargada)", () => {
  assert.equal(AUDIT_API_LIMIT, 500);
  const out = asLoaded(view(auditAscending(499)));
  assert.equal(out.total, 499);
  assert.equal(out.visible[0].key, "audit:a0499");
});

test("500 filas ⇒ NO DISPONIBLE: nunca se enseñan las 500 más antiguas como actividad", () => {
  for (const count of [500, 501, 1200]) {
    const out = view(auditAscending(count));
    assert.equal(out.kind, "unavailable", String(count));
    if (out.kind !== "unavailable") continue;
    assert.match(out.reason, /no puede garantizar las entradas más recientes/);
    assert.doesNotMatch(JSON.stringify(out), /a0001|a0002|audit:/);
    assert.equal(activityStateOf(out).kind, "unavailable");
  }
});

test("lista vacía ⇒ vacío («Sin actividad registrada»), no demostración; error ⇒ error; sin leer ⇒ sin leer", () => {
  const empty = activityBlock({ audit: { kind: "empty" }, agents });
  assert.deepEqual(empty, { kind: "empty", text: "Sin actividad registrada" });
  const error = activityBlock({ audit: { kind: "error", message: "No se pudo cargar la auditoría." }, agents });
  assert.deepEqual(error, { kind: "error", message: "No se pudo cargar la auditoría." });
  const unread = activityBlock({ audit: { kind: "unread", reason: "pendiente" }, agents });
  assert.deepEqual(unread, { kind: "unread", reason: "pendiente" });
  assert.notEqual(unread.kind, "empty");
  assert.notEqual(error.kind, "empty");
});

test("el estado que entiende la tarjeta: cargado, vacío, error, sin leer y no disponible", () => {
  assert.equal(activityStateOf(view(auditAscending(2))).kind, "loaded");
  assert.equal(activityStateOf({ kind: "empty", text: "x" }).kind, "empty");
  assert.equal(activityStateOf({ kind: "error", message: "x" }).kind, "error");
  assert.equal(activityStateOf({ kind: "unread", reason: "x" }).kind, "unread");
});

// --- Categoría, acción, resultado -----------------------------------------------------------------------------------------------

test("la acción registrada se conserva tal cual y la categoría es el prefijo (derivada)", () => {
  const rows = [
    entry("a1", { action: "task.completed" }),
    entry("a2", { action: "decision.made" }),
    entry("a3", { action: "approval.requested" }),
    entry("a4", { action: "economics.run" }),
    entry("a5", { action: "pipeline.started" }),
    entry("a6", { action: "memory.remember" }),
    entry("a7", { action: "incident.opened" }),
    entry("a8", { action: "kill_switch.engaged" }),
    entry("a9", { action: "exchange_rate.set" }),
  ].map((row, index) => ({ ...row, created_at: new Date(NOW - (index + 1) * MINUTE).toISOString() }));
  const out = asLoaded(view(rows));
  const categories = Object.fromEntries(rows.map((row) => [row.action, "?"]));
  // Se enseñan 5, pero las categorías se comprueban sobre todas ordenando de cinco en cinco.
  for (let from = 0; from < rows.length; from += 5) {
    const slice = asLoaded(view(rows.slice(from, from + 5)));
    for (const item of slice.visible) categories[item.action] = item.category;
  }
  assert.deepEqual(categories, {
    "task.completed": "Proyecto",
    "decision.made": "Decisión",
    "approval.requested": "Aprobación",
    "economics.run": "Análisis",
    "pipeline.started": "Pipeline",
    "memory.remember": "Memoria",
    "incident.opened": "Incidencia",
    "kill_switch.engaged": "Seguridad",
    "exchange_rate.set": "Otros",
  });
  assert.equal(out.visible[0].action, "task.completed", "la acción original, no una traducción");
});

test("D-5-2: no se oculta ninguna acción técnica (exchange_rate.*, memory.*, task.*)", () => {
  const rows = [entry("a1", { action: "exchange_rate.set" }), entry("a2", { action: "memory.remember" }), entry("a3", { action: "task.retried" })].map((row, index) => ({
    ...row,
    created_at: new Date(NOW - index * MINUTE).toISOString(),
  }));
  const out = asLoaded(view(rows));
  assert.deepEqual(out.visible.map((row) => row.action).sort(), ["exchange_rate.set", "memory.remember", "task.retried"]);
});

test("una acción desconocida es «Otros» y conserva su nombre original", () => {
  const out = asLoaded(view([entry("a1", { action: "algo.rarisimo" })]));
  assert.equal(out.visible[0].category, "Otros");
  assert.equal(out.visible[0].action, "algo.rarisimo");
});

test("task.failed ⇒ «Fallo»; task.completed NO se llama «OK», «Éxito» ni «Correcta»", () => {
  const failed = asLoaded(view([entry("a1", { action: "task.failed" })]));
  assert.equal(failed.visible[0].failed, true);
  const error = asLoaded(view([entry("a1", { action: "pipeline.step_error" })]));
  assert.equal(error.visible[0].failed, true);
  const done = asLoaded(view([entry("a1", { action: "task.completed" })]));
  assert.equal(done.visible[0].failed, false);
  assert.doesNotMatch(JSON.stringify(done), /"OK"|\bOK\b|Éxito|Exito|Correct[ao]|Sin error/);
  const retried = asLoaded(view([entry("a1", { action: "task.retried" })]));
  assert.equal(retried.visible[0].failed, false, "un reintento no es un fallo por su nombre");
});

// --- Actor y área ---------------------------------------------------------------------------------------------------------------

test("un agente conocido sale con su NOMBRE y su ÁREA (cfo ⇒ Finanzas, finance ⇒ Economía)", () => {
  const out = asLoaded(
    view([
      entry("a3", { actor: "agent-product-1", created_at: new Date(NOW - 1 * MINUTE).toISOString() }),
      entry("a2", { actor: "agent-cfo-1", created_at: new Date(NOW - 2 * MINUTE).toISOString() }),
      entry("a1", { actor: "agent-finance-1", created_at: new Date(NOW - 3 * MINUTE).toISOString() }),
    ]),
  );
  assert.deepEqual(
    out.visible.map((row) => [row.actor.text, row.area]),
    [
      ["Product Validation Agent", "Investigación"],
      ["CFO Financial Health Agent", "Finanzas"],
      ["Finance Validation Agent", "Economía"],
    ],
  );
});

test("`ceo` ⇒ «Orquestador», sin área", () => {
  const row = asLoaded(view([entry("a1", { actor: "ceo" })])).visible[0];
  assert.equal(row.actor.text, "Orquestador");
  assert.equal(row.area, null);
});

test("un actor con correo ⇒ «Persona»: la dirección no está en ningún texto de la vista", () => {
  const rows = [
    entry("a1", { actor: "ivan.perez@example.com", resource: "user:ivan.perez@example.com", created_at: new Date(NOW - 1 * MINUTE).toISOString() }),
    entry("a2", { actor: "ops+test@acme.io", action: "incident.opened", resource: "incident:1", created_at: new Date(NOW - 2 * MINUTE).toISOString() }),
  ];
  const out = view(rows);
  const row = asLoaded(out).visible[0];
  assert.equal(row.actor.text, "Persona");
  assert.equal(row.area, null);
  const text = JSON.stringify(out);
  assert.doesNotMatch(text, /@/, "ninguna dirección de correo en la vista");
  assert.doesNotMatch(text, /ivan|example\.com|acme/i);
});

test("un actor desconocido no inventa identidad ni área (nunca «Operaciones»)", () => {
  const out = asLoaded(view([entry("a1", { actor: "agent-zzz-9" }), entry("a2", { actor: "scheduler", created_at: new Date(NOW - MINUTE).toISOString() })]));
  for (const row of out.visible) {
    assert.equal(row.area, null);
    assert.notEqual(row.actor.text, "Operaciones");
  }
  assert.equal(out.visible.find((row) => row.key === "audit:a1")?.actor.text, "agent-zzz-9", "el actor registrado, tal cual");
  assert.doesNotMatch(JSON.stringify(out), /Operaciones/);
});

test("un agente del registro cuyo rol no tiene área ⇒ sin área, no «Operaciones»", () => {
  const strange = { ...REGISTRY[0], id: "agent-strange-1", role: "alien" };
  const out = asLoaded(activityBlock({ audit: loaded([entry("a1", { actor: "agent-strange-1" })]), agents: loaded([strange]) }));
  assert.equal(out.visible[0].area, null);
  assert.equal(out.visible[0].actor.text, strange.name);
});

test("si el registro de agentes no se pudo leer, la actividad se enseña igual, sin nombres ni áreas, y lo dice", () => {
  const out = asLoaded(activityBlock({ audit: loaded([entry("a1", { actor: "agent-product-1" })]), agents: { kind: "error", message: "No se pudieron cargar los agentes." } }));
  assert.equal(out.visible[0].actor.text, "agent-product-1");
  assert.equal(out.visible[0].area, null);
  assert.match(out.agentsNote ?? "", /nombre y el área de los agentes no están disponibles/i);
  const fine = asLoaded(view([entry("a1")]));
  assert.equal(fine.agentsNote, null);
});

// --- Procedencia ----------------------------------------------------------------------------------------------------------------

test("procedencia: fecha, actor, acción y recurso son registrados; categoría, área y fallo son derivados", () => {
  const row = asLoaded(view([entry("a1", { actor: "agent-product-1", action: "task.failed" })])).visible[0];
  assert.deepEqual(row.provenance.recorded, ["created_at", "actor", "action", "resource"]);
  assert.deepEqual(row.provenance.derived, ["category", "area", "result"]);
  assert.equal(row.provenance.source, "audit_log");
  assert.equal(row.provenance.id, "a1");
  assert.doesNotMatch(JSON.stringify(row), /Verificad/);
});
