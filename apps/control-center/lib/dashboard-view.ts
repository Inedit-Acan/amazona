import type { Agent, AgentExecution, Approval, PipelineReview, Product } from "./api.ts";
import { teamOf } from "./agents.ts";
import { agentCards, type AgentCardView } from "./agents-view.ts";
import { requestFromApproval, requestFromReview, type ApprovalRequest, type ProductContext } from "./approvals-view.ts";
import type { CatalogEntry, DashboardReads } from "./dashboard-reads.ts";
import { demoExecutions } from "./demo/agents.ts";
import type { RequestKind, Severity } from "./demo/approvals.ts";
import { dedupeQuotesBySupplier } from "./economics.ts";
import { buildBaseline } from "./economics-baseline.ts";
import { evaluate } from "./economics-model.ts";
import { formatInteger, formatPercent } from "./format.ts";
import {
  listOf,
  READ_ERROR_TEXT,
  READ_UNAVAILABLE_TEXT,
  READ_UNAVAILABLE_VALUE,
  READ_UNREAD_TEXT,
  worstOf,
  type ReadState,
} from "./read-state.ts";
import { buildRows, type Level, type Risk } from "./research-view.ts";
import type { Settled } from "./revenue-view.ts";

// Vista del Panel (mockup docs/design/«dashboard inicial.png»). El Panel no tiene
// datos propios: es el resumen de las demás pantallas, así que aquí no se calcula
// nada nuevo, solo se elige y se da forma a lo que ya calculan sus libs: la actividad
// de los agentes de Agentes (`lib/agents-view.ts`), las decisiones de Aprobaciones
// (`lib/approvals-view.ts`) y las oportunidades de Investigación
// (`lib/research-view.ts`). Si una cifra no cuadra con su pantalla, el fallo está en
// la lib de origen, no aquí.
//
// Los INGRESOS ya no están aquí (M45): salen del registro de ingresos verificados y
// los da `lib/revenue-view.ts`. Las ventas y el beneficio que antes se modelaban a
// partir del P&L de Finanzas y de pedidos de demostración se retiraron del Panel:
// AMAZONA no factura, y un modelo no se enseña como si fuera una medición.

// --- KPIs de cabecera ---------------------------------------------------------------

export interface DashboardKpis {
  /** Agentes registrados y cuántos no están fuera de servicio (real). */
  agentsOnline: number;
  agentsTotal: number;
  agentsRatio: number;
  /** Decisiones pendientes y cuántas vienen de una solicitud real del backend. */
  pendingDecisions: number;
  realDecisions: number;
}

export function dashboardKpis(input: { agents: Pick<Agent, "status">[]; requests: ApprovalRequest[] }): DashboardKpis {
  const { agents, requests } = input;
  const online = agents.filter((agent) => agent.status !== "OFFLINE").length;
  const pending = requests.filter((request) => request.status === "PENDING");
  return {
    agentsOnline: online,
    agentsTotal: agents.length,
    agentsRatio: agents.length > 0 ? online / agents.length : 0,
    pendingDecisions: pending.length,
    realDecisions: pending.filter((request) => !request.isDemo).length,
  };
}

// --- Actividad empresarial ----------------------------------------------------------

export interface ActivityRow {
  id: string;
  name: string;
  team: AgentCardView["team"];
  /** Tarea en curso (de demostración); null si el agente no está ejecutando. */
  currentTask: string | null;
  runs: number;
  successRate: number | null;
  lastActivityAt: number | null;
  state: AgentCardView["activity"];
}

/** Los agentes que más cuentan ahora mismo: primero los que están ejecutando y
 * luego por actividad más reciente. */
export function activityRows(cards: AgentCardView[], limit: number): ActivityRow[] {
  return [...cards]
    .sort((a, b) => {
      const running = Number(b.activity === "running") - Number(a.activity === "running");
      if (running !== 0) return running;
      return (b.lastActivityAt ?? 0) - (a.lastActivityAt ?? 0);
    })
    .slice(0, limit)
    .map((card) => ({
      id: card.id,
      name: card.name,
      team: card.team,
      currentTask: card.currentTask,
      runs: card.runs,
      successRate: card.successRate,
      lastActivityAt: card.lastActivityAt,
      state: card.activity,
    }));
}

