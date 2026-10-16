import type { Agent, AuditEntry } from "./api.ts";
import { eventCategory, isErrorAction, type EventCategory } from "./audit.ts";
import { strictDomainOfRole } from "./ceo-area-executions.ts";
import type { BlockState } from "./ceo-blocks.ts";
import { formatUtcDateTime } from "./ceo-block-view.ts";
import { parseUtc } from "./dates.ts";
import type { DomainKey } from "./nexus-domains.ts";
import { listOf, type ReadState } from "./read-state.ts";

// ACTIVIDAD REGISTRADA (M47, Commit 5, D-5-1 / D-5-2). Las últimas cinco entradas del registro de auditoría (`audit_log`, append-only).
//
// Por qué «registrada» y no «reciente»: `GET /api/audit` devuelve `ORDER BY created_at ASC LIMIT 500`, es decir, las 500 entradas más
// ANTIGUAS, sin paginación, sin rango de tiempo y con un único filtro (`correlation_id`). Solo cuando la respuesta trae MENOS de 500
// filas es el registro completo y «lo último» es verdad; con 500 el backend no puede garantizar las más recientes y el bloque dice
// «No disponible»: nunca se enseñan las más antiguas como si fueran actividad. El arreglo duradero es un cambio aditivo del backend
// (`order`, `limit`, `since`), pendiente de un micro-commit aparte.
//
// «Lo último» sale del INSTANTE (`created_at`, descendente) y del `id` (descendente) como desempate: nunca del orden de la API ni de la
// posición en el array. Cada fila lleva su fecha y hora absolutas en UTC.
//
// Qué se muestra y de dónde sale cada cosa (procedencia):
//   · registrado: `created_at`, `actor`, `action`, `resource` (tal cual los guarda el backend);
//   · derivado: la categoría (por el prefijo de la acción), el área (solo si el actor es un agente del registro) y «Fallo» (solo si la
//     acción dice `fail` o `error`). Una entrada de auditoría dice que algo OCURRIÓ, no que saliera bien: no existe un «OK».
//
// Privacidad: un actor con correo se enseña como «Persona» y un recurso con correo no se enseña; la dirección no llega a la pantalla.
// D-5-2: no se oculta ninguna acción técnica (`exchange_rate.*`, `memory.*`, `task.*`…); la acción original se conserva siempre.

export const ACTIVITY_BLOCK = {
  key: "actividad",
  title: "Actividad registrada",
} as const;

/** El tope de `GET /api/audit`: con tantas filas, la respuesta puede haber dejado fuera lo último. */
export const AUDIT_API_LIMIT = 500;
export const VISIBLE_ACTIVITY = 5;

const EMPTY_TEXT = "Sin actividad registrada";
const UNAVAILABLE_REASON =
  "La API de auditoría no puede garantizar las entradas más recientes: devuelve las 500 más antiguas, así que no se enseña ninguna como actividad.";
const AGENTS_NOTE = "El nombre y el área de los agentes no están disponibles: el registro de agentes no se pudo leer.";
const FOOTNOTE = "Hora, actor y acción: registrados. Categoría, área y fallo: derivados de la acción y del registro de agentes.";

export type ActorKind = "agent" | "orchestrator" | "person" | "other";

export interface ActivityProvenance {
  source: "audit_log";
  id: string;
  recorded: ["created_at", "actor", "action", "resource"];
  derived: ["category", "area", "result"];
}

export interface ActivityRow {
  key: string;
  /** El `created_at` que trae el backend. */
  at: string;
  atText: string;
  category: EventCategory;
  /** La acción tal cual se registró. */
  action: string;
  actor: { text: string; kind: ActorKind };
  /** Solo si el actor es un agente del registro con un rol que tiene dominio. */
  area: DomainKey | null;
  /** `true` solo si la acción dice `fail` o `error`. No existe el caso contrario («OK»). */
  failed: boolean;
  /** `null` si el recurso lleva una dirección de correo. */
  resource: string | null;
  provenance: ActivityProvenance;
}

