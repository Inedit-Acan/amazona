import assert from "node:assert/strict";
import { test } from "node:test";
import type { TaskStatus } from "./api.ts";
import { agent, decision, fakeMissionSource, project, task } from "./nexus-test-support.ts";
import {
  decisionsContract,
  latestProject,
  projectsContract,
  readMission,
  relatedTasks,
  taskDependencyEdges,
  taskProgress,
  tasksContract,
} from "./nexus-mission.ts";
import type { ReadState } from "./read-state.ts";
import { FAILURES, INVALID_PAYLOADS, TECHNICAL } from "./read-test-support.ts";

// LA ÚLTIMA MISIÓN REGISTRADA y sus tareas (M47, Commit 4). Criterio estructural, verificado en el backend: el ÚNICO sitio que crea un
// `Project` es `CEOOrchestrator.run_objective` (se invoca solo desde `POST /api/objectives/{id}/run`) y ahí se crean, en una misma
// transacción, el proyecto, sus tareas y su decisión: un proyecto confirmado siempre tiene decisión. Por eso «la última misión» es el
// proyecto más reciente por `created_at`; la API no distingue quién la lanzó (la pantalla, la API o un script), así que se llama
// «última misión registrada», no «la que lanzó este botón».

const asLoaded = <T>(data: T[]): ReadState<T[]> => ({ kind: "loaded", data });
const bad = (state: ReadState<unknown>) => {
  assert.equal(state.kind, "error");
  return state.kind === "error" ? state.message : "";
};

// --- Criterio de «última» --------------------------------------------------------------------------------------------------

test("latestProject: el más reciente por `created_at`, sin fiarse del orden de la API", () => {
  const list = [project("old", 300), project("new", 5), project("mid", 60)];
  assert.equal(latestProject(list)?.id, "new");
  assert.equal(latestProject([...list].reverse())?.id, "new");
  assert.equal(latestProject([]), null);
});

test("latestProject: con la misma fecha desempata el id mayor (determinista)", () => {
  const a = project("a", 10);
  const b = project("b", 10, { created_at: a.created_at });
  assert.equal(latestProject([a, b])?.id, "b");
  assert.equal(latestProject([b, a])?.id, "b");
});

test("latestProject: una fecha sin zona se interpreta como UTC (el backend en SQLite la devuelve así)", () => {
  const sinZona = project("sz", 0, { created_at: "2026-10-15T12:30:00" });
  const conZona = project("cz", 0, { created_at: "2026-10-15T12:29:00+00:00" });
  assert.equal(latestProject([conZona, sinZona])?.id, "sz");
});

// --- Contratos -------------------------------------------------------------------------------------------------------------

test("proyectos: una fila sin id, sin nombre o con una fecha ilegible rompe la lectura (error, no «sin misiones»)", () => {
  for (const over of [{ id: "" }, { name: "" }, { created_at: "ayer" }, { created_at: null as never }]) {
    assert.match(bad(projectsContract(asLoaded([project("ok"), project("x", 5, over)]))), /misiones/, JSON.stringify(over));
  }
  assert.equal(projectsContract(asLoaded([project("ok")])).kind, "loaded");
  for (const state of [{ kind: "empty" }, { kind: "error", message: "m" }, { kind: "unread", reason: "r" }] as const) {
    assert.deepEqual(projectsContract(state), state);
  }
});

test("decisiones: estado desconocido o evidencias que no son una lista rompen la lectura", () => {
  for (const over of [{ status: "MAYBE" as never }, { evidence: null as never }, { evidence: [{ summary: "x" }] as never }, { id: "" }]) {
    assert.match(bad(decisionsContract(asLoaded([decision("p1", over)]))), /decisi/, JSON.stringify(over));
  }
  assert.equal(decisionsContract(asLoaded([decision("p1")])).kind, "loaded");
});

