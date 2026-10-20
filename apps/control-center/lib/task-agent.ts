import type { Agent, AgentRelation, AssignmentStatus, ExecutionTrace, Task } from "./api.ts";
import { taskStatusText } from "./nexus-mission.ts";

// La relación TAREA ↔ AGENTE en pantalla (M48, Commit 7). La relación la CALCULA el backend (`Task.agent_relation`: asignación, ejecuciones y qué
// decir de ellas); aquí solo se escribe, y con unas reglas que las pruebas fijan:
//
//   · ASIGNACIÓN ≠ EJECUCIÓN. «Agente asignado» y «Ejecutado por» son dos cosas, y una desviación (la ejecutó otro) se ve; no se funden.
//   · NADA se infiere. Una tarea sin `agent_relation` (un backend anterior) es «No disponible», no «la tarea de este agente por su capacidad».
//     Se acabó emparejar por capacidad, por el nombre de la tarea o por el orden.
//   · Un agente que el registro no conoce (lo dice el BACKEND, `*_known = false`) es «Agente desconocido»: ni su id como si fuera un nombre
//     ni «Disponible». Si la lista de agentes de esta pantalla no se pudo leer, se enseña el id tal cual: no se inventa un nombre.
//   · Lo anterior al vínculo (las misiones de octubre) se dice como lo que es: «ejecutada · sin asignación registrada». No es una desviación.

export const ASSIGNMENT_STATUSES: readonly AssignmentStatus[] = [
  "ORCHESTRATOR",
  "UNASSIGNED",
  "ASSIGNED",
  "MATCH",
  "MISMATCH",
  "EXECUTED_UNASSIGNED",
  "UNKNOWN_AGENT",
  "INCONSISTENT",
];

export const UNKNOWN_AGENT_LABEL = "Agente desconocido";
export const TASK_AGENT_UNAVAILABLE_LABEL = "No disponible";
export const UNASSIGNED_LABEL = "Sin asignar";
export const ORCHESTRATOR_LABEL = "Orquestador (CEO)";

export type TaskAgentTone = "ok" | "warn" | "bad" | "neutral";

export interface AgentRef {
  /** Lo que se enseña: el nombre del agente, «Agente desconocido», «Sin asignar» o «Orquestador (CEO)». */
  label: string;
  id: string | null;
  /** Lo que dice el backend: `null` sin agente, `false` si el registro no lo conoce. */
  known: boolean | null;
}

export interface TaskAgentRow {
  taskId: string;
  taskName: string;
  capability: string;
  taskStatus: string;
  /** El estado de la relación, o `UNAVAILABLE` si el backend no la envió o no es válida (nunca «sin asignar» por defecto). */
  status: AssignmentStatus | "UNAVAILABLE";
  assigned: AgentRef;
  /** El agente de la última ejecución, si la hay. */
  executedBy: { label: string; id: string } | null;
  /** Lo que se enseña como «Estado»: el de la tarea, o «Desviación», «Inconsistente», «Agente desconocido»… */
  state: string;
  tone: TaskAgentTone;
  deviation: boolean;
  reassigned: boolean;
  attempts: number;
  failedAttempts: number;
  /** Alguna ejecución sale solo de la auditoría (anterior al vínculo con el log). */
  historical: boolean;
  note: string | null;
}

const isRecord = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null && !Array.isArray(value);
const isTextOrNull = (value: unknown): value is string | null => value === null || typeof value === "string";
const isBoolOrNull = (value: unknown): value is boolean | null => value === null || typeof value === "boolean";

function isTrace(value: unknown): value is ExecutionTrace {
  return (
    isRecord(value) &&
    (value.source === "execution_log" || value.source === "audit") &&
    typeof value.agent_id === "string" &&
    value.agent_id.length > 0 &&
    typeof value.agent_known === "boolean" &&
    isBoolOrNull(value.success)
  );
}

/** La relación del backend, comprobada. `null` si falta o no cumple el contrato: no se adivina nada en su lugar. */
export function relationOf(task: Task): AgentRelation | null {
  const value: unknown = task.agent_relation;
  if (!isRecord(value)) return null;
  if (typeof value.status !== "string" || !(ASSIGNMENT_STATUSES as readonly string[]).includes(value.status)) return null;
  if (!isTextOrNull(value.assigned_agent_id) || !isBoolOrNull(value.assigned_agent_known) || !isTextOrNull(value.executed_by_agent_id)) return null;
  if (typeof value.reassigned !== "boolean") return null;
  if (!Array.isArray(value.executions) || !value.executions.every(isTrace)) return null;
  return value as unknown as AgentRelation;
}