export type ActivityView =
  | {
      kind: "loaded";
      total: number;
      subtitle: string;
      visible: ActivityRow[];
      more: number;
      agentsNote: string | null;
      footnote: string;
    }
  | { kind: "empty"; text: string }
  | { kind: "unread"; reason: string }
  | { kind: "unavailable"; reason: string }
  | { kind: "error"; message: string };

interface Dated {
  entry: AuditEntry;
  ms: number;
}

/** Más reciente primero; el id desempata (descendente). */
function newest(a: Dated, b: Dated): number {
  if (a.ms !== b.ms) return b.ms - a.ms;
  return a.entry.id < b.entry.id ? 1 : a.entry.id > b.entry.id ? -1 : 0;
}

function actorOf(actor: string, registry: ReadonlyMap<string, Agent> | null): { text: string; kind: ActorKind; agent: Agent | null } {
  const agent = registry?.get(actor) ?? null;
  if (agent !== null) return { text: agent.name, kind: "agent", agent };
  if (actor === "ceo") return { text: "Orquestador", kind: "orchestrator", agent: null };
  if (actor.includes("@")) return { text: "Persona", kind: "person", agent: null };
  return { text: actor, kind: "other", agent: null };
}

function rowOf({ entry, ms }: Dated, registry: ReadonlyMap<string, Agent> | null): ActivityRow {
  const actor = actorOf(entry.actor, registry);
  return {
    key: `audit:${entry.id}`,
    at: entry.created_at,
    atText: formatUtcDateTime(ms),
    category: eventCategory(entry.action),
    action: entry.action,
    actor: { text: actor.text, kind: actor.kind },
    area: actor.agent === null ? null : strictDomainOfRole(actor.agent.role),
    failed: isErrorAction(entry.action),
    resource: entry.resource.includes("@") ? null : entry.resource,
    provenance: {
      source: "audit_log",
      id: entry.id,
      recorded: ["created_at", "actor", "action", "resource"],
      derived: ["category", "area", "result"],
    },
  };
}

function subtitleOf(shown: number, total: number): string {
  return `${shown === 1 ? "Última" : "Últimas"} ${shown} de ${total} ${total === 1 ? "entrada" : "entradas"} del registro de auditoría`;
}

export function activityBlock(input: { audit: ReadState<AuditEntry[]>; agents: ReadState<Agent[]> }): ActivityView {
  const { audit, agents } = input;
  if (audit.kind === "error") return { kind: "error", message: audit.message };
  if (audit.kind === "unread") return { kind: "unread", reason: audit.reason };

  const entries = listOf(audit) ?? [];
  if (entries.length === 0) return { kind: "empty", text: EMPTY_TEXT };
  // La guarda de completitud: con 500 filas la respuesta puede no contener lo último. Nunca se enseñan las 500 más antiguas.
  if (entries.length >= AUDIT_API_LIMIT) return { kind: "unavailable", reason: UNAVAILABLE_REASON };

  // El registro de agentes solo da nombre y área al actor: si no se leyó, la actividad se enseña igual, sin ellos, y lo dice.
  const registry = agents.kind === "loaded" || agents.kind === "empty" ? new Map((listOf(agents) ?? []).map((agent) => [agent.id, agent] as const)) : null;

  const ordered = entries.map((entry): Dated => ({ entry, ms: parseUtc(entry.created_at) })).sort(newest);
  const visible = ordered.slice(0, VISIBLE_ACTIVITY).map((item) => rowOf(item, registry));
  return {
    kind: "loaded",
    total: entries.length,
    subtitle: subtitleOf(visible.length, entries.length),
    visible,
    more: Math.max(0, entries.length - VISIBLE_ACTIVITY),
    agentsNote: registry === null ? AGENTS_NOTE : null,
    footnote: FOOTNOTE,
  };
}

/** El estado que entiende `BlockCard`. */
export function activityStateOf(view: ActivityView): BlockState<unknown> {
  switch (view.kind) {
    case "loaded":
      return { kind: "loaded", data: view };
    case "empty":
      return { kind: "empty" };
    case "unread":
      return { kind: "unread", reason: view.reason };
    case "unavailable":
      return { kind: "unavailable", reason: view.reason };
    case "error":
      return { kind: "error", message: view.message };
  }
}