// --- Decisiones necesarias ----------------------------------------------------------

const SEVERITY_ORDER: Record<Severity, number> = { "Crítica": 0, Alta: 1, Media: 2, Baja: 3 };

export interface DecisionRow {
  id: string;
  title: string;
  /** Qué se aprueba, en una línea. */
  detail: string;
  kind: RequestKind;
  kindLabel: string;
  severity: Severity;
  requestedAt: number;
  isDemo: boolean;
}

/** Las solicitudes pendientes que hay que mirar antes: por severidad y, a igual
 * severidad, las más recientes. */
export function decisionRows(requests: ApprovalRequest[], limit: number): DecisionRow[] {
  return requests
    .filter((request) => request.status === "PENDING")
    .sort((a, b) => SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity] || b.requestedAt - a.requestedAt)
    .slice(0, limit)
    .map((request) => ({
      id: request.id,
      title: request.title,
      detail: request.approveImpact[0] ?? request.findings[0] ?? request.fields[0]?.label ?? "Requiere tu decisión.",
      kind: request.kind,
      kindLabel: request.kindLabel,
      severity: request.severity,
      requestedAt: request.requestedAt,
      isDemo: request.isDemo,
    }));
}

// --- Oportunidades ------------------------------------------------------------------

export const OPPORTUNITY_STAGES = ["En observación", "Evaluación", "Análisis", "Validación", "Lanzamiento"] as const;
export type OpportunityStage = (typeof OPPORTUNITY_STAGES)[number];

/** Cuántos análisis reales tiene un producto: lo que decide en qué fase está. */
export interface ProductDepth {
  productId: string;
  quotes: number;
  economics: number;
  legal: number;
  storefronts: number;
  campaigns: number;
  /** Margen de contribución del modelo económico (fracción), el mismo que enseña
   * Economía; null si el producto no llega ni a tener modelo. */
  marginPct: number | null;
  /** El modelo parte de un análisis económico real, no solo de supuestos demo. */
  marginIsReal: boolean;
}

/** Fase del producto según hasta dónde ha llegado de verdad su pipeline. No se
 * inventa: si no tiene ni una cotización, está «En observación». */
export function opportunityStage(depth: ProductDepth): OpportunityStage {
  if (depth.storefronts > 0 || depth.campaigns > 0) return "Lanzamiento";
  if (depth.legal > 0) return "Validación";
  if (depth.economics > 0) return "Análisis";
  if (depth.quotes > 0) return "Evaluación";
  return "En observación";
}

// =====================================================================================================================
// M46 · Commit 6 — Vistas con estado de lectura.
//
// Todo lo que sigue recibe `ReadState` (lib/read-state.ts), no listas: una lectura que FALLÓ o que NO SE HIZO no es una
// lista vacía. Reglas que estas funciones cumplen y que las pruebas fijan:
//   * `error` y `unread` NUNCA producen un 0, un porcentaje, una suma ni un «Sin datos»: producen un estado explícito.
//   * La demostración solo se activa con `empty` (el backend dijo «el log está vacío»), jamás con `error`.
//   * Ninguna cifra se calcula sobre un recurso que no tiene una lectura válida.
// =====================================================================================================================

export type UnavailableState = "error" | "unread";

const DAY_MS = 86_400_000;

/** `Datos no disponibles en este momento: los agentes, las aprobaciones.` */
export function unavailableText(sources: string[]): string {
  return `${READ_UNAVAILABLE_TEXT}: ${sources.join(", ")}.`;
}

function failedSources(entries: ReadonlyArray<readonly [string, ReadState<unknown>]>): {
  state: UnavailableState;
  sources: string[];
} | null {
  const failed = entries.filter(([, state]) => state.kind === "error" || state.kind === "unread");
  if (failed.length === 0) return null;
  return { state: worstOf(failed.map(([, state]) => state)) ?? "error", sources: failed.map(([name]) => name) };
}

// --- Una cifra de cabecera -----------------------------------------------------------------------------------------

export type KpiView =
  | { kind: "value"; value: string; caption: string }
  /** Lectura válida y el resultado es «nada»: el cero (o el «Sin …») es un hecho. */
  | { kind: "empty"; value: string; caption: string }
  | { kind: "error" | "unread"; value: string; caption: string };

