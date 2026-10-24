import type { Agent, MissionSummary, Project, Task } from "./api.ts";
import { blockerText, missionHeadline, missionLabel, missionOf, missionTone, type MissionTone } from "./mission-state.ts";
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
  /** M50: en qué punto está la misión del proyecto. Opcional: una fuente sin ella (o una lectura que falla) deja el estado de la misión «sin dato». */
  getMission?(projectId: string): Promise<unknown>;
}

export interface MissionTaskAgents {
  project: Project;
  tasks: Task[];
  /** El estado de la misión, validado; `null` si no se pudo leer o el contrato no se cumple. NUNCA se rellena con «completa». */
  mission: MissionSummary | null;
}

export async function readMissionTaskAgents(source: MissionTasksSource): Promise<ReadState<MissionTaskAgents>> {
  const projects = projectsContract(await readList(() => source.listProjects(), "las misiones"));
  if (projects.kind !== "loaded") return projects.kind === "empty" ? { kind: "empty" } : projects;
  const project = latestProject(projects.data);
  if (project === null) return { kind: "empty" };
  const tasks = tasksContract(await readList(() => source.listTasks(project.id), "las tareas de la última misión"));
  if (tasks.kind !== "loaded") return tasks.kind === "empty" ? { kind: "empty" } : tasks;
  return { kind: "loaded", data: { project, tasks: tasks.data, mission: await readMissionSummary(source, project.id) } };
}

async function readMissionSummary(source: MissionTasksSource, projectId: string): Promise<MissionSummary | null> {
  if (source.getMission === undefined) return null;
  try {
    return missionOf(await source.getMission(projectId));
  } catch {
    return null;
  }
}

/** El estado de la misión tal como lo escribe la tarjeta. `unread`: no se sabe (no es «completa»). */
export type MissionPanel =
  | { kind: "unread" }
  | { kind: "loaded"; headline: string | null; label: string | null; tone: MissionTone; blockers: string[]; decisions: number };

export function missionPanel(mission: MissionSummary | null): MissionPanel {
  if (mission === null) return { kind: "unread" };
  return {
    kind: "loaded",
    headline: missionHeadline(mission),
    label: missionLabel(mission),
    tone: missionTone(mission),
    blockers: mission.blockers.map(blockerText),
    decisions: mission.decisions,
  };
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
  | { kind: "loaded"; projectName: string; rows: TaskAgentRow[]; counts: TaskAgentCounts; mission: MissionPanel };

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
        mission: missionPanel(state.data.mission),
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
