import assert from "node:assert/strict";
import { test } from "node:test";
import type { AuditEntry } from "./api.ts";
import { activityBlock, activityStateOf, ACTIVITY_LIMIT, type ActivityView } from "./ceo-activity.ts";
import { auditAscending, auditDescending, entry, MINUTE, NOW, REGISTRY, stack } from "./ceo-activity-test-support.ts";
import type { ReadState } from "./read-state.ts";

// «Actividad registrada» (M47, micro-commit 5B): el frontend pide `GET /api/audit?order=desc&limit=5` y la respuesta VÁLIDA son como
// mucho 5 filas ya en orden `created_at` DESC, `id` DESC. Una respuesta de un backend viejo o mal desplegado (más de 5 filas, o en
// orden ascendente: las 500 más antiguas) NO se reordena ni se recorta para presentarla como válida: es «No disponible».

const loaded = <T>(data: T[]): ReadState<T[]> => (data.length === 0 ? { kind: "empty" } : { kind: "loaded", data });
const agents = loaded(REGISTRY);
const view = (rows: AuditEntry[], agentState: ReadState<typeof REGISTRY> = agents): ActivityView => activityBlock({ audit: loaded(rows), agents: agentState });
const asLoaded = (value: ActivityView) => {
  assert.equal(value.kind, "loaded", JSON.stringify(value));
  if (value.kind !== "loaded") throw new Error("no cargado");
  return value;
};

// --- Respuesta válida ----------------------------------------------------------------------------------------------------------

test("5 filas en orden descendente ⇒ cargada, tal cual llegan (la más nueva primero)", () => {
  assert.equal(ACTIVITY_LIMIT, 5);
  const out = asLoaded(view(auditDescending(5)));
  assert.deepEqual(out.visible.map((row) => row.key), ["audit:a0005", "audit:a0004", "audit:a0003", "audit:a0002", "audit:a0001"]);
});

test("3 filas en orden descendente ⇒ cargada; 1 fila ⇒ cargada", () => {
  assert.deepEqual(asLoaded(view(auditDescending(3))).visible.map((row) => row.key), ["audit:a0003", "audit:a0002", "audit:a0001"]);
  assert.deepEqual(asLoaded(view(auditDescending(1))).visible.map((row) => row.key), ["audit:a0001"]);
});

test("subtítulos: 1 ⇒ «Última entrada registrada», 3 ⇒ «Últimas 3 entradas registradas», 5 ⇒ «Últimas 5 entradas registradas»", () => {
  assert.equal(asLoaded(view(auditDescending(1))).subtitle, "Última entrada registrada");
  assert.equal(asLoaded(view(auditDescending(2))).subtitle, "Últimas 2 entradas registradas");
  assert.equal(asLoaded(view(auditDescending(3))).subtitle, "Últimas 3 entradas registradas");
  assert.equal(asLoaded(view(auditDescending(5))).subtitle, "Últimas 5 entradas registradas");
});

test("no se conoce el total: ni «de N», ni «y N más», ni contador, ni campos `total`/`more` en la vista", () => {
  for (const count of [1, 3, 5]) {
    const out = asLoaded(view(auditDescending(count)));
    const text = JSON.stringify(out);
    assert.doesNotMatch(text, /\bde \d+\b/, "«de N»");
    assert.doesNotMatch(text, /\by \d+ más\b|\bmás\b/, "«y N más»");
    assert.equal("total" in out, false);
    assert.equal("more" in out, false);
  }
});

test("la vista conserva el orden del servidor: no reordena ni recorta", () => {
  const rows = auditDescending(5);
  assert.deepEqual(asLoaded(view(rows)).visible.map((row) => row.provenance.id), rows.map((row) => row.id));
});

test("la fila lleva su fecha y hora ABSOLUTAS en UTC; nunca «hace X», «hoy» ni «esta semana»", () => {
  const out = asLoaded(view([entry("a1", { created_at: "2026-10-14T14:05:00Z" })]));
  assert.equal(out.visible[0].atText, "14 oct 2026 · 14:05 UTC");
  assert.doesNotMatch(JSON.stringify(out), /\bhace\b|\bhoy\b|esta semana|ayer|reciente/i);
});

// --- Guarda de compatibilidad: respuesta de un backend viejo o mal desplegado ------------------------------------------------

