import assert from "node:assert/strict";
import { test } from "node:test";
import type { Approval } from "./api.ts";
import { decision, project, task } from "./nexus-test-support.ts";
import {
  engineHud,
  engineView,
  initialEngineState,
  persistedMissionOf,
  reduceEngine,
  tasksOfView,
  type EngineEvent,
  type EngineState,
  type PersistedMission,
  type SessionMission,
} from "./nexus-engine-state.ts";
import type { MissionRead } from "./nexus-mission.ts";
import type { ReadState } from "./read-state.ts";

// La máquina de estados del Decision Engine (M47, Commit 4): qué se enseña de «la última misión registrada» cuando conviven la lectura
// PERSISTIDA y el resultado de la SESIÓN (la misión que se acaba de crear). Reglas fijadas por el propietario:
//   1. tras «Crear misión» puede enseñarse temporalmente el resultado de la sesión;
//   2. inmediatamente se dispara una relectura;
//   3. cuando la relectura persistida termina bien y contiene la misión, lo persistido es la fuente de verdad;
//   4. una lectura persistida más antigua NO pisa una misión recién creada;
//   5. una lectura con error NO borra un resultado de sesión válido, pero lo marca como no confirmado.

const apply = (events: EngineEvent[], from: EngineState = initialEngineState()): EngineState => events.reduce(reduceEngine, from);

const read = (over: Partial<MissionRead> & { id?: string } = {}): MissionRead => {
  const id = over.id ?? "p1";
  return {
    projects: { kind: "loaded", data: [project(id)] },
    project: project(id),
    decision: { kind: "loaded", data: decision(id) },
    tasks: { kind: "loaded", data: [task("t1", "COMPLETED"), task("t2", "PENDING")] },
    approval: { kind: "empty" },
    ...over,
  };
};

const persisted = (over: Partial<MissionRead> & { id?: string } = {}): PersistedMission => persistedMissionOf(read(over));
const session = (over: Partial<SessionMission> = {}): SessionMission => ({ projectId: "p2", projectName: "Misión nueva", decision: decision("p2"), ...over });
const failed = (message = "No se pudieron cargar las misiones."): PersistedMission => ({ kind: "error", message });
const EMPTY: PersistedMission = { kind: "empty" };

const viewOf = (state: EngineState) => engineView(state);

// --- Estado inicial y lecturas persistidas sin sesión --------------------------------------------------------------------------

test("al empezar, no se ha leído nada: `reading` (no «sin misiones» ni «sin decisión»)", () => {
  assert.equal(viewOf(initialEngineState()).kind, "reading");
});

test("persistido vacío ⇒ «none» (un hecho: no hay misiones); persistido con error ⇒ «error» (NO es «sin misiones»)", () => {
  const none = apply([{ type: "read_requested" }, { type: "read_result", seq: 1, mission: EMPTY }]);
  assert.equal(viewOf(none).kind, "none");
  const error = apply([{ type: "read_requested" }, { type: "read_result", seq: 1, mission: failed() }]);
  assert.equal(viewOf(error).kind, "error");
  assert.notEqual(viewOf(error).kind, "none");
});

test("persistido válido ⇒ misión CONFIRMADA con su proyecto, su decisión y sus tareas", () => {
  const state = apply([{ type: "read_requested" }, { type: "read_result", seq: 1, mission: persisted() }]);
  const view = viewOf(state);
  assert.equal(view.kind, "mission");
  if (view.kind !== "mission") return;
  assert.equal(view.source, "persisted");
  assert.equal(view.confirmed, true);
  assert.equal(view.project.name, "Misión p1");
  assert.equal(view.decision.kind, "loaded");
  assert.equal(view.tasks.kind, "loaded");
});