function nameOf(id: string, known: boolean | null, agents: Agent[] | null): string {
  if (known === false) return UNKNOWN_AGENT_LABEL;
  return agents?.find((item) => item.id === id)?.name ?? id;
}

const TONE: Record<AssignmentStatus | "UNAVAILABLE", TaskAgentTone> = {
  ORCHESTRATOR: "neutral",
  UNASSIGNED: "warn",
  ASSIGNED: "neutral",
  MATCH: "ok",
  MISMATCH: "bad",
  EXECUTED_UNASSIGNED: "neutral",
  UNKNOWN_AGENT: "bad",
  INCONSISTENT: "bad",
  UNAVAILABLE: "neutral",
};

function stateOf(status: AssignmentStatus | "UNAVAILABLE", taskStatus: string): string {
  switch (status) {
    case "MISMATCH":
      return "Desviación";
    case "UNKNOWN_AGENT":
      return UNKNOWN_AGENT_LABEL;
    case "INCONSISTENT":
      return "Inconsistente";
    case "UNASSIGNED":
      return UNASSIGNED_LABEL;
    case "EXECUTED_UNASSIGNED":
      return `${taskStatusText(taskStatus)} · sin asignación registrada`;
    case "UNAVAILABLE":
      return TASK_AGENT_UNAVAILABLE_LABEL;
    default:
      return taskStatusText(taskStatus);
  }
}

function noteOf(relation: AgentRelation, agents: Agent[] | null): string | null {
  const parts: string[] = [];
  const runs = relation.executions;
  if (runs.length > 1) {
    const failed = runs.filter((run) => run.success === false).length;
    const who = [...new Set(runs.map((run) => nameOf(run.agent_id, run.agent_known ? null : false, agents)))];
    parts.push(`${runs.length} intentos${failed > 0 ? ` (${failed} fallido${failed === 1 ? "" : "s"})` : ""}: ${who.join(", ")}`);
  }
  if (relation.reassigned) parts.push("Reasignada");
  return parts.length > 0 ? parts.join(" · ") : null;
}

function rowOf(task: Task, agents: Agent[] | null): TaskAgentRow {
  const relation = relationOf(task);
  const base = { taskId: task.id, taskName: task.name ?? task.id, capability: task.capability, taskStatus: task.status };
  if (relation === null) {
    return {
      ...base,
      status: "UNAVAILABLE",
      assigned: { label: TASK_AGENT_UNAVAILABLE_LABEL, id: null, known: null },
      executedBy: null,
      state: TASK_AGENT_UNAVAILABLE_LABEL,
      tone: TONE.UNAVAILABLE,
      deviation: false,
      reassigned: false,
      attempts: 0,
      failedAttempts: 0,
      historical: false,
      note: null,
    };
  }
  const assigned: AgentRef =
    relation.status === "ORCHESTRATOR"
      ? { label: ORCHESTRATOR_LABEL, id: null, known: null }
      : relation.assigned_agent_id === null
        ? { label: UNASSIGNED_LABEL, id: null, known: null }
        : { label: nameOf(relation.assigned_agent_id, relation.assigned_agent_known, agents), id: relation.assigned_agent_id, known: relation.assigned_agent_known };
  const latest = relation.executions.length > 0 ? relation.executions[relation.executions.length - 1] : null;
  return {
    ...base,
    status: relation.status,
    assigned,
    executedBy: latest === null ? null : { label: nameOf(latest.agent_id, latest.agent_known ? null : false, agents), id: latest.agent_id },
    state: stateOf(relation.status, task.status),
    tone: TONE[relation.status],
    deviation: relation.status === "MISMATCH",
    reassigned: relation.reassigned,
    attempts: relation.executions.length,
    failedAttempts: relation.executions.filter((run) => run.success === false).length,
    historical: relation.executions.some((run) => run.source === "audit"),
    note: noteOf(relation, agents),
  };
}

/** Una fila por tarea, en el orden en que llegan. `agents` es la lista de agentes para escribir sus nombres (`null` si no se pudo leer). */
export function taskAgentRows(tasks: Task[], agents: Agent[] | null): TaskAgentRow[] {
  return tasks.map((task) => rowOf(task, agents));
}

/** Las filas de UN agente: las tareas que tiene ASIGNADAS o que EJECUTÓ (incluida una que ejecutó estando asignada a otro: la desviación es
 * suya también). NUNCA las que solo comparten su capacidad. */
export function agentTaskRows(agentId: string, rows: TaskAgentRow[]): TaskAgentRow[] {
  return rows.filter((row) => row.assigned.id === agentId || row.executedBy?.id === agentId);
}
