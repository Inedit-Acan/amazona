import type { Agent, Project, Task } from "./api.ts";
import { latestProject, projectsContract, tasksContract } from "./nexus-mission.ts";
import { readList, type ReadState } from "./read-state.ts";
import { taskAgentRows, type TaskAgentRow } from "./task-agent.ts";

// «Tareas y agentes» de la última misión (M47/M48, Commit 7): la lectura y el panel que comparten `/status` y el Decision Engine de `/ceo`.
//
// UNA lectura de misiones y UNA de las tareas de la última. Un fallo es `error` (nunca «sin misiones» ni una lista de «sin asignar»), una
// misión sin tareas es `empty` (un hecho), y un contrato roto de tareas es `error`. La relación de cada tarea con su agente la calcula el
// backend (`Task.agent_relation`); aquí no se calcula ni se infiere nada.

export interface MissionTasksSource {
  listProjects(): Promise<Project[]>;
  listTasks(projectId: string): Promise<Task[]>;
}

export interface MissionTaskAgents {
  project: Project;
  tasks: Task[];
}

export async function readMissionTaskAgents(source: MissionTasksSource): Promise<ReadState<MissionTaskAgents>> {
  const projects = projectsContract(await readList(() => source.listProjects(), "las misiones"));
  if (projects.kind !== "loaded") return projects.kind === "empty" ? { kind: "empty" } : projects;
  const project = latestProject(projects.data);
  if (project === null) return { kind: "empty" };
  const tasks = tasksContract(await readList(() => source.listTasks(project.id), "las tareas de la última misión"));
  if (tasks.kind !== "loaded") return tasks.kind === "empty" ? { kind: "empty" } : tasks;
  return { kind: "loaded", data: { project, tasks: tasks.data } };
}

export interface TaskAgentCounts {
  tasks: number;
  /** Tareas con un agente asignado (la asignación vigente, sea cual sea su ejecución). */
  assigned: number;
  /** Tareas con al menos una ejecución. */
  executed: number;
  deviations: number;
  inconsistent: number;
  unassigned: number;
}

export type TaskAgentPanel =
  | { kind: "error"; message: string }
  | { kind: "unread"; reason: string }
  | { kind: "empty" }
  | { kind: "loaded"; projectName: string; rows: TaskAgentRow[]; counts: TaskAgentCounts };

/** El panel a partir de la lectura y de la lista de agentes (`null` si esa no se pudo leer: se enseñan los ids, no nombres inventados). */
export function taskAgentPanel(state: ReadState<MissionTaskAgents>, agents: Agent[] | null): TaskAgentPanel {
  switch (state.kind) {
    case "error":
      return { kind: "error", message: state.message };
    case "unread":
      return { kind: "unread", reason: state.reason };
    case "empty":
      return { kind: "empty" };
    case "loaded": {
      const rows = taskAgentRows(state.data.tasks, agents);
      return {
        kind: "loaded",
        projectName: state.data.project.name,
        rows,
        counts: {
          tasks: rows.length,
          assigned: rows.filter((row) => row.assigned.id !== null).length,
          executed: rows.filter((row) => row.executedBy !== null).length,
          deviations: rows.filter((row) => row.deviation).length,
          inconsistent: rows.filter((row) => row.status === "INCONSISTENT").length,
          unassigned: rows.filter((row) => row.status === "UNASSIGNED").length,
        },
      };
    }
  }
}
