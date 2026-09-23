import type { Agent, AuditEntry, Product } from "./api.ts";
import { actorKind, eventCategory, isErrorAction, stateChanges, type ActorKind, type StateChange } from "./audit.ts";
import { parseUtc } from "./dates.ts";
import {
  DEMO_ANOMALIES,
  EVENTS_PER_DAY,
  EVENT_TEMPLATES,
  EVIDENCE_COMPLETE_RATE,
  TYPE_BY_PREFIX,
  WINDOW_DAYS,
  demoEvidenceCount,
  demoHash,
} from "./demo/audit.ts";
import { demoRandom } from "./demo/random.ts";
import { projectCodeFor } from "./projects-view.ts";

// Vista de la pantalla de Auditoría y trazabilidad (mockup docs/design/
// auditoria.png). Real: las entradas de `AuditLog` (actor, acción, recurso,
// estado antes/después, ID de correlación y fecha) y, a partir de ellas, el
// tipo, el actor, el resultado y los cambios de estado. Demo
// (lib/demo/audit.ts): los eventos que llenan el registro mientras el backend
// solo tiene una decena, la criticidad, la IP, el user agent, las evidencias, el
// hash de integridad, las anomalías y la retención.

const DAY_MS = 86_400_000;

export type Criticality = "Alta" | "Media" | "Baja";
export type EventResult = "Éxito" | "Creado" | "Error";

export interface AuditRow {
  id: string;
  code: string;
  at: number;
  action: string;
  /** Tipo que se enseña en la tabla («Aprobación», «Finanzas»…). */
  type: string;
  title: string;
  detail: string;
  actor: string;
  actorKind: ActorKind;
  projectCode: string | null;
  productName: string | null;
  result: EventResult;
  criticality: Criticality;
  correlationId: string;
  resource: string;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  /** El evento lo generó la demostración, no el backend. */
  isDemo: boolean;
}

export function typeOf(action: string): string {
  return TYPE_BY_PREFIX[action.split(".")[0]] ?? eventCategory(action);
}

function resultOf(action: string): EventResult {
  if (isErrorAction(action)) return "Error";
  return /created|requested/.test(action) ? "Creado" : "Éxito";
}

function criticalityOf(action: string): Criticality {
  const prefix = action.split(".")[0];
  if (prefix === "approval" || prefix === "kill_switch" || action.includes("price_changed")) return "Alta";
  if (prefix === "config" || prefix === "cfo" || prefix === "system" || prefix === "sourcing" || prefix === "marketing") return "Media";
  return "Baja";
}

/** Entrada real del registro presentada como fila de la tabla. */
export function rowFromEntry(entry: AuditEntry, index: number, products: Product[]): AuditRow {
  const productIndex = products.findIndex((product) => entry.resource.includes(product.id));
  return {
    id: entry.id,
    code: `EVT-${String(index + 1).padStart(6, "0")}`,
    at: parseUtc(entry.created_at),
    action: entry.action,
    type: typeOf(entry.action),
    title: entry.action.replace(/[._]/g, " ").replace(/^./, (c) => c.toUpperCase()),
    detail: entry.resource,
    actor: entry.actor,
    actorKind: actorKind(entry.actor),
    projectCode: productIndex >= 0 ? projectCodeFor(productIndex) : null,
    productName: productIndex >= 0 ? products[productIndex].name : null,
    result: resultOf(entry.action),
    criticality: criticalityOf(entry.action),
    correlationId: entry.correlation_id,
    resource: entry.resource,
    before: entry.before,
    after: entry.after,
    isDemo: false,
  };
}