test("persistedMissionOf: proyectos vacíos ⇒ empty; error ⇒ error; unread ⇒ error (no hay lectura válida)", () => {
  assert.deepEqual(persistedMissionOf({ projects: { kind: "empty" }, project: null, decision: { kind: "unread", reason: "x" }, tasks: { kind: "unread", reason: "x" }, approval: { kind: "unread", reason: "x" } }), EMPTY);
  assert.equal(persistedMissionOf({ projects: { kind: "error", message: "m" }, project: null, decision: { kind: "unread", reason: "x" }, tasks: { kind: "unread", reason: "x" }, approval: { kind: "unread", reason: "x" } }).kind, "error");
});

// --- Sesión ↔ persistido (las cinco reglas) ----------------------------------------------------------------------------------------

test("REGLA 1: tras «Crear misión» se enseña el resultado de la sesión, NO confirmado, hasta que la lectura termine", () => {
  const state = apply([{ type: "read_requested" }, { type: "read_result", seq: 1, mission: persisted({ id: "p1" }) }, { type: "mission_created", session: session() }]);
  const view = viewOf(state);
  assert.equal(view.kind, "mission");
  if (view.kind !== "mission") return;
  assert.equal(view.source, "session");
  assert.equal(view.confirmed, false);
  assert.equal(view.reason, "reading");
  assert.equal(view.project.name, "Misión nueva");
  assert.equal(view.decision.kind, "loaded");
  assert.equal(view.tasks.kind, "unavailable", "las tareas solo existen en lo persistido: sin confirmar no hay progreso");
});

test("REGLA 2: crear una misión dispara una relectura (el sello pedido avanza)", () => {
  const before = apply([{ type: "read_requested" }, { type: "read_result", seq: 1, mission: persisted({ id: "p1" }) }]);
  const after = reduceEngine(before, { type: "mission_created", session: session() });
  assert.equal(after.requested, before.requested + 1);
});

test("REGLA 3: la relectura que contiene la misión nueva pasa a ser la verdad y la sesión se retira", () => {
  const mission = persistedMissionOf(read({ id: "p2", projects: { kind: "loaded", data: [project("p1", 600), project("p2", 1)] }, project: project("p2", 1) }));
  const state = apply([{ type: "mission_created", session: session() }, { type: "read_result", seq: 1, mission }]);
  assert.equal(state.session, null);
  const view = viewOf(state);
  assert.equal(view.kind === "mission" && view.source, "persisted");
  assert.equal(view.kind === "mission" && view.confirmed, true);
  assert.equal(view.kind === "mission" && view.project.name, "Misión p2");
  assert.equal(view.kind === "mission" && view.tasks.kind, "loaded");
});

test("REGLA 3 (bis): lo persistido manda aunque otra misión más nueva haya aparecido (la sesión solo adelantaba)", () => {
  const mission = persistedMissionOf(read({ id: "p3", projects: { kind: "loaded", data: [project("p2", 5), project("p3", 1)] }, project: project("p3", 1) }));
  const state = apply([{ type: "mission_created", session: session() }, { type: "read_result", seq: 1, mission }]);
  assert.equal(state.session, null);
  assert.equal(viewOf(state).kind === "mission" && viewOf(state).kind === "mission" && (viewOf(state) as { project: { name: string } }).project.name, "Misión p3");
});

test("REGLA 4: una lectura persistida ANTERIOR (sin la misión nueva) NO sobrescribe la sesión: queda «sin confirmar» por obsoleta", () => {
  const older = persisted({ id: "p1" });
  const state = apply([{ type: "mission_created", session: session() }, { type: "read_result", seq: 1, mission: older }]);
  assert.notEqual(state.session, null);
  const view = viewOf(state);
  assert.equal(view.kind === "mission" && view.source, "session");
  assert.equal(view.kind === "mission" && view.confirmed, false);
  assert.equal(view.kind === "mission" && view.reason, "stale");
  assert.equal(view.kind === "mission" && view.project.name, "Misión nueva");
});

test("REGLA 4 (bis): un persistido VACÍO tampoco borra la misión de la sesión", () => {
  const state = apply([{ type: "mission_created", session: session() }, { type: "read_result", seq: 1, mission: EMPTY }]);
  const view = viewOf(state);
  assert.equal(view.kind === "mission" && view.source, "session");
  assert.equal(view.kind === "mission" && view.reason, "stale");
});