test("tareas: estado desconocido (incluido BLOCKED, que el backend no envía), capacidad vacía o `depends_on` que no es una lista rompen la lectura", () => {
  for (const over of [{ status: "BLOCKED" as never }, { status: "DONE" as never }, { capability: "" }, { depends_on: "x" as never }, { depends_on: undefined as never }, { id: "" }]) {
    assert.match(bad(tasksContract(asLoaded([task("t1", "COMPLETED"), task("t2", "PENDING", "x", over)]))), /tareas/, JSON.stringify(over));
  }
  assert.equal(tasksContract(asLoaded([task("t1", "COMPLETED")])).kind, "loaded");
});

// --- Progreso (D-4-2) ------------------------------------------------------------------------------------------------------

const STATUSES: TaskStatus[] = ["PENDING", "QUEUED", "RUNNING", "WAITING", "WAITING_APPROVAL", "COMPLETED", "FAILED", "CANCELLED"];

test("progreso: COMPLETED / tareas no CANCELLED; entran PENDING, QUEUED, RUNNING, WAITING, WAITING_APPROVAL, COMPLETED y FAILED", () => {
  const all = STATUSES.map((status, i) => task(`t${i}`, status));
  const p = taskProgress(all);
  assert.deepEqual(p && { total: p.total, completed: p.completed }, { total: 7, completed: 1 });
  assert.equal(p?.fraction, 1 / 7);
});

test("progreso: CANCELLED queda fuera del denominador", () => {
  const p = taskProgress([task("a", "COMPLETED"), task("b", "CANCELLED"), task("c", "CANCELLED")]);
  assert.deepEqual(p && { total: p.total, completed: p.completed, fraction: p.fraction }, { total: 1, completed: 1, fraction: 1 });
});

test("progreso: FAILED NO cuenta como completada y WAITING_APPROVAL tampoco", () => {
  const failed = taskProgress([task("a", "COMPLETED"), task("b", "FAILED")]);
  assert.equal(failed?.completed, 1);
  assert.equal(failed?.fraction, 0.5);
  const waiting = taskProgress([task("a", "COMPLETED"), task("b", "WAITING_APPROVAL")]);
  assert.equal(waiting?.completed, 1);
  assert.equal(waiting?.fraction, 0.5);
  assert.equal(taskProgress([task("a", "FAILED"), task("b", "WAITING_APPROVAL")])?.fraction, 0, "0 es un hecho cuando hay tareas y ninguna está completada");
});

test("progreso: sin tareas, o solo CANCELLED ⇒ `null` (Sin dato), NUNCA 0 %", () => {
  assert.equal(taskProgress([]), null);
  assert.equal(taskProgress([task("a", "CANCELLED")]), null);
});

test("progreso: todas las combinaciones de estado de una tarea contra una COMPLETED", () => {
  for (const status of STATUSES) {
    const p = taskProgress([task("done", "COMPLETED"), task("other", status)]);
    if (status === "CANCELLED") assert.deepEqual(p && [p.total, p.completed], [1, 1], status);
    else if (status === "COMPLETED") assert.deepEqual(p && [p.total, p.completed], [2, 2], status);
    else assert.deepEqual(p && [p.total, p.completed], [2, 1], status);
  }
});

test("progreso: la confianza de la decisión NO interviene: misma lista de tareas, mismo progreso con cualquier `confidence`", () => {
  const tasks = [task("a", "COMPLETED"), task("b", "PENDING"), task("c", "PENDING"), task("d", "RUNNING")];
  assert.equal(taskProgress(tasks)?.fraction, 0.25);
  assert.equal(taskProgress.length, 1, "taskProgress solo recibe tareas");
});

// --- Tareas relacionadas por capacidad (NO asignadas) -------------------------------------------------------------------------

test("relatedTasks: empareja por capacidad exacta y SOLO por capacidad", () => {
  const a = agent("a-product", ["market_validation"]);
  const tasks = [task("t1", "COMPLETED", "market_validation"), task("t2", "FAILED", "legal_validation"), task("t3", "PENDING", "market_validation_extra")];
  assert.deepEqual(relatedTasks(a, tasks).map((t) => t.id), ["t1"]);
  assert.deepEqual(relatedTasks(agent("x", []), tasks), []);
});

test("relatedTasks: el resultado no se llama «asignada»: la tarea no trae ningún agente y la función no lo inventa", () => {
  const t = task("t1", "COMPLETED", "market_validation");
  assert.equal("assigned_agent_id" in t, false);
  assert.equal(relatedTasks(agent("a", ["market_validation"]), [t])[0], t);
});