test("6 filas (aunque estén en orden descendente) ⇒ NO DISPONIBLE: no se recortan a 5", () => {
  const out = view(auditDescending(6));
  assert.equal(out.kind, "unavailable");
  if (out.kind !== "unavailable") return;
  assert.match(out.reason, /no puede garantizar las últimas entradas/);
  assert.doesNotMatch(JSON.stringify(out), /audit:|a0006|a0005/);
  assert.equal(activityStateOf(out).kind, "unavailable");
});

test("una respuesta ASCENDENTE (backend viejo: ignora `order`) ⇒ NO DISPONIBLE, aunque quepa en 5 filas; no se reordena", () => {
  for (const count of [2, 3, 5]) {
    const out = view(auditAscending(count));
    assert.equal(out.kind, "unavailable", String(count));
    assert.doesNotMatch(JSON.stringify(out), /audit:/);
  }
});

test("la guarda antigua sigue en pie: 27, 499, 500, 501 y 1200 filas ascendentes (el backend viejo) ⇒ NO DISPONIBLE, nunca cargada", () => {
  for (const count of [27, 499, 500, 501, 1200]) {
    const out = view(auditAscending(count));
    assert.equal(out.kind, "unavailable", String(count));
    assert.doesNotMatch(JSON.stringify(out), /a0001|a0002|audit:/);
  }
});

test("un solo par fuera de orden en medio de la lista ⇒ NO DISPONIBLE", () => {
  const [a, b, c, d, e] = auditDescending(5);
  for (const rows of [[a, c, b, d, e], [a, b, d, c, e], [b, a, c, d, e], [a, b, c, e, d]]) {
    assert.equal(view(rows).kind, "unavailable");
  }
});

test("con el mismo `created_at`, el `id` debe ir DESCENDENTE: ids en orden ascendente ⇒ NO DISPONIBLE", () => {
  const at = new Date(NOW - 5 * MINUTE).toISOString();
  const wrong = [entry("a", { created_at: at }), entry("b", { created_at: at }), entry("c", { created_at: at })];
  assert.equal(view(wrong).kind, "unavailable");
  const right = [entry("c", { created_at: at }), entry("b", { created_at: at }), entry("a", { created_at: at })];
  assert.deepEqual(asLoaded(view(right)).visible.map((row) => row.key), ["audit:c", "audit:b", "audit:a"]);
});

test("un empate en medio de una lista con ids correctos ⇒ cargada; con ids incorrectos ⇒ no disponible", () => {
  const at = new Date(NOW - 5 * MINUTE).toISOString();
  const newer = entry("z", { created_at: new Date(NOW - MINUTE).toISOString() });
  const older = entry("y", { created_at: new Date(NOW - 9 * MINUTE).toISOString() });
  assert.equal(view([newer, entry("t2", { created_at: at }), entry("t1", { created_at: at }), older]).kind, "loaded");
  assert.equal(view([newer, entry("t1", { created_at: at }), entry("t2", { created_at: at }), older]).kind, "unavailable");
});

test("dos filas idénticas (mismo instante y mismo id) no son un orden estricto ⇒ NO DISPONIBLE", () => {
  const same = entry("a1", { created_at: new Date(NOW - MINUTE).toISOString() });
  assert.equal(view([same, { ...same }]).kind, "unavailable");
});

test("una fecha con y sin sufijo de zona del mismo instante son el mismo instante (UTC): el empate se resuelve por el id", () => {
  const right = [entry("n", { created_at: "2026-10-15T10:00:00Z" }), entry("m", { created_at: "2026-10-15T10:00:00" }), entry("old", { created_at: "2026-10-15T09:59:59Z" })];
  assert.deepEqual(asLoaded(view(right)).visible.map((row) => row.key), ["audit:n", "audit:m", "audit:old"]);
  const wrong = [right[1], right[0], right[2]];
  assert.equal(view(wrong).kind, "unavailable");
});

test("un `created_at` con desplazamiento horario se ordena por su instante UTC, no por el texto", () => {
  // 14:00+02:00 son las 12:00Z; 12:30Z es MÁS reciente aunque su texto «12:30» sea menor que «14:00».
  const right = [entry("a", { created_at: "2026-10-15T12:30:00Z" }), entry("b", { created_at: "2026-10-15T14:00:00+02:00" })];
  assert.equal(view(right).kind, "loaded");
  assert.equal(view([right[1], right[0]]).kind, "unavailable");
});

// --- Estados --------------------------------------------------------------------------------------------------------------------