test("REGLA 5: una lectura con ERROR no borra la sesión, pero la marca «persistencia no verificada»", () => {
  const state = apply([{ type: "mission_created", session: session() }, { type: "read_result", seq: 1, mission: failed() }]);
  const view = viewOf(state);
  assert.equal(view.kind === "mission" && view.source, "session");
  assert.equal(view.kind === "mission" && view.confirmed, false);
  assert.equal(view.kind === "mission" && view.reason, "error");
  assert.equal(view.kind === "mission" && view.project.name, "Misión nueva");
});

test("REGLA 5 (bis): tras un error, una relectura buena que contiene la misión la confirma", () => {
  const good = persistedMissionOf(read({ id: "p2", projects: { kind: "loaded", data: [project("p2", 1)] }, project: project("p2", 1) }));
  const state = apply([
    { type: "mission_created", session: session() },
    { type: "read_result", seq: 1, mission: failed() },
    { type: "read_requested" },
    { type: "read_result", seq: 2, mission: good },
  ]);
  assert.equal(state.session, null);
  assert.equal(viewOf(state).kind === "mission" && (viewOf(state) as { confirmed: boolean }).confirmed, true);
});

test("sin sesión, un error NO se convierte en «sin misiones» ni en misión anterior borrada en silencio: el estado dice error", () => {
  const state = apply([
    { type: "read_requested" },
    { type: "read_result", seq: 1, mission: persisted({ id: "p1" }) },
    { type: "read_requested" },
    { type: "read_result", seq: 2, mission: failed() },
  ]);
  assert.equal(viewOf(state).kind, "error");
});

// --- Respuestas fuera de orden ---------------------------------------------------------------------------------------------------

test("una respuesta VIEJA que llega tarde no pisa a la nueva (sellos)", () => {
  const newer = persisted({ id: "p2" });
  const older = persisted({ id: "p1" });
  const state = apply([
    { type: "read_requested" },
    { type: "read_requested" },
    { type: "read_result", seq: 2, mission: newer },
    { type: "read_result", seq: 1, mission: older },
  ]);
  assert.equal(viewOf(state).kind === "mission" && (viewOf(state) as { project: { name: string } }).project.name, "Misión p2");
});

test("una respuesta repetida o ya aplicada se ignora", () => {
  const first = apply([{ type: "read_requested" }, { type: "read_result", seq: 1, mission: persisted({ id: "p1" }) }]);
  const again = reduceEngine(first, { type: "read_result", seq: 1, mission: EMPTY });
  assert.equal(viewOf(again).kind, "mission");
});

test("una segunda misión después de una persistida: la sesión nueva gana a lo anterior hasta confirmarse", () => {
  const confirmed = apply([{ type: "read_requested" }, { type: "read_result", seq: 1, mission: persisted({ id: "p1" }) }]);
  const next = reduceEngine(confirmed, { type: "mission_created", session: session() });
  const view = viewOf(next);
  assert.equal(view.kind === "mission" && view.source, "session");
  assert.equal(view.kind === "mission" && view.project.name, "Misión nueva");
});

// --- Vista: decisión y tareas ------------------------------------------------------------------------------------------------------

test("vista: la decisión se enseña con su estado real y sus evidencias = `evidence.length`, sin reinterpretar", () => {
  const view = viewOf(apply([{ type: "read_requested" }, { type: "read_result", seq: 1, mission: persisted() }]));
  assert.equal(view.kind === "mission" && view.decision.kind === "loaded" && view.decision.status, "GO");
  assert.equal(view.kind === "mission" && view.decision.kind === "loaded" && view.decision.evidenceCount, 3);
});