// --- Dependencias reales (D-4-4) ------------------------------------------------------------------------------------------------

const REGISTRY = [
  agent("a-product", ["market_validation"], "product"),
  agent("a-supplier", ["supplier_sourcing"], "supplier"),
  agent("a-finance", ["financial_validation"], "finance"),
  agent("a-legal", ["legal_validation"], "legal"),
];

test("dependencias: solo salen de `depends_on` de tareas reales, entre los dominios de sus capacidades", () => {
  const tasks = [
    task("t-product", "COMPLETED", "market_validation"),
    task("t-supplier", "COMPLETED", "supplier_sourcing", { depends_on: ["t-product"] }),
    task("t-finance", "COMPLETED", "financial_validation", { depends_on: ["t-product", "t-supplier"] }),
  ];
  const edges = taskDependencyEdges(tasks, REGISTRY);
  assert.deepEqual(
    edges.map((e) => `${e.source}→${e.target}`),
    ["Investigación→Abastecimiento", "Investigación→Economía", "Abastecimiento→Economía"],
  );
});

test("dependencias: sin `depends_on` NO se dibuja nada (ni por similitud de dominio ni de capacidad)", () => {
  const tasks = [task("a", "COMPLETED", "market_validation"), task("b", "COMPLETED", "supplier_sourcing"), task("c", "COMPLETED", "legal_validation")];
  assert.deepEqual(taskDependencyEdges(tasks, REGISTRY), []);
  assert.deepEqual(taskDependencyEdges([], REGISTRY), []);
});

test("dependencias: una capacidad sin agente (decision_synthesis), un padre inexistente o dos tareas del mismo dominio no dibujan nada", () => {
  const tasks = [
    task("p", "COMPLETED", "market_validation"),
    task("s", "COMPLETED", "decision_synthesis", { depends_on: ["p"] }),
    task("g", "COMPLETED", "supplier_sourcing", { depends_on: ["no-existe"] }),
    task("p2", "COMPLETED", "market_validation", { depends_on: ["p"] }),
  ];
  assert.deepEqual(taskDependencyEdges(tasks, REGISTRY), []);
});

test("dependencias: una capacidad que pertenece a agentes de dos dominios es ambigua y no se dibuja", () => {
  const shared = [agent("x", ["shared"], "product"), agent("y", ["shared"], "legal"), agent("z", ["market_validation"], "product")];
  const tasks = [task("p", "COMPLETED", "market_validation"), task("c", "COMPLETED", "shared", { depends_on: ["p"] })];
  assert.deepEqual(taskDependencyEdges(tasks, shared), []);
  // Con el padre en el OTRO dominio de la capacidad ambigua, elegir uno cualquiera de los dos dibujaría una línea que nadie sabe si es cierta.
  const legalParent = [task("p", "COMPLETED", "legal_validation"), task("c", "COMPLETED", "shared", { depends_on: ["p"] })];
  assert.deepEqual(taskDependencyEdges(legalParent, [...shared, agent("w", ["legal_validation"], "legal")]), []);
  const sharedParent = [task("p", "COMPLETED", "shared"), task("c", "COMPLETED", "legal_validation", { depends_on: ["p"] })];
  assert.deepEqual(taskDependencyEdges(sharedParent, [...shared, agent("w", ["legal_validation"], "legal")]), []);
});

test("dependencias: sin duplicados y en un orden determinista", () => {
  const tasks = [
    task("p", "COMPLETED", "market_validation"),
    task("s1", "COMPLETED", "supplier_sourcing", { depends_on: ["p"] }),
    task("s2", "COMPLETED", "supplier_sourcing", { depends_on: ["p"] }),
  ];
  assert.equal(taskDependencyEdges(tasks, REGISTRY).length, 1);
  assert.deepEqual(taskDependencyEdges([...tasks].reverse(), REGISTRY), taskDependencyEdges(tasks, REGISTRY));
});

// --- Lectura de la cadena proyecto → decisión + tareas -----------------------------------------------------------------------------

