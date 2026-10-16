import type { Agent, AuditEntry } from "./api.ts";
import { eventCategory, isErrorAction, type EventCategory } from "./audit.ts";
import { strictDomainOfRole } from "./ceo-area-executions.ts";
import type { BlockState } from "./ceo-blocks.ts";
import { formatUtcDateTime } from "./ceo-block-view.ts";
import { parseUtc } from "./dates.ts";
import type { DomainKey } from "./nexus-domains.ts";
import { listOf, type ReadState } from "./read-state.ts";

// ACTIVIDAD REGISTRADA (M47, Commit 5 y micro-commit 5B, D-5-1 / D-5-2). Las últimas cinco entradas del registro de auditoría
// (`audit_log`, append-only).
//
// LA PETICIÓN: `GET /api/audit?order=desc&limit=5` (micro-commit 5A del backend). El servidor devuelve ya las cinco más recientes,
// ordenadas por `created_at` DESC y `id` DESC. Una sola lectura: no se pide el total (el endpoint no lo expone y leer 500 filas solo
// para contarlas no merece la pena), así que el subtítulo dice «Últimas 5 entradas registradas», sin «de N» ni «y N más».
//
// LA GUARDA DE COMPATIBILIDAD. Antes del 5A, `GET /api/audit` devolvía `ORDER BY created_at ASC LIMIT 500`: las 500 entradas más
// ANTIGUAS, y un backend viejo o mal desplegado ignora `order` y `limit`. La respuesta solo es válida si trae como mucho 5 filas Y
// vienen en orden estrictamente descendente de `(created_at, id)`. Si trae más, o no están en ese orden, el bloque dice «No
// disponible»: NO se recorta, NO se reordena y NO se presenta como válida una respuesta que no se sabe si contiene lo último.
//
// Qué se muestra y de dónde sale cada cosa (procedencia):
//   · registrado: `created_at`, `actor`, `action`, `resource` (tal cual los guarda el backend);
//   · derivado: la categoría (por el prefijo de la acción), el área (solo si el actor es un agente del registro) y «Fallo» (solo si la
//     acción dice `fail` o `error`). Una entrada de auditoría dice que algo OCURRIÓ, no que saliera bien: no existe un «OK».
//
// Cada fila lleva su fecha y hora absolutas en UTC. Privacidad: un actor con correo se enseña como «Persona» y un recurso con correo no
// se enseña; la dirección no llega a la pantalla. D-5-2: no se oculta ninguna acción técnica; la acción original se conserva siempre.

export const ACTIVITY_BLOCK = {
  key: "actividad",
  title: "Actividad registrada",
} as const;

/** Cuántas filas se piden y, como mucho, cuántas se enseñan. */
export const ACTIVITY_LIMIT = 5;

const EMPTY_TEXT = "Sin actividad registrada";
const UNAVAILABLE_REASON =
  "La API de auditoría no puede garantizar las últimas entradas: devolvió más filas de las pedidas o no las ordenó de más reciente a más antigua, así que no se enseña ninguna como actividad.";
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
      /** «Última entrada registrada» / «Últimas N entradas registradas»: N es lo que se enseña, nunca el total del registro. */
      subtitle: string;
      visible: ActivityRow[];
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

/** Cuál va antes en «más reciente primero»: un número positivo si `a` es más reciente que `b`. El `id` desempata (descendente). */
function recency(a: Dated, b: Dated): number {
  if (a.ms !== b.ms) return a.ms - b.ms;
  return a.entry.id > b.entry.id ? 1 : a.entry.id < b.entry.id ? -1 : 0;
}

/** Cada fila es ESTRICTAMENTE más antigua que la anterior en `(created_at, id)`: el orden `order=desc` del backend 5A. */
function isNewestFirst(items: readonly Dated[]): boolean {
  return items.every((item, index) => index === 0 || recency(items[index - 1], item) > 0);
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

const subtitleOf = (shown: number) => (shown === 1 ? "Última entrada registrada" : `Últimas ${shown} entradas registradas`);

export function activityBlock(input: { audit: ReadState<AuditEntry[]>; agents: ReadState<Agent[]> }): ActivityView {
  const { audit, agents } = input;
  if (audit.kind === "error") return { kind: "error", message: audit.message };
  if (audit.kind === "unread") return { kind: "unread", reason: audit.reason };

  const entries = listOf(audit) ?? [];
  if (entries.length === 0) return { kind: "empty", text: EMPTY_TEXT };

  // La guarda de compatibilidad: más filas de las pedidas, o fuera de orden, es un backend que no cumple el contrato del 5A.
  const dated = entries.map((entry): Dated => ({ entry, ms: parseUtc(entry.created_at) }));
  if (dated.length > ACTIVITY_LIMIT || !isNewestFirst(dated)) return { kind: "unavailable", reason: UNAVAILABLE_REASON };

  // El registro de agentes solo da nombre y área al actor: si no se leyó, la actividad se enseña igual, sin ellos, y lo dice.
  const registry = agents.kind === "loaded" || agents.kind === "empty" ? new Map((listOf(agents) ?? []).map((agent) => [agent.id, agent] as const)) : null;

  return {
    kind: "loaded",
    subtitle: subtitleOf(dated.length),
    visible: dated.map((item) => rowOf(item, registry)),
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