test("vista: error de la decisión ⇒ «No disponible»; proyecto sin decisión ⇒ «Sin decisión registrada»; no son lo mismo", () => {
  const err = viewOf(apply([{ type: "read_result", seq: 1, mission: persisted({ decision: { kind: "error", message: "m" } }) }]));
  const none = viewOf(apply([{ type: "read_result", seq: 1, mission: persisted({ decision: { kind: "empty" } }) }]));
  assert.equal(err.kind === "mission" && err.decision.kind === "unavailable" && err.decision.text, "No disponible");
  assert.equal(none.kind === "mission" && none.decision.kind === "unavailable" && none.decision.text, "Sin decisión registrada");
});

test("vista: tareas con error ⇒ «No disponible»; sin tareas ⇒ «Sin tareas registradas»; ninguna da 0 %", () => {
  const err = viewOf(apply([{ type: "read_result", seq: 1, mission: persisted({ tasks: { kind: "error", message: "m" } }) }]));
  const none = viewOf(apply([{ type: "read_result", seq: 1, mission: persisted({ tasks: { kind: "empty" } }) }]));
  assert.equal(err.kind === "mission" && err.tasks.kind, "unavailable");
  assert.equal(none.kind === "mission" && none.tasks.kind, "none");
  assert.deepEqual(tasksOfView(err), null);
  assert.deepEqual(tasksOfView(none), null);
});

test("tasksOfView: las tareas del grafo son las de la misión persistida mostrada, y nunca las de una sesión sin confirmar", () => {
  const persistedView = viewOf(apply([{ type: "read_result", seq: 1, mission: persisted() }]));
  assert.equal(tasksOfView(persistedView)?.length, 2);
  const sessionView = viewOf(apply([{ type: "mission_created", session: session() }]));
  assert.equal(tasksOfView(sessionView), null);
});

// --- HUD y procedencia --------------------------------------------------------------------------------------------------------------

const hud = (state: EngineState, agents = { running: 0, total: 13 }, latencyMs: number | null = null, now = Date.parse("2026-10-15T12:00:00Z")) =>
  engineHud({ view: viewOf(state), agents, latencyMs, now });
const field = (h: ReturnType<typeof hud>, label: string) => {
  const f = h.fields.find((item) => item.label === label);
  assert.ok(f, `falta el campo «${label}»`);
  return f;
};
const CONFIRMED = () => apply([{ type: "read_requested" }, { type: "read_result", seq: 1, mission: persisted({ tasks: { kind: "loaded", data: [task("a", "COMPLETED"), task("b", "COMPLETED"), task("c", "PENDING"), task("d", "FAILED"), task("e", "CANCELLED")] } }) }]);

test("HUD: los rótulos aprobados — «Evidencias de la decisión» (NO «Eventos activos»), «Progreso» y «Proyecto» con nombre", () => {
  const h = hud(CONFIRMED(), { running: 0, total: 13 }, 1_000);
  assert.deepEqual(h.fields.map((f) => f.label), ["Última misión", "Tipo de decisión", "Evidencias de la decisión", "Progreso", "Agentes activos", "Latencia media"]);
  assert.doesNotMatch(JSON.stringify(h), /Eventos activos/);
  assert.equal(field(h, "Última misión").text, "Misión p1");
  assert.doesNotMatch(field(h, "Última misión").text, /^p1$|^dec-/);
});

test("HUD: «Evidencias de la decisión» es exactamente `evidence.length`", () => {
  const h = hud(CONFIRMED());
  assert.equal(field(h, "Evidencias de la decisión").text, "3");
  assert.equal(field(h, "Evidencias de la decisión").provenance, "derived");
});

test("HUD: «Progreso» sale SOLO de las tareas: 2 completadas de 4 relevantes (la CANCELLED fuera) = 50 %", () => {
  const f = field(hud(CONFIRMED()), "Progreso");
  assert.equal(f.text, "2 de 4 tareas · 50 %");
  assert.equal(f.provenance, "derived");
  assert.equal(hud(CONFIRMED()).progress, 0.5);
});