const unavailableKpi = (state: Extract<ReadState<unknown>, { kind: "error" | "unread" }>): KpiView =>
  state.kind === "error"
    ? { kind: "error", value: READ_UNAVAILABLE_VALUE, caption: state.message }
    : { kind: "unread", value: READ_UNREAD_TEXT, caption: state.reason };

/** «Agentes en línea». Sin agentes leídos no hay «0 / 0» ni «0 %»: hay un error, o «Sin agentes» si el registro dijo que
 * está vacío. */
export function agentsKpiView(agents: ReadState<Agent[]>, executions: ReadState<AgentExecution[]>): KpiView {
  if (agents.kind === "error" || agents.kind === "unread") return unavailableKpi(agents);
  if (agents.kind === "empty") return { kind: "empty", value: "Sin agentes", caption: "El registro no tiene ningún agente." };
  const { agentsOnline, agentsTotal, agentsRatio } = dashboardKpis({ agents: agents.data, requests: [] });
  const note = executions.kind === "error" || executions.kind === "unread" ? " · ejecuciones no disponibles" : "";
  return {
    kind: "value",
    value: `${agentsOnline} / ${agentsTotal}`,
    caption: `${formatPercent(agentsRatio, 0)} operativos${note}`,
  };
}

// --- Actividad empresarial -----------------------------------------------------------------------------------------

/** Ejecuciones por día de los siete últimos (las barras de la tarjeta de agentes). */
export function runsPerDay(runs: Pick<AgentExecution, "created_at">[], now: number): number[] {
  const dayStart = now - (now % DAY_MS);
  return Array.from({ length: 7 }, (_, index) => {
    const from = dayStart - (6 - index) * DAY_MS;
    return runs.filter((run) => {
      const at = new Date(`${run.created_at}${/[zZ]|[+-]\d{2}:?\d{2}$/.test(run.created_at) ? "" : "Z"}`).getTime();
      return at >= from && at < from + DAY_MS;
    }).length;
  });
}

export type ActivityView =
  | {
      kind: "rows";
      rows: ActivityRow[];
      /** El log de ejecuciones es válido y está VACÍO: se usan las de demostración (y se dice). Nunca por un error. */
      usingDemoRuns: boolean;
      runsPerDay: number[];
    }
  /** El registro de agentes es válido y está vacío. */
  | { kind: "no-agents" }
  | { kind: "unavailable"; state: UnavailableState; sources: string[]; message: string };

export function activityView(input: {
  agents: ReadState<Agent[]>;
  executions: ReadState<AgentExecution[]>;
  now: number;
  limit: number;
}): ActivityView {
  const { agents, executions, now, limit } = input;
  const failed = failedSources([
    ["los agentes", agents],
    ["el log de ejecuciones", executions],
  ]);
  if (failed) return { kind: "unavailable", ...failed, message: unavailableText(failed.sources) };
  if (agents.kind === "empty") return { kind: "no-agents" };
  if (agents.kind !== "loaded") return { kind: "no-agents" }; // inalcanzable: `failedSources` ya filtró error/unread

  const usingDemoRuns = executions.kind === "empty";
  const runs = executions.kind === "loaded" ? executions.data : demoExecutions(agents.data, teamOf, now, 7);
  const cards = agentCards(agents.data, runs, now);
  return { kind: "rows", rows: activityRows(cards, limit), usingDemoRuns, runsPerDay: runsPerDay(runs, now) };
}

// --- Decisiones necesarias -----------------------------------------------------------------------------------------

export type DecisionsView =
  | { kind: "ready"; requests: ApprovalRequest[]; pending: number; fromBackend: number }
  | { kind: "unavailable"; state: UnavailableState; sources: string[]; message: string };

/** Las solicitudes del backend (aprobaciones y revisiones) más las de demostración. Si cualquiera de las dos lecturas
 * del backend falló NO hay lista parcial ni conteo: «0 del backend» sería afirmar que el backend no tiene ninguna. */
