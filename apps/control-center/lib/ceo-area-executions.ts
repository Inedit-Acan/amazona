import type { Agent, AgentExecution } from "./api.ts";
import type { BlockState } from "./ceo-blocks.ts";
import { formatUtcDateTime, plural } from "./ceo-block-view.ts";
import { parseUtc } from "./dates.ts";
import { formatDuration } from "./format.ts";
import { teamOf } from "./agents.ts";
import { DOMAINS, type DomainKey } from "./nexus-domains.ts";
import { listOf, type ReadState } from "./read-state.ts";

// EJECUCIONES POR ÁREA (M47, Commit 5, D-5-3 / D-5-4). Antes se llamaba «Rendimiento por área» y llevaba los porcentajes del mockup.
// No existe una puntuación de área: lo que el backend SÍ guarda es el log de ejecuciones de los agentes (`agent_execution_log`, una
// fila por llamada a `AgentManager.execute`, también las que fallan y los reintentos). De ahí salen, por dominio:
//
//   · cuántas ejecuciones, cuántas correctas y cuántas fallidas («X de Y correctas»),
//   · la latencia media (`duration_ms` medido) y la última ejecución,
//
// siempre sobre «las últimas N ejecuciones registradas»: la API devuelve las 100 más recientes y no tiene ventana temporal, así que
// con 100 filas los números son «de las últimas 100», NO el total. Ningún porcentaje, ningún coste, ninguna tendencia.
//
// El ÁREA es uno de los ocho dominios del Decision Engine (`DOMAINS`), por el rol del agente en el registro. Un agente fuera del
// registro, o con un rol sin dominio, es «Sin área»: NUNCA «Operaciones» (el `domainOfRole` del Decision Engine sí cae ahí y no se toca).

export const AREA_BLOCK = {
  key: "ejecuciones-por-area",
  title: "Ejecuciones por área",
} as const;

/** El tope de `GET /api/agent-executions`: las 100 más recientes. */
export const EXECUTIONS_API_LIMIT = 100;

export const NO_AREA = "Sin área";
export type AreaKey = DomainKey | typeof NO_AREA;

const NO_DATA = "Sin dato";
const NO_EXECUTIONS = "Sin ejecuciones";
const EMPTY_TEXT = "Sin ejecuciones registradas";
const FOOTNOTE =
  "Latencia media de las ejecuciones registradas de cada área. Cada fila del log es una ejecución, reintentos incluidos. El área es la del rol del agente en el registro.";

/** El dominio de un rol, o `null` si el rol no pertenece a ninguno de los ocho. A diferencia de `domainOfRole`, nunca inventa «Operaciones». */
export function strictDomainOfRole(role: string): DomainKey | null {
  const team = teamOf(role);
  return (DOMAINS as readonly string[]).includes(team) ? (team as DomainKey) : null;
}

export interface AreaProvenance {
  source: "agent_execution_log";
  /** Lo que el backend guarda tal cual. */
  recorded: string[];
  /** Lo que se calcula de lo registrado. */
  derived: string[];
}

export interface AreaRow {
  area: AreaKey;
  total: number;
  ok: number;
  failed: number;
  /** «2 de 3 correctas», o «Sin ejecuciones». Nunca un porcentaje. */
  okText: string;
  failedText: string;
  /** Agentes distintos del área que aparecen en la ventana. */
  agents: number;
  meanLatencyMs: number | null;
  latencyText: string;
  /** El `created_at` de la última ejecución del área (el que trae el backend), o `null`. */
  lastAt: string | null;
  lastId: string | null;
  lastText: string;
  provenance: AreaProvenance;
}

export type AreaView =
  | { kind: "loaded"; total: number; truncated: boolean; windowText: string; rows: AreaRow[]; footnote: string }
  | { kind: "empty"; text: string }
  | { kind: "unread"; reason: string }
  | { kind: "error"; message: string };

interface Bucket {
  rows: AgentExecution[];
}