test("lista vacía ⇒ vacío («Sin actividad registrada»), no demostración; error ⇒ error; sin leer ⇒ sin leer; ninguno es «vacío»", () => {
  const empty = activityBlock({ audit: { kind: "empty" }, agents });
  assert.deepEqual(empty, { kind: "empty", text: "Sin actividad registrada" });
  const error = activityBlock({ audit: { kind: "error", message: "No se pudo cargar la auditoría." }, agents });
  assert.deepEqual(error, { kind: "error", message: "No se pudo cargar la auditoría." });
  const unread = activityBlock({ audit: { kind: "unread", reason: "pendiente" }, agents });
  assert.deepEqual(unread, { kind: "unread", reason: "pendiente" });
  assert.notEqual(error.kind, "empty");
  assert.notEqual(unread.kind, "empty");
  assert.notEqual(view(auditDescending(6)).kind, "empty");
});

test("el estado que entiende la tarjeta: cargado, vacío, error, sin leer y no disponible", () => {
  assert.equal(activityStateOf(view(auditDescending(2))).kind, "loaded");
  assert.equal(activityStateOf({ kind: "empty", text: "x" }).kind, "empty");
  assert.equal(activityStateOf({ kind: "error", message: "x" }).kind, "error");
  assert.equal(activityStateOf({ kind: "unread", reason: "x" }).kind, "unread");
  assert.equal(activityStateOf({ kind: "unavailable", reason: "x" }).kind, "unavailable");
});

// --- Categoría, acción, resultado ---------------------------------------------------------------------------------------------

