import type { Decision, MissionBlocker, MissionBlockerReason, MissionStateName, MissionSummary } from "./api.ts";

// El estado de una misión y su historia de decisiones (M50, Commit 9). Solo VISIBILIDAD: el backend decide (`GET /api/projects/{id}/mission`);
// aquí se valida el contrato y se escribe. No hay botón de reanudar: hasta que el backend esté completamente validado, la interfaz solo dice
// en qué punto está la misión y qué falta resolver. Un campo ausente o desconocido NO se convierte en «completa»: es «sin dato».

export type MissionTone = "ok" | "warn" | "bad" | "neutral";

const STATES: readonly MissionStateName[] = ["complete", "ready_to_resume", "recovery_pending", "resuming", "cancelled", "inconsistent"];
const REASONS: readonly MissionBlockerReason[] = [
  "failed_recoverable",
  "failed_reassign_required",
  "failed_definitive",
  "unknown_agent",
  "mismatch",
  "no_agent_available",
  "running",
];

const isText = (value: unknown): value is string => typeof value === "string" && value.trim() !== "";
const isTextList = (value: unknown): value is string[] => Array.isArray(value) && value.every(isText);
const isCount = (value: unknown): value is number => typeof value === "number" && Number.isInteger(value) && value >= 0;

function blockerOf(raw: unknown): MissionBlocker | null {
  if (raw === null || typeof raw !== "object") return null;
  const row = raw as Record<string, unknown>;
  if (!isText(row.task) || !REASONS.includes(row.reason as MissionBlockerReason)) return null;
  return { task: row.task, reason: row.reason as MissionBlockerReason };
}

/** La misión leída del backend, o `null` si el contrato no se cumple (estado desconocido, recuentos que no son números, lista de bloqueos rota…). */
export function missionOf(raw: unknown): MissionSummary | null {
  if (raw === null || typeof raw !== "object") return null;
  const row = raw as Record<string, unknown>;
  if (!isText(row.project_id) || !STATES.includes(row.state as MissionStateName)) return null;
  if (typeof row.resumable !== "boolean" || typeof row.resumed !== "boolean") return null;
  if (!Array.isArray(row.blockers) || !isTextList(row.pending_tasks) || !isTextList(row.completed_tasks) || !isCount(row.decisions)) return null;
  if (row.current_decision_id !== null && !isText(row.current_decision_id)) return null;
  const blockers = row.blockers.map(blockerOf);
  if (blockers.some((blocker) => blocker === null)) return null;
  return {
    project_id: row.project_id,
    state: row.state as MissionStateName,
    resumable: row.resumable,
    resumed: row.resumed,
    blockers: blockers as MissionBlocker[],
    pending_tasks: row.pending_tasks,
    completed_tasks: row.completed_tasks,
    current_decision_id: row.current_decision_id as string | null,
    decisions: row.decisions,
  };
}

/** «Misión incompleta» cuando falta trabajo por hacer (lista para reanudar, recuperación pendiente, en curso o un plan roto); `null` si no. */
export function missionHeadline(mission: MissionSummary): string | null {
  switch (mission.state) {
    case "ready_to_resume":
    case "recovery_pending":
    case "resuming":
    case "inconsistent":
      return "Misión incompleta";
    default:
      return null;
  }
}

/** La etapa en una frase. Una misión completa que nunca se reanudó no lleva etiqueta: no hay nada que decir. */
export function missionLabel(mission: MissionSummary): string | null {
  switch (mission.state) {
    case "recovery_pending":
      return "Recuperación pendiente";
    case "ready_to_resume":
      return "Lista para reanudar";
    case "resuming":
      return "Reanudando";
    case "complete":
      return mission.resumed ? "Reanudada" : null;
    case "cancelled":
      return "Misión cancelada";
    case "inconsistent":
      return "Plan inconsistente";
  }
}

export function missionTone(mission: MissionSummary): MissionTone {
  switch (mission.state) {
    case "complete":
      return mission.resumed ? "ok" : "neutral";
    case "ready_to_resume":
    case "resuming":
      return "warn";
    case "recovery_pending":
    case "inconsistent":
      return "bad";
    case "cancelled":
      return "neutral";
  }
}

const REASON_TEXT: Record<MissionBlockerReason, string> = {
  failed_recoverable: "falló y se puede reintentar",
  failed_reassign_required: "falló y su agente ya gastó los intentos: hay que reasignarla",
  failed_definitive: "falló y ya no admite más intentos",
  unknown_agent: "su agente ya no existe en el registro",
  mismatch: "la ejecutó un agente que no era el asignado",
  no_agent_available: "no hay ningún agente disponible para ella",
  running: "se está ejecutando",
};

/** Lo que impide reanudar, tarea por tarea, en lenguaje llano. */
export function blockerText(blocker: MissionBlocker): string {
  return `${blocker.task}: ${REASON_TEXT[blocker.reason]}`;
}

/** La decisión vigente de una lista. Una misión reanudada tiene varias; solo una es la vigente. Sin marcas (un backend anterior) y con una sola
 * decisión, esa es la vigente. Con varias y sin una única marcada, NO se adivina: `ambiguous`. */
export type CurrentDecision = { kind: "none" } | { kind: "current"; decision: Decision } | { kind: "ambiguous" };

export function currentDecision(decisions: readonly Decision[]): CurrentDecision {
  if (decisions.length === 0) return { kind: "none" };
  const marked = decisions.filter((decision) => decision.is_current === true);
  if (marked.length === 1) return { kind: "current", decision: marked[0] };
  if (marked.length === 0 && decisions.length === 1) return { kind: "current", decision: decisions[0] };
  return { kind: "ambiguous" };
}
