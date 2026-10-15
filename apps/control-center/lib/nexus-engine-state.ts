import type { Decision, DecisionStatus, Project, Task } from "./api.ts";
import { formatUtcDateTime } from "./ceo-block-view.ts";
import { parseUtc } from "./dates.ts";
import { formatDuration } from "./format.ts";
import { taskProgress, type MissionRead, type TaskProgress } from "./nexus-mission.ts";
import type { NodeStatus } from "./neural-nexus.ts";
import type { ReadState } from "./read-state.ts";

// EL ESTADO DEL DECISION ENGINE (M47, Commit 4): qué se enseña de «la última misión registrada» y con qué procedencia. Capa pura: una
// máquina de estados que concilia la lectura PERSISTIDA con el resultado de la SESIÓN (la misión recién creada), y el HUD que sale de ella.
//
// Precedencia sesión ↔ persistido (reglas del propietario):
//   1. tras «Crear misión» se puede enseñar, temporalmente, el resultado de la sesión;
//   2. inmediatamente se dispara una relectura (`mission_created` avanza el sello pedido);
//   3. cuando la relectura persistida termina bien Y contiene la misión, lo persistido es la fuente de verdad y la sesión se retira;
//   4. una lectura persistida más antigua (sin la misión nueva) NO sobrescribe la sesión: queda «sin confirmar» (obsoleta);
//   5. una lectura con error NO borra un resultado de sesión válido, pero lo marca «persistencia no verificada».
// Las respuestas llegan en cualquier orden: cada lectura lleva un sello (`seq`) y una respuesta más vieja que la ya aplicada se ignora.
//
// Procedencia de cada dato mostrado: `recorded` (tal cual lo guarda el backend), `derived` (calculado de datos registrados: evidencias de
// una decisión, progreso de tareas, agentes ocupados del registro, latencia del log) o `unavailable` (no hay dato).

export type Provenance = "recorded" | "derived" | "unavailable";

/** La última misión leída del backend. */
export type PersistedMission =
  | { kind: "empty" }
  | { kind: "error"; message: string }
  | { kind: "loaded"; project: Project; projectIds: string[]; decision: ReadState<Decision>; tasks: ReadState<Task[]> };

/** La misión que se acaba de crear en esta sesión: lo único que se sabe sin releer. */
export interface SessionMission {
  projectId: string;
  /** El título del objetivo enviado: el backend lo guarda como nombre del proyecto. */
  projectName: string;
  /** La decisión leída tras la ejecución; `null` si no se pudo leer. */
  decision: Decision | null;
}

/** El aviso de que se acaba de crear una misión: cada uno lleva un `id` nuevo para que el grafo dispare una relectura. */
export interface MissionEvent {
  id: number;
  session: SessionMission;
}

export function persistedMissionOf(read: MissionRead): PersistedMission {
  if (read.projects.kind === "empty") return { kind: "empty" };
  if (read.projects.kind !== "loaded" || read.project === null) {
    return { kind: "error", message: read.projects.kind === "error" ? read.projects.message : "No se pudo leer la última misión." };
  }
  return { kind: "loaded", project: read.project, projectIds: read.projects.data.map((item) => item.id), decision: read.decision, tasks: read.tasks };
}

export interface EngineState {
  /** La última lectura persistida aplicada; `null` = ninguna todavía. */
  persisted: PersistedMission | null;
  session: SessionMission | null;
  /** El sello de la última lectura pedida y el de la última aplicada. */
  requested: number;
  applied: number;
  /** Solo con una sesión sin confirmar: qué pasó con la última relectura. */
  sessionOutcome: "pending" | "stale" | "error";
}

export type EngineEvent =
  | { type: "read_requested" }
  | { type: "read_result"; seq: number; mission: PersistedMission }
  | { type: "mission_created"; session: SessionMission };

export const initialEngineState = (): EngineState => ({ persisted: null, session: null, requested: 0, applied: 0, sessionOutcome: "pending" });

