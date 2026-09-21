import type { AuditEntry } from "./api.ts";
import { isSameLocalDay, parseUtc } from "./dates.ts";

// El registro de auditoría es una lista de AuditLog: actor, acción, recurso, estado
// antes/después, ID de correlación y fecha. No tiene tipo, criticidad, resultado,
// proyecto, IP, hash ni evidencias. Este módulo clasifica y agrupa lo que sí hay;
// el «tipo» y el «tipo de actor» se deducen del prefijo de la acción y del nombre del
// actor, no son campos guardados.

export type EventCategory = "Proyecto" | "Decisión" | "Aprobación" | "Análisis" | "Pipeline" | "Memoria" | "Incidencia" | "Seguridad" | "Otros";

export const EVENT_CATEGORIES: EventCategory[] = [
  "Proyecto",
  "Decisión",
  "Aprobación",
  "Análisis",
  "Pipeline",
  "Memoria",
  "Incidencia",
  "Seguridad",
  "Otros",
];

/** Categoría de una acción (`project.created`, `economics.run`…) según su prefijo. */
export function eventCategory(action: string): EventCategory {
  const prefix = action.split(".")[0];
  switch (prefix) {
    case "project":
    case "tasks":
    case "task":
      return "Proyecto";
    case "decision":
      return "Decisión";
    case "approval":
    case "pipeline_review":
      return "Aprobación";
    case "memory":
      return "Memoria";
    case "incident":
      return "Incidencia";
    case "kill_switch":
    case "killswitch":
    case "auth":
    case "permission":
      return "Seguridad";
    case "pipeline":
      return "Pipeline";
    default:
      return action.endsWith(".run") ? "Análisis" : "Otros";
  }
}

export type ActorKind = "Agente" | "Persona" | "Orquestador" | "Sistema";

/** Tipo de actor deducido del nombre: `agent-*`, un correo, el CEO o el sistema. */
export function actorKind(actor: string): ActorKind {
  if (actor.startsWith("agent-") || actor.endsWith("-orchestrator-1")) return "Agente";
  if (actor.includes("@")) return "Persona";
  if (actor === "ceo") return "Orquestador";
  return "Sistema";
}

/** La acción indica un fallo o error (`task.failed`, `…error`). */
export function isErrorAction(action: string): boolean {
  return /fail|error/i.test(action);
}

export interface AuditFilters {
  window: "all" | "24h" | "7d" | "30d";
  category: EventCategory | "all";
  actor: string | "all";
  project: string | "all";
  query: string;
}

const WINDOW_MS = { "24h": 86_400_000, "7d": 7 * 86_400_000, "30d": 30 * 86_400_000 } as const;

/** Un proyecto por ID de correlación (lo da la decisión del proyecto). */
export type ProjectByCorrelation = Record<string, { id: string; name: string }>;

export function filterEvents(entries: AuditEntry[], filters: AuditFilters, projects: ProjectByCorrelation, now: number): AuditEntry[] {
  const query = filters.query.trim().toLowerCase();
  return entries.filter((entry) => {
    if (filters.window !== "all" && now - parseUtc(entry.created_at) > WINDOW_MS[filters.window]) return false;
    if (filters.category !== "all" && eventCategory(entry.action) !== filters.category) return false;
    if (filters.actor !== "all" && entry.actor !== filters.actor) return false;
    if (filters.project !== "all" && projects[entry.correlation_id]?.id !== filters.project) return false;
    if (!query) return true;
    const project = projects[entry.correlation_id]?.name ?? "";
    return `${entry.action} ${entry.actor} ${entry.resource} ${entry.correlation_id} ${project}`.toLowerCase().includes(query);
  });
}

export interface AuditSummary {
  total: number;
  today: number;
  approvals: number;
  decisions: number;
  errors: number;
  actors: number;
}