export function decisionsView(input: {
  approvals: ReadState<Approval[]>;
  reviews: ReadState<PipelineReview[]>;
  demo: ApprovalRequest[];
  now: number;
}): DecisionsView {
  const { approvals, reviews, demo, now } = input;
  const failed = failedSources([
    ["las aprobaciones", approvals],
    ["las revisiones de pipeline", reviews],
  ]);
  if (failed) return { kind: "unavailable", ...failed, message: unavailableText(failed.sources) };

  const requests = [
    ...(listOf(approvals) ?? []).map((approval) => requestFromApproval(approval, now)),
    ...(listOf(reviews) ?? []).map((review) => requestFromReview(review, now)),
    ...demo,
  ];
  const pending = requests.filter((request) => request.status === "PENDING");
  return {
    kind: "ready",
    requests,
    pending: pending.length,
    fromBackend: pending.filter((request) => !request.isDemo).length,
  };
}

/** «Aprobaciones pendientes». El cero solo existe si las dos lecturas del backend fueron válidas. */
export function decisionsKpiView(view: DecisionsView): KpiView {
  if (view.kind === "unavailable") {
    return view.state === "error"
      ? { kind: "error", value: READ_UNAVAILABLE_VALUE, caption: view.message }
      : { kind: "unread", value: READ_UNREAD_TEXT, caption: view.message };
  }
  const caption =
    view.pending === 0
      ? "Nada esperando tu decisión."
      : view.fromBackend > 0
        ? `${view.fromBackend} del backend · ${view.pending - view.fromBackend} de demostración`
        : "Requieren una decisión";
  return { kind: view.pending === 0 ? "empty" : "value", value: formatInteger(view.pending), caption };
}

// --- Oportunidades -------------------------------------------------------------------------------------------------

/** Una celda que puede no tener valor: el motivo es un estado explícito, nunca una cifra ni una fase inventadas. */
export type Cell<T> = { kind: "value"; value: T } | { kind: "error"; text: string } | { kind: "unread"; text: string };

export interface OpportunityViewRow {
  productId: string;
  name: string;
  subcategory: string;
  demand: Level;
  risk: Risk;
  score: number;
  /** Las señales de mercado son de demostración (no se investigó en esta sesión). */
  signalsAreDemo: boolean;
  /** Hasta dónde ha llegado de verdad su pipeline; indeterminada si alguna de sus cinco lecturas falló. */
  stage: Cell<OpportunityStage>;
  /** Margen (fracción) del modelo económico y si parte de un análisis económico real. */
  margin: Cell<{ pct: number; isReal: boolean }>;
}

export type OpportunitiesView =
  | { kind: "rows"; rows: OpportunityViewRow[] }
  /** La lectura del catálogo es válida y no hay productos. */
  | { kind: "no-catalog" }
  | { kind: "unavailable"; state: UnavailableState; message: string };

const cellOf = (state: UnavailableState): { kind: UnavailableState; text: string } =>
  state === "error" ? { kind: "error", text: READ_ERROR_TEXT } : { kind: "unread", text: READ_UNREAD_TEXT };

function pipelineCells(entry: CatalogEntry | undefined): Pick<OpportunityViewRow, "stage" | "margin"> {
  // Un producto del que no se leyó el pipeline (pasa del tope) no está «En observación»: no se sabe.
  if (!entry) return { stage: cellOf("unread"), margin: cellOf("unread") };

  const quotes = listOf(entry.quotes);
  const economics = listOf(entry.economics);
  const legal = listOf(entry.legal);
  const storefronts = listOf(entry.storefronts);
  const campaigns = listOf(entry.campaigns);

  const stageFailure = worstOf([entry.quotes, entry.economics, entry.legal, entry.storefronts, entry.campaigns]);
  const stage: OpportunityViewRow["stage"] =
    stageFailure === null && quotes && economics && legal && storefronts && campaigns
      ? {
          kind: "value",
          value: opportunityStage({
            productId: entry.product.id,
            quotes: quotes.length,
            economics: economics.length,
            legal: legal.length,
            storefronts: storefronts.length,
            campaigns: campaigns.length,
            marginPct: null,
            marginIsReal: false,
          }),
        }
      : cellOf(stageFailure ?? "unread");

  // `listOf` es `null` para un `error` y para un `unread`: sin lectura válida de proveedores y de economía no hay margen.
  if (!quotes || !economics) return { stage, margin: cellOf(worstOf([entry.quotes, entry.economics]) ?? "unread") };
  const analysis = economics[0];
  const options = dedupeQuotesBySupplier(quotes, analysis?.supplier_quote_id);
  const quote = options.find((q) => q.id === analysis?.supplier_quote_id) ?? options[0];
  return {
    stage,
    margin: {
      kind: "value",
      value: { pct: evaluate(buildBaseline(quote, analysis).inputs).contributionMargin, isReal: economics.length > 0 },
    },
  };
}