/** Si alguna lectura falló o no se hizo, el bloque entero lo dice: `error` gana a `unread`, y sus mensajes se juntan sin repetir. */
function unusableOf(states: ReadonlyArray<ReadState<unknown>>): Extract<AreaView, { kind: "error" | "unread" }> | null {
  const errors = states.flatMap((state) => (state.kind === "error" ? [state.message] : []));
  if (errors.length > 0) return { kind: "error", message: [...new Set(errors)].join(" ") };
  const reasons = states.flatMap((state) => (state.kind === "unread" ? [state.reason] : []));
  if (reasons.length > 0) return { kind: "unread", reason: [...new Set(reasons)].join(" ") };
  return null;
}

function windowText(total: number): string {
  if (total >= EXECUTIONS_API_LIMIT) return `Últimas ${total} ejecuciones registradas · las últimas ${total}, no el total`;
  return total === 1 ? "Última ejecución registrada" : `Últimas ${total} ejecuciones registradas`;
}

/** Más reciente primero; el id desempata (descendente). */
function newest(a: AgentExecution, b: AgentExecution): number {
  const at = parseUtc(a.created_at);
  const bt = parseUtc(b.created_at);
  if (at !== bt) return bt - at;
  return a.id < b.id ? 1 : a.id > b.id ? -1 : 0;
}

function rowOf(area: AreaKey, bucket: Bucket): AreaRow {
  const total = bucket.rows.length;
  const ok = bucket.rows.filter((row) => row.success).length;
  const failed = total - ok;
  const last = [...bucket.rows].sort(newest)[0] ?? null;
  const meanLatencyMs = total === 0 ? null : bucket.rows.reduce((sum, row) => sum + row.duration_ms, 0) / total;
  return {
    area,
    total,
    ok,
    failed,
    okText: total === 0 ? NO_EXECUTIONS : `${ok} de ${total} correctas`,
    failedText: total === 0 ? NO_EXECUTIONS : `${failed} ${plural(failed, "fallida", "fallidas")}`,
    agents: new Set(bucket.rows.map((row) => row.agent_id)).size,
    meanLatencyMs,
    latencyText: meanLatencyMs === null ? NO_DATA : formatDuration(meanLatencyMs),
    lastAt: last === null ? null : last.created_at,
    lastId: last === null ? null : last.id,
    lastText: last === null ? NO_EXECUTIONS : formatUtcDateTime(parseUtc(last.created_at)),
    provenance: {
      source: "agent_execution_log",
      recorded: ["created_at"],
      derived: ["total", "ok", "failed", "meanLatencyMs", "area"],
    },
  };
}

export function areaExecutionsBlock(input: { executions: ReadState<AgentExecution[]>; agents: ReadState<Agent[]> }): AreaView {
  const { executions, agents } = input;
  // Sin el registro de agentes no se puede atribuir ninguna ejecución a un área: el bloque entero lo dice, no reparte por defecto.
  const failed = unusableOf([executions, agents]);
  if (failed) return failed;

  const rows = listOf(executions) ?? [];
  if (rows.length === 0) return { kind: "empty", text: EMPTY_TEXT };

  const roleOf = new Map((listOf(agents) ?? []).map((agent) => [agent.id, agent.role] as const));
  const buckets = new Map<AreaKey, Bucket>([...DOMAINS, NO_AREA].map((area) => [area as AreaKey, { rows: [] }] as const));
  for (const row of rows) {
    const role = roleOf.get(row.agent_id);
    const area: AreaKey = (role === undefined ? null : strictDomainOfRole(role)) ?? NO_AREA;
    buckets.get(area)!.rows.push(row);
  }

  const orphans: AreaKey[] = (buckets.get(NO_AREA)?.rows.length ?? 0) > 0 ? [NO_AREA] : [];
  const areas: AreaKey[] = [...DOMAINS, ...orphans];
  return {
    kind: "loaded",
    total: rows.length,
    truncated: rows.length >= EXECUTIONS_API_LIMIT,
    windowText: windowText(rows.length),
    rows: areas.map((area) => rowOf(area, buckets.get(area)!)),
    footnote: FOOTNOTE,
  };
}

/** El estado que entiende `BlockCard`. */
export function areaStateOf(view: AreaView): BlockState<unknown> {
  switch (view.kind) {
    case "loaded":
      return { kind: "loaded", data: view };
    case "empty":
      return { kind: "empty" };
    case "unread":
      return { kind: "unread", reason: view.reason };
    case "error":
      return { kind: "error", message: view.message };
  }
}