/** Eventos de demostración que llenan el registro, deterministas por día e índice. */
export function demoRows(products: Product[], agents: Agent[], now: number, startIndex: number): AuditRow[] {
  const rows: AuditRow[] = [];
  const dayStart = now - (now % DAY_MS);
  let sequence = startIndex;

  for (let offset = -(WINDOW_DAYS - 1); offset <= 0; offset++) {
    for (let k = 0; k < EVENTS_PER_DAY; k++) {
      const seed = `audit-${offset}-${k}`;
      const template = EVENT_TEMPLATES[Math.floor(demoRandom(seed, "template") * EVENT_TEMPLATES.length)];
      const productIndex = products.length ? Math.floor(demoRandom(seed, "product") * products.length) : -1;
      const product = template.hasProject && productIndex >= 0 ? products[productIndex] : undefined;
      // Las de hoy, solo hasta la hora actual; las de días pasados, repartidas por el día.
      const span = offset === 0 ? now - dayStart : DAY_MS;
      const at = dayStart + offset * DAY_MS + Math.floor(((k + 0.5) / EVENTS_PER_DAY) * span);
      const actor = template.actorRole ? (agents.find((agent) => agent.role === template.actorRole)?.name ?? template.actorFallback) : template.actorFallback;
      const correlation = `CR-${String(90_000 + Math.floor(demoRandom(seed, "correlation") * 9_000)).slice(0, 5)}`;
      rows.push({
        id: `demo-audit-${offset}-${k}`,
        code: `EVT-${String(sequence++).padStart(6, "0")}`,
        at,
        action: template.action,
        type: typeOf(template.action),
        title: template.title,
        detail: template.detail,
        actor,
        actorKind: actorKind(actor),
        projectCode: product ? projectCodeFor(productIndex) : null,
        productName: product ? product.name : null,
        result: template.result,
        criticality: template.criticality,
        correlationId: correlation,
        resource: product ? `product:${product.id}` : template.action.split(".")[0],
        before: null,
        after: null,
        isDemo: true,
      });
    }
  }
  return rows;
}

/** Todas las filas del registro: las reales primero, luego las de demostración. */
export function auditRows(entries: AuditEntry[], products: Product[], agents: Agent[], now: number): AuditRow[] {
  const real = entries.map((entry, index) => rowFromEntry(entry, index, products));
  return [...real, ...demoRows(products, agents, now, real.length + 1)].sort((a, b) => b.at - a.at);
}

export interface AuditKpis {
  today: number;
  critical: number;
  approvals: number;
  configChanges: number;
  errors: number;
  evidenceRate: number;
}

export function auditKpis(rows: AuditRow[], now: number): AuditKpis {
  const dayStart = now - (now % DAY_MS);
  const today = rows.filter((row) => row.at >= dayStart);
  return {
    today: today.length,
    critical: today.filter((row) => row.criticality === "Alta").length,
    approvals: today.filter((row) => row.type === "Aprobación").length,
    configChanges: today.filter((row) => row.type === "Configuración").length,
    errors: today.filter((row) => row.result === "Error").length,
    evidenceRate: EVIDENCE_COMPLETE_RATE,
  };
}

export type AuditWindow = "24h" | "7d" | "30d" | "all";

export const WINDOW_LABELS: Record<AuditWindow, string> = {
  "24h": "Últimas 24 h",
  "7d": "Últimos 7 días",
  "30d": "Últimos 30 días",
  all: "Todo el histórico",
};

export interface RowFilters {
  window: AuditWindow;
  type: string;
  actor: string;
  project: string;
  criticality: string;
  query: string;
}

export const EMPTY_FILTERS: RowFilters = { window: "30d", type: "all", actor: "all", project: "all", criticality: "all", query: "" };

const WINDOW_MS: Record<Exclude<AuditWindow, "all">, number> = { "24h": DAY_MS, "7d": 7 * DAY_MS, "30d": 30 * DAY_MS };

export function filterRows(rows: AuditRow[], filters: RowFilters, now: number): AuditRow[] {
  const query = filters.query.trim().toLowerCase();
  return rows.filter((row) => {
    if (filters.window !== "all" && now - row.at > WINDOW_MS[filters.window]) return false;
    if (filters.type !== "all" && row.type !== filters.type) return false;
    if (filters.actor !== "all" && row.actor !== filters.actor) return false;
    if (filters.project !== "all" && row.projectCode !== filters.project) return false;
    if (filters.criticality !== "all" && row.criticality !== filters.criticality) return false;
    if (!query) return true;
    return `${row.code} ${row.title} ${row.actor} ${row.correlationId} ${row.productName ?? ""} ${row.type}`.toLowerCase().includes(query);
  });
}

export interface Page<T> {
  items: T[];
  page: number;
  pages: number;
  from: number;
  to: number;
  total: number;
}

export function paginate<T>(items: T[], page: number, size: number): Page<T> {
  const pages = Math.max(1, Math.ceil(items.length / size));
  const current = Math.min(Math.max(0, page), pages - 1);
  const from = items.length === 0 ? 0 : current * size + 1;
  return {
    items: items.slice(current * size, current * size + size),
    page: current,
    pages,
    from,
    to: Math.min(items.length, (current + 1) * size),
    total: items.length,
  };
}

// --- Detalle ----------------------------------------------------------------------

export interface DetailField {
  label: string;
  value: string;
}