export function opportunitiesView(input: {
  products: ReadState<Product[]>;
  catalog: CatalogEntry[];
  limit: number;
}): OpportunitiesView {
  const { products, catalog, limit } = input;
  if (products.kind === "error") return { kind: "unavailable", state: "error", message: products.message };
  if (products.kind === "unread") return { kind: "unavailable", state: "unread", message: products.reason };
  if (products.kind === "empty") return { kind: "no-catalog" };

  const entries = new Map(catalog.map((entry) => [entry.product.id, entry] as const));
  const rows = buildRows(products.data, [])
    .slice(0, limit)
    .map(
      (row): OpportunityViewRow => ({
        productId: row.productId,
        name: row.name,
        subcategory: row.subcategory,
        demand: row.demand,
        risk: row.risk,
        score: row.score,
        signalsAreDemo: row.isDemo,
        ...pipelineCells(entries.get(row.productId)),
      }),
    );
  return { kind: "rows", rows };
}

/** El producto real más avanzado, sobre el que se construyen las solicitudes de demostración. Solo entran los productos
 * con sus cinco lecturas válidas: una lectura que falló no es «cero análisis». */
export function demoContext(catalog: CatalogEntry[]): ProductContext | undefined {
  const complete = catalog.flatMap((entry) => {
    const quotes = listOf(entry.quotes);
    const economics = listOf(entry.economics);
    const legal = listOf(entry.legal);
    const storefronts = listOf(entry.storefronts);
    const campaigns = listOf(entry.campaigns);
    if (!quotes || !economics || !legal || !storefronts || !campaigns) return [];
    const depth = quotes.length + economics.length + legal.length + storefronts.length + campaigns.length;
    return [{ entry, quotes, economics, legal, storefronts, campaigns, depth }];
  });
  const best = [...complete].sort((a, b) => b.depth - a.depth)[0];
  if (!best) return undefined;
  const { entry, quotes, economics, legal, storefronts, campaigns } = best;
  return {
    product: entry.product,
    quotes,
    economics,
    legal,
    storefronts,
    campaigns,
    projectCode: entry.projectCode,
    market: storefronts[0]?.market ?? legal[0]?.market ?? "eu",
  };
}

// --- Qué lecturas fallaron -----------------------------------------------------------------------------------------

export interface ReadIssue {
  label: string;
}

/** Las lecturas del Panel que FALLARON (`error`). Un producto que pasa del tope es `unread` por diseño y no es un fallo. */
export function readIssues(
  reads: DashboardReads,
  revenue: { summary: Settled<unknown>; series: Settled<unknown>; entries: Settled<unknown> },
): ReadIssue[] {
  const issues: ReadIssue[] = [];
  const named: Array<[string, ReadState<unknown>]> = [
    ["el catálogo de productos", reads.products],
    ["los agentes", reads.agents],
    ["el log de ejecuciones", reads.executions],
    ["las aprobaciones", reads.approvals],
    ["las revisiones de pipeline", reads.reviews],
  ];
  for (const [label, state] of named) if (state.kind === "error") issues.push({ label });
  const failedProducts = reads.catalog.filter((entry) =>
    [entry.quotes, entry.economics, entry.legal, entry.storefronts, entry.campaigns].some((state) => state.kind === "error"),
  ).length;
  if (failedProducts > 0) {
    issues.push({ label: `el pipeline de ${failedProducts} producto${failedProducts === 1 ? "" : "s"}` });
  }
  if (!revenue.summary.ok || !revenue.series.ok || !revenue.entries.ok) issues.push({ label: "los ingresos" });
  return issues;
}
