import type { Agent, Decision, Project, Task, TaskStatus } from "./api.ts";
import type { MissionSource } from "./nexus-mission.ts";

// Apoyo común de las pruebas de la capa de datos del Decision Engine (M47, Commit 4). No es una prueba: no acaba en `.test.ts`.

export const NOW = Date.UTC(2026, 9, 15, 12);
const iso = (ms: number) => new Date(ms).toISOString();

export const project = (id: string, minutesAgo = 10, over: Partial<Project> = {}): Project => ({
  id,
  objective_id: `obj-${id}`,
  name: `Misión ${id}`,
  status: "VALIDATING",
  created_at: iso(NOW - minutesAgo * 60_000),
  ...over,
});

export const decision = (projectId: string, over: Partial<Decision> = {}): Decision => ({
  id: `dec-${projectId}`,
  project_id: projectId,
  status: "GO",
  opportunity_score: 0.8,
  confidence: 0.9,
  rationale: null,
  correlation_id: `corr-${projectId}`,
  evidence: [
    { source: "product_validation", summary: "ok", data: null },
    { source: "supplier_sourcing", summary: "ok", data: null },
    { source: "legal_validation", summary: "ok", data: null },
  ],
  ...over,
});

export const task = (id: string, status: TaskStatus, capability = "market_validation", over: Partial<Task> = {}): Task => ({
  id,
  project_id: "p1",
  name: `tarea ${id}`,
  capability,
  status,
  input: null,
  output: null,
  error: null,
  depends_on: [],
  ...over,
});

export const agent = (id: string, capabilities: string[], role = "product", status = "AVAILABLE"): Agent => ({
  id,
  name: `Agente ${id}`,
  role,
  capabilities,
  status,
  reliability_score: 0.9,
  version: "1.0.0",
  cost_profile: {},
});

/** Una fuente de la misión que cuenta sus llamadas. */
export function fakeMissionSource(
  data: { projects?: Project[]; decisions?: Record<string, Decision[]>; tasks?: Record<string, Task[]> } = {},
  fail: Partial<Record<"listProjects" | "listDecisionsForProject" | "listTasks", () => Error>> = {},
): MissionSource & { calls: Record<string, number>; args: Record<string, string[]> } {
  const calls: Record<string, number> = { listProjects: 0, listDecisionsForProject: 0, listTasks: 0 };
  const args: Record<string, string[]> = { listDecisionsForProject: [], listTasks: [] };
  return {
    calls,
    args,
    async listProjects() {
      calls.listProjects += 1;
      if (fail.listProjects) throw fail.listProjects();
      return data.projects ?? [];
    },
    async listDecisionsForProject(projectId: string) {
      calls.listDecisionsForProject += 1;
      args.listDecisionsForProject.push(projectId);
      if (fail.listDecisionsForProject) throw fail.listDecisionsForProject();
      return data.decisions?.[projectId] ?? [];
    },
    async listTasks(projectId: string) {
      calls.listTasks += 1;
      args.listTasks.push(projectId);
      if (fail.listTasks) throw fail.listTasks();
      return data.tasks?.[projectId] ?? [];
    },
  };
}