/** Campos del panel de detalle: lo real primero y lo de demostración señalado. */
export function detailFields(row: AuditRow): { real: DetailField[]; demo: DetailField[] } {
  return {
    real: [
      { label: "Tipo", value: row.action },
      { label: "Actor", value: `${row.actor} (${row.actorKind})` },
      { label: "Proyecto", value: [row.projectCode, row.productName].filter(Boolean).join(" · ") || "—" },
      { label: "Resultado", value: row.result },
      { label: "ID de correlación", value: row.correlationId },
      { label: "Recurso", value: row.resource },
    ],
    demo: [
      { label: "Origen del evento", value: row.isDemo ? "Registro de demostración" : "Registro de auditoría" },
      { label: "Dirección IP", value: row.actorKind === "Persona" ? "192.168.1.24" : "interna" },
      { label: "User agent", value: row.actorKind === "Persona" ? "Mozilla/5.0 · AMAZONA" : "Agente interno" },
      { label: "Hash", value: demoHash(row.id).slice(0, 16) },
      { label: "Evidencias", value: String(demoEvidenceCount(row.id)) },
    ],
  };
}

/** Cambios de estado del evento (reales cuando el backend los guardó). */
export function rowChanges(row: AuditRow): StateChange[] {
  return stateChanges(row.before, row.after);
}

export interface TraceStep {
  code: string;
  title: string;
  actor: string;
  at: number;
}

/** Cadena de eventos que comparten ID de correlación, del primero al último. */
export function correlationTrace(rows: AuditRow[], correlationId: string): TraceStep[] {
  return rows
    .filter((row) => row.correlationId === correlationId)
    .sort((a, b) => a.at - b.at)
    .map((row) => ({ code: row.code, title: row.title, actor: row.actor, at: row.at }));
}

export interface ActorActivity {
  actor: string;
  kind: ActorKind;
  events: number;
  errors: number;
  lastAt: number;
}

export function actorActivity(rows: AuditRow[]): ActorActivity[] {
  const map = new Map<string, ActorActivity>();
  for (const row of rows) {
    const current = map.get(row.actor) ?? { actor: row.actor, kind: row.actorKind, events: 0, errors: 0, lastAt: row.at };
    current.events += 1;
    if (row.result === "Error") current.errors += 1;
    current.lastAt = Math.max(current.lastAt, row.at);
    map.set(row.actor, current);
  }
  return [...map.values()].sort((a, b) => b.events - a.events);
}

export interface ProjectActivity {
  projectCode: string;
  productName: string | null;
  events: number;
  lastAt: number;
}

export function projectActivity(rows: AuditRow[]): ProjectActivity[] {
  const map = new Map<string, ProjectActivity>();
  for (const row of rows) {
    if (!row.projectCode) continue;
    const current = map.get(row.projectCode) ?? { projectCode: row.projectCode, productName: row.productName, events: 0, lastAt: row.at };
    current.events += 1;
    current.lastAt = Math.max(current.lastAt, row.at);
    map.set(row.projectCode, current);
  }
  return [...map.values()].sort((a, b) => b.events - a.events);
}

/** Eventos por día para la vista de timeline. */
export function rowsByDay(rows: AuditRow[]): { day: number; rows: AuditRow[] }[] {
  const map = new Map<number, AuditRow[]>();
  for (const row of rows) {
    const day = row.at - (row.at % DAY_MS);
    map.set(day, [...(map.get(day) ?? []), row]);
  }
  return [...map.entries()]
    .map(([day, list]) => ({ day, rows: list.sort((a, b) => b.at - a.at) }))
    .sort((a, b) => b.day - a.day);
}

export interface Anomaly {
  level: "Crítica" | "Media" | "Baja";
  count: number;
  text: string;
}

/** Anomalías de los últimos 7 días: las de demostración más las que se ven en el registro. */
export function anomalies(rows: AuditRow[], now: number): Anomaly[] {
  const week = rows.filter((row) => now - row.at <= 7 * DAY_MS);
  const errors = week.filter((row) => row.result === "Error").length;
  const list: Anomaly[] = DEMO_ANOMALIES.map((item) => ({ ...item, level: item.level as Anomaly["level"] }));
  if (errors > 0) list.push({ level: "Media", count: errors, text: "Errores registrados esta semana" });
  return list;
}

/** Tipos y actores presentes en el registro, para los filtros. */
export function filterOptions(rows: AuditRow[]): { types: string[]; actors: string[]; projects: string[] } {
  return {
    types: [...new Set(rows.map((row) => row.type))].sort((a, b) => a.localeCompare(b, "es")),
    actors: [...new Set(rows.map((row) => row.actor))].sort((a, b) => a.localeCompare(b, "es")),
    projects: [...new Set(rows.flatMap((row) => (row.projectCode ? [row.projectCode] : [])))].sort(),
  };
}
