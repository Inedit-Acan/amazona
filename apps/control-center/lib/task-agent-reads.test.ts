import assert from "node:assert/strict";
import { test } from "node:test";
import type { Agent, AgentRelation, Project, Task } from "./api.ts";
import { readMissionTaskAgents, taskAgentPanel, type MissionTasksSource } from "./task-agent-reads.ts";
import { unreadState } from "./read-state.ts";

// La lectura y el panel de «Tareas y agentes» de la última misión (M47/M48). Lo que fijan: UNA lectura de proyectos y UNA de tareas (de la última
// misión), un fallo es `error` (nunca «sin tareas»), un contrato roto también, y el panel cuenta solo lo que el backend dijo.

const project = (id: string, createdAt: string, name = `misión ${id}`): Project => ({ id, objective_id: `o-${id}`, name, status: "VALIDATING", created_at: createdAt }) as Project;
const relation = (status: AgentRelation["status"], over: Partial<AgentRelation> = {}): AgentRelation => ({
  status,
  assigned_agent_id: null,
  assigned_agent_known: null,
  executed_by_agent_id: null,
  reassigned: false,
  executions: [],
  ...over,
});
const task = (id: string, over: Partial<Task> = {}): Task => ({
  id,
  project_id: "p-new",
  name: `tarea ${id}`,
  capability: "market_validation",
  status: "COMPLETED",
  input: null,
  output: null,
  error: null,
  depends_on: [],
  agent_relation: relation("ORCHESTRATOR"),
  ...over,
});
const agents: Agent[] = [{ id: "agent-product-1", name: "Product Validation Agent", role: "x", capabilities: ["market_validation"], status: "AVAILABLE", reliability_score: 1, version: "1", cost_profile: {} }];

function source(over: Partial<MissionTasksSource> & { calls?: string[] } = {}): MissionTasksSource {
  const calls = over.calls ?? [];
  return {
    listProjects:
      over.listProjects ??
      (async () => {
        calls.push("projects");
        return [project("p-old", "2026-10-18T10:00:00Z"), project("p-new", "2026-10-20T10:00:00Z")];
      }),
    listTasks:
      over.listTasks ??
      (async (id: string) => {
        calls.push(`tasks:${id}`);
        return [task("t1")];
      }),
  };
}

test("lee los proyectos una vez y las tareas SOLO de la última misión", async () => {
  const calls: string[] = [];
  const state = await readMissionTaskAgents(source({ calls }));

  assert.deepEqual(calls, ["projects", "tasks:p-new"]);
  assert.equal(state.kind, "loaded");
  assert.equal(state.kind === "loaded" && state.data.project.id, "p-new");
});

test("sin misiones es `empty` (un hecho) y no se piden tareas", async () => {
  const calls: string[] = [];
  const state = await readMissionTaskAgents(source({ calls, listProjects: async () => [] }));

  assert.equal(state.kind, "empty");
  assert.deepEqual(calls, []);
});

test("una misión sin tareas es `empty`", async () => {
  const state = await readMissionTaskAgents(source({ listTasks: async () => [] }));
  assert.equal(state.kind, "empty");
});

test("un fallo al leer los proyectos es `error`, nunca «sin misiones»", async () => {
  const state = await readMissionTaskAgents(
    source({
      listProjects: async () => {
        throw new Error("fetch failed");
      },
    }),
  );
  assert.equal(state.kind, "error");
  assert.doesNotMatch(state.kind === "error" ? state.message : "", /fetch failed|ECONNREFUSED/);
});

test("un fallo al leer las tareas es `error`, nunca «sin tareas» ni una lista de «Sin asignar»", async () => {
  const state = await readMissionTaskAgents(
    source({
      listTasks: async () => {
        throw new Error("boom");
      },
    }),
  );
  assert.equal(state.kind, "error");
});

test("un contrato de tareas roto (estado que no existe) es `error`", async () => {
  const state = await readMissionTaskAgents(source({ listTasks: async () => [task("t", { status: "WEIRD" as Task["status"] })] }));
  assert.equal(state.kind, "error");
});

test("el panel cuenta lo que dijo el backend: asignadas, ejecutadas, desviaciones, sin relación e inconsistencias", async () => {
  const tasks = [
    task("a", { agent_relation: relation("MATCH", { assigned_agent_id: "agent-product-1", assigned_agent_known: true, executed_by_agent_id: "agent-product-1", executions: [{ source: "execution_log", execution_id: "e", agent_id: "agent-product-1", agent_known: true, success: true, attempt: 1, assigned_agent_id: "agent-product-1", started_at: null, completed_at: null, created_at: "2026-10-20T10:00:00Z" }] }) }),
    task("b", { status: "PENDING", agent_relation: relation("ASSIGNED", { assigned_agent_id: "agent-product-1", assigned_agent_known: true }) }),
    task("c", { agent_relation: relation("MISMATCH", { assigned_agent_id: "agent-product-1", assigned_agent_known: true, executed_by_agent_id: "agent-other", executions: [{ source: "execution_log", execution_id: "e2", agent_id: "agent-other", agent_known: false, success: true, attempt: 1, assigned_agent_id: "agent-product-1", started_at: null, completed_at: null, created_at: "2026-10-20T10:00:00Z" }] }) }),
    task("d", { agent_relation: relation("INCONSISTENT") }),
    task("e", { agent_relation: relation("UNASSIGNED"), status: "PENDING" }),
    task("f", { agent_relation: relation("ORCHESTRATOR"), capability: "decision_synthesis" }),
  ];
  const view = taskAgentPanel(await readMissionTaskAgents(source({ listTasks: async () => tasks })), agents);

  assert.equal(view.kind, "loaded");
  if (view.kind !== "loaded") return;
  assert.equal(view.projectName, "misión p-new");
  assert.equal(view.rows.length, 6);
  assert.deepEqual(view.counts, { tasks: 6, assigned: 3, executed: 2, deviations: 1, inconsistent: 1, unassigned: 1 });
});

test("el panel NO cambia de estado de lectura: error y sin leer se dicen, no se vuelven filas ni ceros", () => {
  const error = taskAgentPanel({ kind: "error", message: "No se pudieron cargar las misiones." }, agents);
  assert.equal(error.kind, "error");
  const unread = taskAgentPanel(unreadState("No se leyó."), agents);
  assert.equal(unread.kind, "unread");
  const empty = taskAgentPanel({ kind: "empty" }, agents);
  assert.equal(empty.kind, "empty");
  for (const view of [error, unread, empty]) assert.equal("rows" in view, false);
});

test("sin lista de agentes el panel enseña los ids tal cual (no inventa nombres) y mantiene el estado de la relación", async () => {
  const tasks = [task("a", { agent_relation: relation("ASSIGNED", { assigned_agent_id: "agent-product-1", assigned_agent_known: true }), status: "PENDING" })];
  const view = taskAgentPanel(await readMissionTaskAgents(source({ listTasks: async () => tasks })), null);

  assert.equal(view.kind === "loaded" && view.rows[0].assigned.label, "agent-product-1");
});