test("readMission: lee los proyectos y, del ÚLTIMO, su decisión y sus tareas, una vez cada una", async () => {
  const source = fakeMissionSource({
    projects: [project("old", 600), project("new", 5)],
    decisions: { new: [decision("new")], old: [decision("old")] },
    tasks: { new: [task("t1", "COMPLETED")], old: [task("t0", "COMPLETED")] },
  });
  const read = await readMission(source);
  assert.deepEqual(source.calls, { listProjects: 1, listDecisionsForProject: 1, listTasks: 1 });
  assert.deepEqual(source.args, { listDecisionsForProject: ["new"], listTasks: ["new"] });
  assert.equal(read.project?.id, "new");
  assert.equal(read.decision.kind, "loaded");
  assert.equal(read.tasks.kind, "loaded");
});

test("readMission: sin proyectos ⇒ `empty` y no se lee nada más", async () => {
  const source = fakeMissionSource({ projects: [] });
  const read = await readMission(source);
  assert.equal(read.projects.kind, "empty");
  assert.equal(read.project, null);
  assert.deepEqual(source.calls, { listProjects: 1, listDecisionsForProject: 0, listTasks: 0 });
});

test("readMission: un fallo de proyectos es `error` (jamás «sin misiones») y no se lee nada más", async () => {
  for (const [name, make] of Object.entries(FAILURES)) {
    const source = fakeMissionSource({}, { listProjects: make });
    const read = await readMission(source);
    assert.equal(read.projects.kind, "error", name);
    assert.equal(read.project, null, name);
    assert.equal(read.decision.kind, "unread", `${name}: sin proyectos leídos no se sabe nada de la decisión (no es «sin decisión»)`);
    assert.equal(read.tasks.kind, "unread", `${name}: ni de las tareas (no es «sin tareas»)`);
    assert.equal(source.calls.listDecisionsForProject + source.calls.listTasks, 0, name);
    if (read.projects.kind === "error") assert.doesNotMatch(read.projects.message, TECHNICAL, name);
  }
});

test("readMission: una respuesta de proyectos que no es una lista es `error`", async () => {
  for (const [name, payload] of INVALID_PAYLOADS) {
    const source = fakeMissionSource();
    source.listProjects = (async () => payload) as never;
    assert.equal((await readMission(source)).projects.kind, "error", name);
  }
});

test("readMission: un fallo de la decisión o de las tareas rompe SOLO esa parte (error, no «sin decisión» ni 0 tareas)", async () => {
  const data = { projects: [project("p1")], decisions: { p1: [decision("p1")] }, tasks: { p1: [task("t1", "COMPLETED")] } };
  const noDecision = await readMission(fakeMissionSource(data, { listDecisionsForProject: FAILURES["500"] }));
  assert.equal(noDecision.decision.kind, "error");
  assert.equal(noDecision.tasks.kind, "loaded");
  const noTasks = await readMission(fakeMissionSource(data, { listTasks: FAILURES["503"] }));
  assert.equal(noTasks.tasks.kind, "error");
  assert.equal(noTasks.decision.kind, "loaded");
});

test("readMission: proyecto sin decisión ⇒ `empty` de la decisión (un hecho), y más de una decisión ⇒ error de contrato", async () => {
  const none = await readMission(fakeMissionSource({ projects: [project("p1")], tasks: { p1: [task("t1", "PENDING")] } }));
  assert.equal(none.decision.kind, "empty");
  const many = await readMission(fakeMissionSource({ projects: [project("p1")], decisions: { p1: [decision("p1"), decision("p1", { id: "otra" })] } }));
  assert.equal(many.decision.kind, "error");
});

test("readMission: contrato roto en una tarea ⇒ error de tareas; en un proyecto ⇒ error de proyectos", async () => {
  const brokenTask = await readMission(fakeMissionSource({ projects: [project("p1")], tasks: { p1: [task("t1", "BLOCKED" as never)] } }));
  assert.equal(brokenTask.tasks.kind, "error");
  const brokenProject = await readMission(fakeMissionSource({ projects: [project("p1", 5, { name: "" })] }));
  assert.equal(brokenProject.projects.kind, "error");
});