export function reduceEngine(state: EngineState, event: EngineEvent): EngineState {
  switch (event.type) {
    case "read_requested":
      return { ...state, requested: state.requested + 1 };
    case "mission_created":
      return { ...state, session: event.session, requested: state.requested + 1, sessionOutcome: "pending" };
    case "read_result": {
      // Una respuesta más vieja (o repetida) que la ya aplicada no pisa a la nueva.
      if (event.seq <= state.applied) return state;
      const next = { ...state, applied: event.seq };
      const { mission } = event;
      if (state.session === null) return { ...next, persisted: mission };
      if (mission.kind === "loaded" && mission.projectIds.includes(state.session.projectId)) {
        return { ...next, persisted: mission, session: null, sessionOutcome: "pending" };
      }
      return { ...next, sessionOutcome: mission.kind === "error" ? "error" : "stale" };
    }
  }
}

// --- Vista --------------------------------------------------------------------------------------------------------------------

const DECISION_LABEL: Record<DecisionStatus, string> = {
  GO: "Favorable (GO)",
  REVIEW: "Revisión (REVIEW)",
  NO_GO: "No viable (NO_GO)",
  HUMAN_APPROVAL: "Requiere aprobación humana (HUMAN_APPROVAL)",
};

export type DecisionView =
  | { kind: "loaded"; status: DecisionStatus; statusText: string; evidenceCount: number }
  | { kind: "unavailable"; text: "No disponible" | "Sin decisión registrada" };

export type TasksView =
  | { kind: "loaded"; tasks: Task[]; progress: TaskProgress | null }
  | { kind: "none" }
  | { kind: "unavailable"; text: string };

export type EngineView =
  | { kind: "reading" }
  | { kind: "none" }
  | { kind: "error"; message: string }
  | {
      kind: "mission";
      source: "persisted" | "session";
      confirmed: boolean;
      /** Por qué lo de la sesión no está confirmado; `null` si lo está. */
      reason: "reading" | "stale" | "error" | null;
      project: { name: string; createdAt: string | null };
      decision: DecisionView;
      tasks: TasksView;
    };

const decisionView = (decision: Decision): DecisionView => ({
  kind: "loaded",
  status: decision.status,
  statusText: DECISION_LABEL[decision.status],
  evidenceCount: decision.evidence.length,
});

function decisionOf(state: ReadState<Decision>): DecisionView {
  if (state.kind === "loaded") return decisionView(state.data);
  return { kind: "unavailable", text: state.kind === "empty" ? "Sin decisión registrada" : "No disponible" };
}

function tasksOf(state: ReadState<Task[]>): TasksView {
  if (state.kind === "loaded") return { kind: "loaded", tasks: state.data, progress: taskProgress(state.data) };
  if (state.kind === "empty") return { kind: "none" };
  return { kind: "unavailable", text: "No disponible" };
}

export function engineView(state: EngineState): EngineView {
  const { session, persisted } = state;
  if (session !== null) {
    return {
      kind: "mission",
      source: "session",
      confirmed: false,
      reason: state.sessionOutcome === "pending" ? "reading" : state.sessionOutcome,
      project: { name: session.projectName, createdAt: null },
      decision: session.decision === null ? { kind: "unavailable", text: "No disponible" } : decisionView(session.decision),
      // Las tareas solo existen en lo persistido: sin confirmar no hay progreso.
      tasks: { kind: "unavailable", text: "No disponible" },
    };
  }
  if (persisted === null) return { kind: "reading" };
  if (persisted.kind === "empty") return { kind: "none" };
  if (persisted.kind === "error") return { kind: "error", message: persisted.message };
  return {
    kind: "mission",
    source: "persisted",
    confirmed: true,
    reason: null,
    project: { name: persisted.project.name, createdAt: persisted.project.created_at },
    decision: decisionOf(persisted.decision),
    tasks: tasksOf(persisted.tasks),
  };
}

/** Las tareas de la misión que se muestra, para las aristas de dependencia y las tareas relacionadas. Solo de lo PERSISTIDO: una sesión sin
 * confirmar no trae tareas. */
export function tasksOfView(view: EngineView): Task[] | null {
  return view.kind === "mission" && view.tasks.kind === "loaded" ? view.tasks.tasks : null;
}

// --- HUD ----------------------------------------------------------------------------------------------------------------------

export interface HudField {
  label: string;
  text: string;
  provenance: Provenance;
  /** Detalle para el tooltip (fecha, regla de cálculo). */
  note?: string;
}