test("la acción registrada se conserva tal cual y la categoría es el prefijo (derivada)", () => {
  const actions = ["task.completed", "decision.made", "approval.requested", "economics.run", "pipeline.started", "memory.remember", "incident.opened", "kill_switch.engaged", "exchange_rate.set"];
  const categories: Record<string, string> = {};
  for (let from = 0; from < actions.length; from += 5) {
    const slice = actions.slice(from, from + 5);
    for (const row of asLoaded(view(stack(...slice.map((action) => ({ action }))))).visible) categories[row.action] = row.category;
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
});

test("D-5-2: no se oculta ninguna acción técnica (exchange_rate.*, memory.*, task.*)", () => {
  const out = asLoaded(view(stack({ action: "exchange_rate.set" }, { action: "memory.remember" }, { action: "task.retried" })));
  assert.deepEqual(out.visible.map((row) => row.action), ["exchange_rate.set", "memory.remember", "task.retried"]);
});

test("una acción desconocida es «Otros» y conserva su nombre original", () => {
  const row = asLoaded(view(stack({ action: "algo.rarisimo" }))).visible[0];
  assert.equal(row.category, "Otros");
  assert.equal(row.action, "algo.rarisimo");
});

test("task.failed ⇒ «Fallo»; task.completed NO se llama «OK», «Éxito» ni «Correcta»", () => {
  assert.equal(asLoaded(view(stack({ action: "task.failed" }))).visible[0].failed, true);
  assert.equal(asLoaded(view(stack({ action: "pipeline.step_error" }))).visible[0].failed, true);
  const done = asLoaded(view(stack({ action: "task.completed" })));
  assert.equal(done.visible[0].failed, false);
  assert.doesNotMatch(JSON.stringify(done), /"OK"|\bOK\b|Éxito|Exito|Correct[ao]|Sin error/);
  assert.equal(asLoaded(view(stack({ action: "task.retried" }))).visible[0].failed, false, "un reintento no es un fallo por su nombre");
});

// --- Actor y área ---------------------------------------------------------------------------------------------------------------

test("un agente conocido sale con su NOMBRE y su ÁREA (cfo ⇒ Finanzas, finance ⇒ Economía)", () => {
  const out = asLoaded(view(stack({ actor: "agent-product-1" }, { actor: "agent-cfo-1" }, { actor: "agent-finance-1" })));
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
  const row = asLoaded(view(stack({ actor: "ceo" }))).visible[0];
  assert.equal(row.actor.text, "Orquestador");
  assert.equal(row.area, null);
});

test("un actor con correo ⇒ «Persona»: la dirección no está en ningún texto de la vista", () => {
  const out = view(
    stack(
      { actor: "ivan.perez@example.com", resource: "user:ivan.perez@example.com" },
      { actor: "ops+test@acme.io", action: "incident.opened", resource: "incident:1" },
    ),
  );
  const row = asLoaded(out).visible[0];
  assert.equal(row.actor.text, "Persona");
  assert.equal(row.area, null);
  const text = JSON.stringify(out);
  assert.doesNotMatch(text, /@/, "ninguna dirección de correo en la vista");
  assert.doesNotMatch(text, /ivan|example\.com|acme/i);
});

test("un actor desconocido no inventa identidad ni área (nunca «Operaciones»)", () => {
  const out = asLoaded(view(stack({ actor: "scheduler" }, { actor: "agent-zzz-9" })));
  for (const row of out.visible) {
    assert.equal(row.area, null);
    assert.notEqual(row.actor.text, "Operaciones");
  }
  assert.equal(out.visible[1].actor.text, "agent-zzz-9", "el actor registrado, tal cual");
  assert.doesNotMatch(JSON.stringify(out), /Operaciones/);
});

test("un agente del registro cuyo rol no tiene área ⇒ sin área, no «Operaciones»", () => {
  const strange = { ...REGISTRY[0], id: "agent-strange-1", role: "alien" };
  const out = asLoaded(activityBlock({ audit: loaded(stack({ actor: "agent-strange-1" })), agents: loaded([strange]) }));
  assert.equal(out.visible[0].area, null);
  assert.equal(out.visible[0].actor.text, strange.name);
});

test("si el registro de agentes no se pudo leer, la actividad se enseña igual, sin nombres ni áreas, y lo dice", () => {
  const out = asLoaded(activityBlock({ audit: loaded(stack({ actor: "agent-product-1" })), agents: { kind: "error", message: "No se pudieron cargar los agentes." } }));
  assert.equal(out.visible[0].actor.text, "agent-product-1");
  assert.equal(out.visible[0].area, null);
  assert.match(out.agentsNote ?? "", /nombre y el área de los agentes no están disponibles/i);
  assert.equal(asLoaded(view(stack({}))).agentsNote, null);
});

// --- Procedencia ----------------------------------------------------------------------------------------------------------------

test("procedencia: fecha, actor, acción y recurso son registrados; categoría, área y fallo son derivados", () => {
  const row = asLoaded(view(stack({ actor: "agent-product-1", action: "task.failed" }))).visible[0];
  assert.deepEqual(row.provenance.recorded, ["created_at", "actor", "action", "resource"]);
  assert.deepEqual(row.provenance.derived, ["category", "area", "result"]);
  assert.equal(row.provenance.source, "audit_log");
  assert.equal(row.provenance.id, "a1");
  assert.doesNotMatch(JSON.stringify(row), /Verificad/);
});

// --- Corrección tras la primera misión real: el actor declarado no se presenta como una identidad ------------------------------------

const actorRow = (over: Partial<AuditEntry>) => asLoaded(view([entry("a0001", over)])).visible[0];

test("un actor `declared` (lo escribió quien llamó) se enseña «sin autenticar»: ni su nombre, ni su correo, ni «Persona»", () => {
  for (const actor of ["owner@amazona.local", "local-development", "someone"]) {
    const row = actorRow({ actor, actor_source: "declared" });
    assert.match(row.actor.text, /sin autenticar/);
    assert.doesNotMatch(JSON.stringify(row), /@|owner|propietario/i);
    assert.notEqual(row.actor.kind, "person", actor);
  }
});

test("el actor local sin autenticar tampoco se enseña como un usuario aunque el backend no mande la fuente", () => {
  assert.equal(actorRow({ actor: "local-development" }).actor.text, "Operador local (sin autenticar)");
});

test("un actor verificado (`token`) es «Persona», sin correo; los agentes y el orquestador no cambian", () => {
  const verified = actorRow({ actor: "ana@example.com", actor_source: "token" });
  assert.equal(verified.actor.text, "Persona");
  assert.doesNotMatch(JSON.stringify(verified), /@/);
  assert.equal(actorRow({ actor: "ceo" }).actor.text, "Orquestador");
  assert.equal(actorRow({ actor: "ceo", actor_source: "declared" }).actor.text, "Orquestador");
});

test("una fila sin fuente (agentes, historial anterior) no se inventa una: se conserva el comportamiento de siempre", () => {
  assert.equal(actorRow({ actor: "owner@amazona.local", actor_source: null }).actor.text, "Persona");
  assert.equal(actorRow({ actor: "memory" }).actor.text, "memory");
});