test("HUD: la confianza de la decisión NO alimenta el progreso (confianza 0,99 y 0 tareas completadas ⇒ 0 %, no 99 %)", () => {
  const state = apply([
    { type: "read_result", seq: 1, mission: persisted({ decision: { kind: "loaded", data: decision("p1", { confidence: 0.99 }) }, tasks: { kind: "loaded", data: [task("a", "PENDING"), task("b", "FAILED")] } }) },
  ]);
  const h = hud(state);
  assert.equal(h.progress, 0);
  assert.equal(field(h, "Progreso").text, "0 de 2 tareas · 0 %");
  assert.doesNotMatch(JSON.stringify(h), /99/);
});

test("HUD: sin tareas ⇒ «Sin dato» (no 0 %), con procedencia `unavailable`", () => {
  const h = hud(apply([{ type: "read_result", seq: 1, mission: persisted({ tasks: { kind: "empty" } }) }]));
  assert.equal(h.progress, null);
  assert.equal(field(h, "Progreso").text, "Sin dato");
  assert.equal(field(h, "Progreso").provenance, "unavailable");
  assert.doesNotMatch(field(h, "Progreso").text, /0 %/);
});

test("HUD: WAITING_APPROVAL y FAILED no cuentan como completadas ni se maquillan", () => {
  const h = hud(apply([{ type: "read_result", seq: 1, mission: persisted({ tasks: { kind: "loaded", data: [task("a", "COMPLETED"), task("b", "WAITING_APPROVAL"), task("c", "FAILED")] } }) }]));
  assert.equal(field(h, "Progreso").text, "1 de 3 tareas · 33 %");
});

test("HUD: procedencia de cada dato — proyecto y decisión `recorded`; evidencias, progreso, agentes y latencia `derived`; lo que falta `unavailable`", () => {
  const h = hud(CONFIRMED(), { running: 2, total: 13 }, 1_000);
  assert.deepEqual(
    h.fields.map((f) => [f.label, f.provenance]),
    [
      ["Última misión", "recorded"],
      ["Tipo de decisión", "recorded"],
      ["Evidencias de la decisión", "derived"],
      ["Progreso", "derived"],
      ["Agentes activos", "derived"],
      ["Latencia media", "derived"],
    ],
  );
  const sinLatencia = hud(CONFIRMED(), { running: 0, total: 13 }, null);
  assert.deepEqual([field(sinLatencia, "Latencia media").text, field(sinLatencia, "Latencia media").provenance], ["Sin dato", "unavailable"]);
});

test("HUD: ningún campo usa el coste, y ningún texto es una cifra de demostración", () => {
  const dump = JSON.stringify(hud(CONFIRMED()));
  assert.doesNotMatch(dump, /Coste|coste|€|AMZ-2026|68 %|estimad|aproximad/);
});

test("HUD: si la decisión no se pudo leer, las evidencias dicen «No disponible»; si no hay decisión registrada, «Sin dato»; nunca 0", () => {
  const err = hud(apply([{ type: "read_result", seq: 1, mission: persisted({ decision: { kind: "error", message: "m" } }) }]));
  assert.equal(field(err, "Tipo de decisión").text, "No disponible");
  assert.equal(field(err, "Evidencias de la decisión").text, "No disponible");
  const none = hud(apply([{ type: "read_result", seq: 1, mission: persisted({ decision: { kind: "empty" } }) }]));
  assert.equal(field(none, "Tipo de decisión").text, "Sin decisión registrada");
  assert.equal(field(none, "Evidencias de la decisión").text, "Sin dato");
  for (const h of [err, none]) assert.notEqual(field(h, "Evidencias de la decisión").text, "0");
});