export interface EngineHud {
  /** El núcleo no «se enciende» con una decisión guardada: su estado es el de la lectura de agentes, no el de una misión pasada. */
  coreStatus: NodeStatus;
  notice: { tone: "info" | "warning" | "error"; text: string } | null;
  /** La fracción de progreso (0–1) de las tareas, o `null` si no hay dato. */
  progress: number | null;
  fields: HudField[];
}

const NO_DATA = "Sin dato";
const NOT_AVAILABLE = "No disponible";
const READING = "Leyendo…";

function noticeOf(view: EngineView): EngineHud["notice"] {
  if (view.kind === "error") return { tone: "error", text: view.message };
  if (view.kind !== "mission" || view.confirmed) return null;
  if (view.reason === "stale") return { tone: "warning", text: "La lectura guardada es anterior a esta misión: resultado de esta sesión sin confirmar." };
  if (view.reason === "error") return { tone: "warning", text: "No se pudo verificar la persistencia: resultado de esta sesión sin confirmar." };
  return { tone: "info", text: "Resultado de esta sesión, pendiente de confirmar con lo guardado." };
}

export function engineHud(input: { view: EngineView; agents: { running: number; total: number }; latencyMs: number | null }): EngineHud {
  const { view, agents, latencyMs } = input;
  const missing = view.kind === "reading" ? READING : view.kind === "error" ? NOT_AVAILABLE : NO_DATA;
  const unavailable = (label: string): HudField => ({ label, text: missing, provenance: "unavailable" });

  let project: HudField;
  let decision: HudField;
  let evidence: HudField;
  let progress: HudField;
  let fraction: number | null = null;

  if (view.kind !== "mission") {
    project =
      view.kind === "none"
        ? { label: "Última misión", text: "Sin misiones", provenance: "recorded", note: "El backend respondió y no hay ninguna misión registrada." }
        : unavailable("Última misión");
    decision = unavailable("Decisión");
    evidence = unavailable("Evidencias de la decisión");
    progress = unavailable("Progreso");
  } else {
    project = {
      label: "Última misión",
      text: view.project.name,
      provenance: "recorded",
      note: view.project.createdAt === null ? "Misión creada en esta sesión." : `Creada ${formatUtcDateTime(parseUtc(view.project.createdAt))}`,
    };
    decision =
      view.decision.kind === "loaded"
        ? { label: "Decisión", text: view.decision.statusText, provenance: "recorded" }
        : { label: "Decisión", text: view.decision.text, provenance: "unavailable" };
    evidence =
      view.decision.kind === "loaded"
        ? { label: "Evidencias de la decisión", text: String(view.decision.evidenceCount), provenance: "derived", note: "Número de evidencias que trae la decisión (evidence.length)." }
        : { label: "Evidencias de la decisión", text: view.decision.text === "No disponible" ? NOT_AVAILABLE : NO_DATA, provenance: "unavailable" };
    if (view.tasks.kind === "loaded" && view.tasks.progress !== null) {
      fraction = view.tasks.progress.fraction;
      progress = {
        label: "Progreso",
        text: `${view.tasks.progress.completed} de ${view.tasks.progress.total} tareas · ${Math.round(view.tasks.progress.fraction * 100)} %`,
        provenance: "derived",
        note: "Tareas COMPLETED entre las tareas de la misión que no están CANCELLED. FAILED y WAITING_APPROVAL no cuentan como completadas.",
      };
    } else {
      progress = { label: "Progreso", text: view.tasks.kind === "unavailable" ? NOT_AVAILABLE : NO_DATA, provenance: "unavailable" };
    }
  }

  return {
    coreStatus: "available",
    notice: noticeOf(view),
    progress: fraction,
    fields: [
      project,
      decision,
      evidence,
      progress,
      { label: "Agentes activos", text: `${agents.running} / ${agents.total}`, provenance: "derived", note: "Agentes que el registro da por ocupados (BUSY)." },
      latencyMs === null
        ? { label: "Latencia media", text: NO_DATA, provenance: "unavailable" }
        : { label: "Latencia media", text: formatDuration(latencyMs), provenance: "derived", note: "Media de las últimas ejecuciones del log." },
    ],
  };
}
