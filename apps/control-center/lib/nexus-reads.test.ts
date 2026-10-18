import assert from "node:assert/strict";
import { test } from "node:test";
import type { Agent, AgentExecution } from "./api.ts";
import { readNexus, type NexusSource } from "./nexus-reads.ts";
import { buildGraph } from "./neural-nexus.ts";
import { decision, project, task } from "./nexus-test-support.ts";
import { listOf } from "./read-state.ts";
import { agent, execution, FAILURES, INVALID_PAYLOADS, NOW, TECHNICAL } from "./read-test-support.ts";

// Las lecturas del grafo de agentes (M47, Commit 1 y 4). Un fallo NUNCA es una lista vacía: de una lista vacía salía el roster
// de demostración con «13 Disponible». Desde el Commit 4 el grafo lee además la ÚLTIMA MISIÓN REGISTRADA (proyecto → decisión + tareas),
// cada lectura con su estado.

const ok = <T>(value: T) => async () => value;
const source = (agents: () => Promise<unknown>, executions: () => Promise<unknown>, over: Partial<NexusSource> = {}): NexusSource => ({
  listAgents: agents as NexusSource["listAgents"],
  listAgentExecutions: executions as NexusSource["listAgentExecutions"],
  listProjects: async () => [],
  listDecisionsForProject: async () => [],
  listTasks: async () => [],
  listApprovals: async () => [],
  ...over,
});

test("un fallo del registro de agentes es `error`, jamás una lista vacía", async () => {
  for (const [name, make] of Object.entries(FAILURES)) {
    const reads = await readNexus(
      source(async () => { throw make(); }, ok<AgentExecution[]>([execution("e1", "a1")])),
    );
    assert.equal(reads.agents.kind, "error", name);
    assert.equal(listOf(reads.agents), null, `${name}: un fallo no puede leerse como lista`);
    if (reads.agents.kind === "error") assert.doesNotMatch(reads.agents.message, TECHNICAL, name);
  }
});

test("una respuesta con la forma equivocada es `error`, no «registro vacío»", async () => {
  for (const [name, payload] of INVALID_PAYLOADS) {
    const reads = await readNexus(source(ok(payload), ok<AgentExecution[]>([])));
    assert.equal(reads.agents.kind, "error", name);
    assert.equal(listOf(reads.agents), null, name);
  }
});

test("el registro vacío es `empty` (un hecho) y no se parece a un error", async () => {
  const reads = await readNexus(source(ok<Agent[]>([]), ok<AgentExecution[]>([])));
  assert.equal(reads.agents.kind, "empty");
  assert.deepEqual(listOf(reads.agents), []);
});

test("agentes bien y ejecuciones fallidas: los agentes son `loaded` y las ejecuciones `error`, no `[]`", async () => {
  for (const [name, make] of Object.entries(FAILURES)) {
    const reads = await readNexus(source(ok([agent("a1")]), async () => { throw make(); }));
    assert.equal(reads.agents.kind, "loaded", name);
    assert.equal(reads.executions.kind, "error", name);
    assert.equal(listOf(reads.executions), null, name);
  }
});

test("las ejecuciones que no se pudieron leer dejan las métricas de ejecución sin valor, no en cero", async () => {
  const reads = await readNexus(source(ok([agent("a1")]), async () => { throw FAILURES["500"](); }));
  const agents = listOf(reads.agents)!;
  const { nodes } = buildGraph({ agents, executions: listOf(reads.executions), tasks: null, now: NOW });
  const node = nodes.find((n) => n.id === "a1")!;
  assert.equal(node.metrics?.runs, undefined);
  assert.equal(node.metrics !== undefined && "costToday" in node.metrics, false);
});

test("lecturas válidas: loaded con su contenido", async () => {
  const reads = await readNexus(source(ok([agent("a1"), agent("a2")]), ok([execution("e1", "a1")])));
  assert.equal(reads.agents.kind, "loaded");
  assert.equal(reads.executions.kind, "loaded");
  assert.equal(listOf(reads.agents)?.length, 2);
});

// --- La última misión registrada ---------------------------------------------------------------------------------------------

test("readNexus también lee la última misión registrada: proyecto, decisión y tareas, una vez cada una", async () => {
  const calls: string[] = [];
  const reads = await readNexus(
    source(ok([agent("a1")]), ok<AgentExecution[]>([]), {
      listProjects: async () => (calls.push("projects"), [project("old", 900), project("new", 3)]),
      listDecisionsForProject: async (id: string) => (calls.push(`decisions:${id}`), [decision(id)]),
      listTasks: async (id: string) => (calls.push(`tasks:${id}`), [task("t1", "COMPLETED")]),
    }),
  );
  assert.deepEqual(calls.sort(), ["decisions:new", "projects", "tasks:new"]);
  assert.equal(reads.mission.project?.id, "new");
  assert.equal(reads.mission.decision.kind, "loaded");
  assert.equal(reads.mission.tasks.kind, "loaded");
});

test("un fallo de la misión NO rompe el registro ni las ejecuciones, y NO es «sin misiones»", async () => {
  for (const [name, make] of Object.entries(FAILURES)) {
    const reads = await readNexus(
      source(ok([agent("a1")]), ok<AgentExecution[]>([]), {
        listProjects: async () => {
          throw make();
        },
      }),
    );
    assert.equal(reads.agents.kind, "loaded", name);
    assert.equal(reads.executions.kind, "empty", name);
    assert.equal(reads.mission.projects.kind, "error", name);
    assert.notEqual(reads.mission.projects.kind, "empty", name);
  }
});

test("un fallo de la decisión o de las tareas de la última misión es `error` de esa parte (no «sin decisión», no 0 tareas)", async () => {
  const withFailure = (over: Partial<NexusSource>) =>
    readNexus(
      source(ok([agent("a1")]), ok<AgentExecution[]>([]), {
        listProjects: async () => [project("p1")],
        listDecisionsForProject: async () => [decision("p1")],
        listTasks: async () => [task("t1", "COMPLETED")],
        ...over,
      }),
    );
  const noDecision = await withFailure({ listDecisionsForProject: async () => { throw FAILURES["500"](); } });
  assert.equal(noDecision.mission.decision.kind, "error");
  assert.equal(noDecision.mission.tasks.kind, "loaded");
  const noTasks = await withFailure({ listTasks: async () => { throw FAILURES["503"](); } });
  assert.equal(noTasks.mission.tasks.kind, "error");
  assert.equal(noTasks.mission.decision.kind, "loaded");
});

test("sin proyectos: `empty` (un hecho) y no se piden decisiones ni tareas", async () => {
  let more = 0;
  const reads = await readNexus(
    source(ok([agent("a1")]), ok<AgentExecution[]>([]), {
      listDecisionsForProject: async () => (more++, []),
      listTasks: async () => (more++, []),
    }),
  );
  assert.equal(reads.mission.projects.kind, "empty");
  assert.equal(more, 0);
});