test("HUD: sin misiones ⇒ «Sin misiones»; con error ⇒ «No disponible» con aviso; leyendo ⇒ «Leyendo…»; ninguno parece una misión ni un 0", () => {
  const none = hud(apply([{ type: "read_result", seq: 1, mission: EMPTY }]));
  assert.equal(field(none, "Última misión").text, "Sin misiones");
  assert.equal(field(none, "Progreso").text, "Sin dato");
  const err = hud(apply([{ type: "read_result", seq: 1, mission: failed() }]));
  assert.equal(field(err, "Última misión").text, "No disponible");
  assert.equal(err.notice?.tone, "error");
  assert.doesNotMatch(JSON.stringify(err), /Sin misiones|0 %/);
  const reading = hud(initialEngineState());
  assert.equal(field(reading, "Última misión").text, "Leyendo…");
});

test("HUD: un resultado de sesión sin confirmar lo dice (aviso) y no enseña progreso", () => {
  const h = hud(apply([{ type: "mission_created", session: session() }]));
  assert.match(h.notice?.text ?? "", /sin confirmar|no confirmad|pendiente de confirmar/i);
  assert.equal(h.progress, null);
  const stale = hud(apply([{ type: "mission_created", session: session() }, { type: "read_result", seq: 1, mission: persisted({ id: "p1" }) }]));
  assert.match(stale.notice?.text ?? "", /anterior|obsoleta/i);
  const err = hud(apply([{ type: "mission_created", session: session() }, { type: "read_result", seq: 1, mission: failed() }]));
  assert.match(err.notice?.text ?? "", /persistencia no verificada|no se pudo verificar/i);
});

test("HUD: el estado del núcleo no depende de la decisión (una decisión guardada no es «Ejecutando»)", () => {
  for (const status of ["GO", "NO_GO", "REVIEW", "HUMAN_APPROVAL"] as const) {
    const h = hud(apply([{ type: "read_result", seq: 1, mission: persisted({ decision: { kind: "loaded", data: decision("p1", { status }) } }) }]));
    assert.equal(h.coreStatus, "available", status);
  }
});

test("HUD: «Agentes activos» cuenta los del registro y «Latencia media» la del log; ambos derivados", () => {
  const h = hud(CONFIRMED(), { running: 3, total: 13 }, 1_250);
  assert.equal(field(h, "Agentes activos").text, "3 / 13");
  assert.match(field(h, "Latencia media").text, /1[.,]25|1,3|1250|1,2/);
});

test("el tipo de estado no admite una lectura `unread` como misión: `unread` ≠ vacío", () => {
  const unread: ReadState<unknown> = { kind: "unread", reason: "x" };
  assert.equal(persistedMissionOf({ projects: unread as never, project: null, decision: unread as never, tasks: unread as never, approval: unread as never }).kind, "error");
});

// --- TIPO de decisión ≠ ESTADO de aprobación (corrección tras la primera misión real) ------------------------------------------------

const NOW_MS = Date.parse("2026-10-18T18:00:00Z");
const approvalRow = (over: Partial<Approval> = {}): Approval => ({
  id: "ap1",
  decision_id: "dec-p1",
  action: "simulated_external_spend",
  amount: 1,
  status: "PENDING",
  expires_at: "2026-10-19T16:28:11Z",
  resolved_at: null,
  resolved_by: null,
  requested_at: "2026-10-18T16:28:11Z",
  ...over,
});
const humanMission = (approval: ReadState<Approval>) =>
  apply([
    { type: "read_requested" },
    { type: "read_result", seq: 1, mission: persisted({ decision: { kind: "loaded", data: decision("p1", { status: "HUMAN_APPROVAL" }) }, approval }) },
  ]);
const hudAt = (state: EngineState, now = NOW_MS) => hud(state, { running: 0, total: 13 }, null, now);

test("HUD: el tipo `HUMAN_APPROVAL` sigue siendo «Requiere aprobación humana» aunque la aprobación esté APROBADA, y es un campo aparte del estado", () => {
  const h = hudAt(humanMission({ kind: "loaded", data: approvalRow({ status: "APPROVED", resolved_at: "2026-10-18T16:29:25Z", resolved_by: "local-development" }) }));
  assert.equal(field(h, "Tipo de decisión").text, "Requiere aprobación humana (HUMAN_APPROVAL)");
  assert.match(field(h, "Tipo de decisión").note ?? "", /no cambia cuando se resuelve su aprobación/);
  assert.equal(field(h, "Aprobación").text, "Aprobada · 18 oct 2026 · 16:29 UTC");
  assert.doesNotMatch(field(h, "Aprobación").text, /pendiente/i, "una aprobación aprobada no se presenta como pendiente");
  assert.equal(field(h, "Aprobación").provenance, "recorded");
});

