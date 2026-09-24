import type { Agent } from "./api.ts";
import type { AgentCardView } from "./agents-view.ts";
import type { ApprovalRequest } from "./approvals-view.ts";
import type { Pnl } from "./cfo-view.ts";
import type { RequestKind, Severity } from "./demo/approvals.ts";
import type { Order } from "./operations-view.ts";
import { startOfDay } from "./operations-view.ts";
import type { Level, ResearchRow, Risk } from "./research-view.ts";

// Vista del Panel (mockup docs/design/«dashboard inicial.png»). El Panel no tiene
// datos propios: es el resumen de las demás pantallas, así que aquí no se calcula
// nada nuevo, solo se elige y se da forma a lo que ya calculan sus libs. Ventas y
// beneficio salen del mismo P&L que Finanzas (`lib/cfo-view.ts`), la actividad de
// los agentes de Agentes (`lib/agents-view.ts`), las decisiones de Aprobaciones
// (`lib/approvals-view.ts`), las oportunidades de Investigación
// (`lib/research-view.ts`) y la serie de 30 días de los pedidos de Operaciones
// (`lib/operations-view.ts`). Si una cifra no cuadra con su pantalla, el fallo
// está en la lib de origen, no aquí.

const DAY_MS = 86_400_000;
/** Días del mes que cubre el P&L de Finanzas (su unidad es el mes). */
const PNL_DAYS = 30;
const round2 = (value: number) => Math.round(value * 100) / 100;

// --- KPIs de cabecera ---------------------------------------------------------------

export interface DashboardKpis {
  /** Ingresos y beneficio neto del mes, del mismo P&L que Finanzas. */
  sales: number;
  salesDelta: number | null;
  profit: number;
  profitDelta: number | null;
  /** Agentes registrados y cuántos no están fuera de servicio (real). */
  agentsOnline: number;
  agentsTotal: number;
  agentsRatio: number;
  /** Decisiones pendientes y cuántas vienen de una solicitud real del backend. */
  pendingDecisions: number;
  realDecisions: number;
}

export function dashboardKpis(input: {
  pnl: Pnl;
  previousPnl: Pnl;
  agents: Pick<Agent, "status">[];
  requests: ApprovalRequest[];
}): DashboardKpis {
  const { pnl, previousPnl, agents, requests } = input;
  const online = agents.filter((agent) => agent.status !== "OFFLINE").length;
  const pending = requests.filter((request) => request.status === "PENDING");
  return {
    sales: pnl.revenue,
    salesDelta: previousPnl.revenue > 0 ? pnl.revenue / previousPnl.revenue - 1 : null,
    profit: pnl.net,
    profitDelta: previousPnl.net > 0 ? pnl.net / previousPnl.net - 1 : null,
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

export interface OpportunityRow {
  productId: string;
  name: string;
  subcategory: string;
  demand: Level;
  risk: Risk;
  score: number;
  /** Margen (fracción): el del modelo económico si el producto tiene modelo, si no
   * el rango de Investigación. */
  marginPct: number;
  /** El margen sale de un análisis económico real del producto. */
  marginIsReal: boolean;
  stage: OpportunityStage;
  /** Las señales de mercado son de demostración (no se investigó en esta sesión). */
  signalsAreDemo: boolean;
}

/** Las oportunidades con mejor score de Investigación, con el margen real del
 * producto cuando lo tiene y la fase a la que ha llegado su pipeline. */
export function opportunityRows(rows: ResearchRow[], depths: ProductDepth[], limit: number): OpportunityRow[] {
  const byProduct = new Map(depths.map((depth) => [depth.productId, depth] as const));
  return rows.slice(0, limit).map((row) => {
    const depth = byProduct.get(row.productId);
    const modelled = depth?.marginPct ?? null;
    return {
      productId: row.productId,
      name: row.name,
      subcategory: row.subcategory,
      demand: row.demand,
      risk: row.risk,
      score: row.score,
      marginPct: modelled ?? (row.margin[0] + row.margin[1]) / 2 / 100,
      marginIsReal: modelled !== null && (depth?.marginIsReal ?? false),
      stage: depth ? opportunityStage(depth) : "En observación",
      signalsAreDemo: row.isDemo,
    };
  });
}

// --- Ventas y margen de los últimos 30 días -----------------------------------------

export interface SalesPoint {
  /** Índice 0…days-1; `days-1` es hoy. */
  x: number;
  at: number;
  sales: number;
  /** Margen operativo del día (fracción). */
  marginPct: number;
}

/** Ventas por día: los pedidos de Operaciones dan la FORMA (qué días se vendió
 * más) y el P&L de Finanzas el NIVEL. El P&L es mensual, así que una ventana de
 * `days` días vale su parte proporcional: a 30 días la gráfica suma exactamente
 * los ingresos del KPI y de Finanzas. El margen de cada día sale del mismo P&L:
 * los costes variables van con las ventas y los operativos son fijos, así que un
 * día de más ventas deja más margen. Es un modelo, no una medición: AMAZONA no
 * factura. */
export function salesSeries(orders: Order[], pnl: Pnl, today: string, days: number): SalesPoint[] {
  const end = startOfDay(today);
  const from = end - (days - 1) * DAY_MS;
  const byDay = new Map<number, number>();
  let total = 0;
  for (const order of orders) {
    if (order.createdAt < from || order.createdAt > end) continue;
    byDay.set(order.createdAt, (byDay.get(order.createdAt) ?? 0) + order.amount);
    total += order.amount;
  }
  const windowRevenue = (pnl.revenue * days) / PNL_DAYS;
  const variableRate = pnl.revenue > 0 ? pnl.cogs / pnl.revenue : 0;
  const fixedPerDay = pnl.operatingCosts / PNL_DAYS;
  return Array.from({ length: days }, (_, x) => {
    const at = from + x * DAY_MS;
    // Sin pedidos en la ventana, se reparte a partes iguales.
    const share = total > 0 ? (byDay.get(at) ?? 0) / total : 1 / days;
    const sales = round2(windowRevenue * share);
    return { x, at, sales, marginPct: sales > 0 ? Math.max(0, 1 - variableRate - fixedPerDay / sales) : 0 };
  });
}