export function auditSummary(entries: AuditEntry[], now: number): AuditSummary {
  return {
    total: entries.length,
    today: entries.filter((e) => isSameLocalDay(parseUtc(e.created_at), now)).length,
    approvals: entries.filter((e) => eventCategory(e.action) === "Aprobación").length,
    decisions: entries.filter((e) => e.action === "decision.made").length,
    errors: entries.filter((e) => isErrorAction(e.action)).length,
    actors: new Set(entries.map((e) => e.actor)).size,
  };
}

export interface ActorRow {
  actor: string;
  kind: ActorKind;
  events: number;
  firstAt: number;
  lastAt: number;
  errors: number;
}

/** Actividad por actor, del más activo al menos. */
export function actorRows(entries: AuditEntry[]): ActorRow[] {
  const map = new Map<string, ActorRow>();
  for (const entry of entries) {
    const at = parseUtc(entry.created_at);
    const row = map.get(entry.actor) ?? { actor: entry.actor, kind: actorKind(entry.actor), events: 0, firstAt: at, lastAt: at, errors: 0 };
    row.events += 1;
    row.firstAt = Math.min(row.firstAt, at);
    row.lastAt = Math.max(row.lastAt, at);
    if (isErrorAction(entry.action)) row.errors += 1;
    map.set(entry.actor, row);
  }
  return [...map.values()].sort((a, b) => b.events - a.events || a.actor.localeCompare(b.actor));
}

export interface ProjectRow {
  projectId: string;
  name: string;
  events: number;
  correlations: number;
  lastAt: number;
}

/** Eventos por proyecto (los que se pueden atribuir por ID de correlación). */
export function projectRows(entries: AuditEntry[], projects: ProjectByCorrelation): ProjectRow[] {
  const map = new Map<string, ProjectRow & { ids: Set<string> }>();
  for (const entry of entries) {
    const project = projects[entry.correlation_id];
    if (!project) continue;
    const at = parseUtc(entry.created_at);
    const row = map.get(project.id) ?? { projectId: project.id, name: project.name, events: 0, correlations: 0, lastAt: at, ids: new Set<string>() };
    row.events += 1;
    row.ids.add(entry.correlation_id);
    row.lastAt = Math.max(row.lastAt, at);
    map.set(project.id, row);
  }
  return [...map.values()]
    .map(({ ids, ...row }) => ({ ...row, correlations: ids.size }))
    .sort((a, b) => b.lastAt - a.lastAt);
}

/** Eventos sin proyecto atribuible por su ID de correlación. */
export function unattributedCount(entries: AuditEntry[], projects: ProjectByCorrelation): number {
  return entries.filter((e) => !projects[e.correlation_id]).length;
}

export interface DayGroup {
  /** Clave `YYYY-MM-DD` del día local. */
  day: string;
  entries: AuditEntry[];
}

/** Eventos agrupados por día local, del más reciente al más antiguo (y dentro del día, igual). */
export function groupByDay(entries: AuditEntry[]): DayGroup[] {
  const groups = new Map<string, AuditEntry[]>();
  const sorted = [...entries].sort((a, b) => parseUtc(b.created_at) - parseUtc(a.created_at));
  for (const entry of sorted) {
    const date = new Date(parseUtc(entry.created_at));
    const day = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
    groups.set(day, [...(groups.get(day) ?? []), entry]);
  }
  return [...groups.entries()].map(([day, list]) => ({ day, entries: list }));
}

export interface StateChange {
  key: string;
  before: string | null;
  after: string | null;
}

function show(value: unknown): string {
  return typeof value === "string" ? value : JSON.stringify(value);
}

/** Claves de `before`/`after` con su valor antes y después (null si no existía). */
export function stateChanges(before: Record<string, unknown> | null, after: Record<string, unknown> | null): StateChange[] {
  const keys = [...new Set([...Object.keys(before ?? {}), ...Object.keys(after ?? {})])].sort();
  return keys.map((key) => ({
    key,
    before: before && key in before ? show(before[key]) : null,
    after: after && key in after ? show(after[key]) : null,
  }));
}