test("HUD: pendiente (con su vencimiento), rechazada, vencida y cancelada, cada una con su texto y su fecha real", () => {
  assert.equal(field(hudAt(humanMission({ kind: "loaded", data: approvalRow() })), "Aprobación").text, "Pendiente · 19 oct 2026 · 16:28 UTC");
  assert.equal(field(hudAt(humanMission({ kind: "loaded", data: approvalRow({ status: "REJECTED", resolved_at: "2026-10-18T17:00:00Z" }) })), "Aprobación").text, "Rechazada · 18 oct 2026 · 17:00 UTC");
  assert.equal(field(hudAt(humanMission({ kind: "loaded", data: approvalRow({ status: "EXPIRED", resolved_at: "2026-10-19T16:30:00Z" }) })), "Aprobación").text, "Vencida · 19 oct 2026 · 16:30 UTC");
  assert.equal(field(hudAt(humanMission({ kind: "loaded", data: approvalRow({ status: "CANCELLED" }) })), "Aprobación").text, "Cancelada");
});

test("HUD: una aprobación PENDING con el vencimiento pasado se dice «Vencida sin resolver»", () => {
  const h = hudAt(humanMission({ kind: "loaded", data: approvalRow({ expires_at: "2026-10-18T10:00:00Z" }) }));
  assert.equal(field(h, "Aprobación").text, "Vencida sin resolver · 18 oct 2026 · 10:00 UTC");
});

test("HUD: la fecha de solicitud, la de resolución y la de vencimiento no se confunden", () => {
  const h = hudAt(humanMission({ kind: "loaded", data: approvalRow({ status: "APPROVED", requested_at: "2026-10-18T16:28:11Z", resolved_at: "2026-10-18T16:29:25Z", expires_at: "2026-10-19T16:28:11Z" }) }));
  assert.match(field(h, "Aprobación").text, /16:29 UTC/);
  assert.match(field(h, "Aprobación").note ?? "", /Solicitada 18 oct 2026 · 16:28 UTC/);
  assert.doesNotMatch(field(h, "Aprobación").text, /19 oct/);
});

test("HUD: una aprobación que no se pudo leer es «No disponible»; una decisión que la pide y no la tiene dice «Sin aprobación registrada»", () => {
  assert.equal(field(hudAt(humanMission({ kind: "error", message: "x" })), "Aprobación").text, "No disponible");
  assert.equal(field(hudAt(humanMission({ kind: "unread", reason: "x" })), "Aprobación").provenance, "unavailable");
  assert.equal(field(hudAt(humanMission({ kind: "empty" })), "Aprobación").text, "Sin aprobación registrada");
});

test("HUD: una decisión que no pide aprobación (GO, NO_GO, REVIEW) no tiene campo «Aprobación»", () => {
  for (const status of ["GO", "NO_GO", "REVIEW"] as const) {
    const state = apply([{ type: "read_requested" }, { type: "read_result", seq: 1, mission: persisted({ decision: { kind: "loaded", data: decision("p1", { status }) } }) }]);
    assert.equal(hudAt(state).fields.some((f) => f.label === "Aprobación"), false, status);
  }
});

test("la misión recién creada en esta sesión no sabe el estado de su aprobación: «Sin confirmar»", () => {
  const session = apply([{ type: "mission_created", session: { projectId: "p1", projectName: "x", decision: decision("p1", { status: "HUMAN_APPROVAL" }) } }]);
  assert.equal(field(hudAt(session), "Aprobación").text, "Sin confirmar");
});
