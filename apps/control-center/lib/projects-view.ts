import type { AuditEntry, EconomicAnalysis, LegalAnalysis, MarketingCampaign, OperationsRecord, Product, Storefront, SupplierQuote } from "./api.ts";
import { DEMO_ACTUAL_SPREAD, DEMO_CLOSED_PROJECTS, DEMO_PROJECTS, DEMO_SUPPLIER_ADVANCE, PROJECT_CODE_PREFIX } from "./demo/projects.ts";
import { demoRandom } from "./demo/random.ts";
import { launchReadiness } from "./ecommerce.ts";
import { dedupeQuotesBySupplier } from "./economics.ts";
import { buildBaseline } from "./economics-baseline.ts";
import { evaluate } from "./economics-model.ts";
import { buildLegalView } from "./legal-view.ts";
import { ACTIVE_STATUSES, daysBetween, type Order } from "./operations-view.ts";
import { buildRows } from "./research-view.ts";
import { rankSuppliers } from "./sourcing-view.ts";

// Vista de la pantalla de Proyectos (mockup docs/design/proyectos.png). Un
// proyecto del backend es un grafo de tareas del Director ejecutivo: no tiene
// producto, mercado, fase de negocio, salud ni beneficio, y hoy no hay ninguno
// creado. Aquí cada producto real se presenta como un proyecto con SUS datos
// reales (score de Investigación, proveedor, análisis económico y legal, tienda,
// campaña y operaciones) y la cartera se completa con proyectos de demostración
// (lib/demo/projects.ts). Las fases y los scores son los mismos que enseña cada
// pantalla del pipeline.

const DAY_MS = 86_400_000;
const round2 = (value: number) => Math.round(value * 100) / 100;

export type PhaseKey = "research" | "suppliers" | "economics" | "legal" | "store" | "marketing" | "operations" | "scale";

export const PHASES: { key: PhaseKey; label: string; href: string }[] = [
  { key: "research", label: "Investigación", href: "/research" },
  { key: "suppliers", label: "Proveedores", href: "/sourcing" },
  { key: "economics", label: "Economía", href: "/economics" },
  { key: "legal", label: "Legal", href: "/legal" },
  { key: "store", label: "Tienda", href: "/ecommerce" },
  { key: "marketing", label: "Marketing", href: "/marketing" },
  { key: "operations", label: "Operaciones", href: "/operations" },
  { key: "scale", label: "Escala", href: "/cfo" },
];

export type PhaseState = "done" | "current" | "blocked" | "todo";

export interface ProjectPhase {
  key: PhaseKey;
  label: string;
  href: string;
  state: PhaseState;
  /** Texto bajo la fase: «92/100», «Aprobado», «Ready 94 %», «Pendiente»… */
  detail: string;
  /** 0–100 cuando la fase tiene puntuación. */
  score: number | null;
}

export type ProjectStatusLabel = "En curso" | "En riesgo" | "Bloqueado" | "Pausado" | "Cerrado";

export interface ProjectCard {
  id: string;
  code: string;
  name: string;
  category: string;
  market: string;
  phases: ProjectPhase[];
  phase: PhaseKey;
  phaseLabel: string;
  status: ProjectStatusLabel;
  /** 0–100. */
  health: number;
  /** 0–1. */
  progress: number;
  projectedProfit: number | null;
  realProfit: number | null;
  capitalExposed: number;
  startedAt: number;
  productId?: string;
  /** El proyecto entero es de demostración (no hay producto detrás). */
  isDemo: boolean;
}

export interface ProductProjectInput {
  product: Product;
  quotes: SupplierQuote[];
  economics: EconomicAnalysis[];
  legal: LegalAnalysis[];
  storefronts: Storefront[];
  campaigns: MarketingCampaign[];
  operations: OperationsRecord[];
  /** Pedidos del producto (Operaciones) para el beneficio real y el capital expuesto. */
  orders: Order[];
  /** Entradas de auditoría del producto, para la fecha de inicio y la actividad. */
  audit: AuditEntry[];
  market: string;
}

/** Código del proyecto de un producto por su posición en el catálogo (AMZ-0024,
 * AMZ-0023...). Lo comparten Proyectos y Aprobaciones. */
export function projectCodeFor(index: number): string {
  return `${PROJECT_CODE_PREFIX}${String(24 - index).padStart(4, "0")}`;
}

function phase(key: PhaseKey, state: PhaseState, detail: string, score: number | null = null): ProjectPhase {
  const meta = PHASES.find((p) => p.key === key)!;
  return { key, label: meta.label, href: meta.href, state, detail, score };
}

/** Proyecto de un producto real: cada fase lee lo que su pantalla ya enseña. */
export function projectFromProduct(input: ProductProjectInput, index: number, today: number): ProjectCard {
  const { product, quotes, economics, legal, storefronts, campaigns, operations, orders, audit, market } = input;
  const analysis = economics[0];
  const options = dedupeQuotesBySupplier(quotes, analysis?.supplier_quote_id);
  const quote = options.find((q) => q.id === analysis?.supplier_quote_id) ?? options[0];
  const baseline = buildBaseline(quote, analysis);
  const economicsResult = evaluate(baseline.inputs);
  const researchScore = buildRows([product], [])[0].score;

  const phases: ProjectPhase[] = [];
  phases.push(phase("research", "done", `${researchScore}/100`, researchScore));

  const ranked = quotes.length > 0 ? rankSuppliers(dedupeQuotesBySupplier(quotes)) : [];
  const supplierScore = ranked[0] ? Math.round(ranked[0].score) : null;
  phases.push(quotes.length > 0 ? phase("suppliers", "done", `${supplierScore}/100`, supplierScore) : phase("suppliers", "current", "Sin cotizaciones"));

  const marginScore = analysis ? Math.round(Math.max(0, Math.min(1, economicsResult.contributionMargin / 0.5)) * 100) : null;
  phases.push(analysis ? phase("economics", "done", `${marginScore}/100`, marginScore) : phase("economics", "todo", "Pendiente"));

  const legalAnalysis = legal.find((l) => l.market === market) ?? legal[0];
  const legalView = buildLegalView(market, legalAnalysis);
  phases.push(
    legalAnalysis
      ? phase(
          "legal",
          legalView.gate.state === "blocked" ? "blocked" : legalView.gate.state === "review" ? "current" : "done",
          legalView.gate.state === "blocked" ? "Bloqueado" : legalView.gate.state === "review" ? "Revisión" : "Aprobado",
          Math.round(legalView.compliance.ratio * 100),
        )
      : phase("legal", "todo", "Pendiente"),
  );

  const storefront = storefronts.find((s) => s.market === market) ?? storefronts[0];
  const readiness = launchReadiness({ economic: analysis, storefront, legal: legalAnalysis });
  const readyRatio = readiness.length ? readiness.filter((r) => r.state === "done").length / readiness.length : 0;
  phases.push(
    storefront ? phase("store", "done", `Ready ${Math.round(readyRatio * 100)} %`, Math.round(readyRatio * 100)) : phase("store", "todo", "Pendiente"),
  );

  const campaign = campaigns.find((c) => c.market === market) ?? campaigns[0];
  phases.push(campaign ? phase("marketing", "current", "En curso") : phase("marketing", "todo", "Pendiente"));

  const operationsRecord = operations.find((o) => o.market === market) ?? operations[0];
  phases.push(operationsRecord ? phase("operations", "done", "Simulado") : phase("operations", "todo", "Pendiente"));
  phases.push(phase("scale", "blocked", "Bloqueado"));

  const activeOrders = orders.filter((o) => ACTIVE_STATUSES.includes(o.status));
  const deliveredOrders = orders.filter((o) => o.status === "delivered" || o.status === "returned");
  const realProfit = deliveredOrders.length
    ? round2(deliveredOrders.reduce((sum, o) => sum + o.units, 0) * economicsResult.contribution - baseline.inputs.monthlyFixedCosts)
    : null;
  const startedAt = audit.length ? Math.min(...audit.map((entry) => Date.parse(entry.created_at))) : today - 30 * DAY_MS;

  return {
    id: product.id,
    code: projectCodeFor(index),
    name: product.name,
    category: product.category,
    market,
    phases,
    ...currentPhase(phases),
    status: statusOf(phases),
    health: healthOf(phases),
    progress: progressOf(phases),
    projectedProfit: round2(economicsResult.monthlyProfit),
    realProfit,
    capitalExposed: round2(activeOrders.reduce((sum, o) => sum + o.amount, 0) * DEMO_SUPPLIER_ADVANCE),
    startedAt,
    productId: product.id,
    isDemo: false,
  };
}

/** La fase actual es la primera que no está cerrada, en el orden del pipeline. */
function currentPhase(phases: ProjectPhase[]): { phase: PhaseKey; phaseLabel: string } {
  const current = phases.find((p) => p.state !== "done") ?? phases[phases.length - 1];
  return { phase: current.key, phaseLabel: current.label };
}

function statusOf(phases: ProjectPhase[]): ProjectStatusLabel {
  if (phases.some((p) => p.state === "blocked" && p.key !== "scale")) return "Bloqueado";
  const scores = phases.filter((p) => p.score !== null).map((p) => p.score!);
  if (scores.some((score) => score < 50)) return "En riesgo";
  return "En curso";
}

function healthOf(phases: ProjectPhase[]): number {
  const scores = phases.filter((p) => p.score !== null).map((p) => p.score!);
  if (scores.length === 0) return 0;
  const average = scores.reduce((sum, score) => sum + score, 0) / scores.length;
  const blocked = phases.filter((p) => p.state === "blocked" && p.key !== "scale").length;
  return Math.max(0, Math.min(100, Math.round(average - blocked * 15)));
}

function progressOf(phases: ProjectPhase[]): number {
  const done = phases.filter((p) => p.state === "done").length;
  const current = phases.filter((p) => p.state === "current").length;
  return (done + current * 0.5) / phases.length;
}

/** Proyectos de ejemplo que completan la cartera, deterministas por nombre. */
export function demoProjects(today: number, startIndex: number): ProjectCard[] {
  const rows: ProjectCard[] = DEMO_PROJECTS.map((demo, k) => {
    const phaseIndex = PHASES.findIndex((p) => p.key === demo.phase);
    const phases = PHASES.map((meta, index) => {
      if (index < phaseIndex) return phase(meta.key, "done", `${60 + Math.round(demoRandom(demo.name, `phase-${index}`) * 38)}/100`, 60 + Math.round(demoRandom(demo.name, `phase-${index}`) * 38));
      if (index === phaseIndex) return phase(meta.key, demo.status === "Pausado" ? "todo" : "current", demo.status === "Pausado" ? "Pausado" : "En curso");
      return phase(meta.key, meta.key === "scale" ? "blocked" : "todo", meta.key === "scale" ? "Bloqueado" : "Pendiente");
    });
    return {
      id: `demo-${demo.name.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`,
      code: `${PROJECT_CODE_PREFIX}${String(startIndex - k).padStart(4, "0")}`,
      name: demo.name,
      category: demo.category,
      market: demo.market,
      phases,
      ...currentPhase(phases),
      status: demo.status as ProjectStatusLabel,
      health: demo.health,
      progress: progressOf(phases),
      projectedProfit: demo.profit,
      realProfit: demo.status === "Cerrado" ? demo.profit : null,
      capitalExposed: Math.round(demoRandom(demo.name, "capital") * 400),
      startedAt: today - demo.daysAgo * DAY_MS,
      isDemo: true,
    } satisfies ProjectCard;
  });

  const closed: ProjectCard[] = DEMO_CLOSED_PROJECTS.map((demo, k) => {
    const phases = PHASES.map((meta) => phase(meta.key, "done", "Cerrado"));
    return {
      id: `demo-${demo.name.toLowerCase()}`,
      code: `${PROJECT_CODE_PREFIX}${String(startIndex - DEMO_PROJECTS.length - k).padStart(4, "0")}`,
      name: demo.name,
      category: demo.category,
      market: demo.market,
      phases,
      phase: "scale" as PhaseKey,
      phaseLabel: "Cerrado",
      status: "Cerrado" as ProjectStatusLabel,
      health: demo.health,
      progress: 1,
      projectedProfit: demo.profit,
      realProfit: demo.profit,
      capitalExposed: 0,
      startedAt: today - demo.daysAgo * DAY_MS,
      isDemo: true,
    } satisfies ProjectCard;
  });

  return [...rows, ...closed];
}

// --- Cartera ---------------------------------------------------------------------

export interface PortfolioCounts {
  active: number;
  validation: number;
  launch: number;
  operating: number;
  atRisk: number;
  blocked: number;
  closed: number;
  projectedProfit: number;
  realProfit: number;
}

const VALIDATION_PHASES: PhaseKey[] = ["research", "suppliers", "economics", "legal"];
const LAUNCH_PHASES: PhaseKey[] = ["store", "marketing"];

export function portfolioCounts(projects: ProjectCard[]): PortfolioCounts {
  const open = projects.filter((p) => p.status !== "Cerrado");
  return {
    active: open.length,
    validation: open.filter((p) => VALIDATION_PHASES.includes(p.phase)).length,
    launch: open.filter((p) => LAUNCH_PHASES.includes(p.phase)).length,
    operating: open.filter((p) => p.phase === "operations" || p.phase === "scale").length,
    atRisk: open.filter((p) => p.status === "En riesgo").length,
    blocked: open.filter((p) => p.status === "Bloqueado").length,
    closed: projects.filter((p) => p.status === "Cerrado").length,
    projectedProfit: round2(open.reduce((sum, p) => sum + (p.projectedProfit ?? 0), 0)),
    realProfit: round2(projects.reduce((sum, p) => sum + (p.realProfit ?? 0), 0)),
  };
}

export type PortfolioTab = "all" | "validation" | "launch" | "operating" | "closed";

export const PORTFOLIO_TABS: { key: PortfolioTab; label: string }[] = [
  { key: "all", label: "Todos" },
  { key: "validation", label: "Validación" },
  { key: "launch", label: "Lanzamiento" },
  { key: "operating", label: "Operativos" },
  { key: "closed", label: "Cerrados" },
];

export function filterProjects(
  projects: ProjectCard[],
  filters: { tab: PortfolioTab; query?: string; market?: string; category?: string; status?: string },
): ProjectCard[] {
  const query = (filters.query ?? "").trim().toLowerCase();
  return projects.filter((project) => {
    if (filters.tab === "validation" && !(project.status !== "Cerrado" && VALIDATION_PHASES.includes(project.phase))) return false;
    if (filters.tab === "launch" && !(project.status !== "Cerrado" && LAUNCH_PHASES.includes(project.phase))) return false;
    if (filters.tab === "operating" && !(project.status !== "Cerrado" && (project.phase === "operations" || project.phase === "scale"))) return false;
    if (filters.tab === "closed" && project.status !== "Cerrado") return false;
    if (query && !`${project.code} ${project.name}`.toLowerCase().includes(query)) return false;
    if (filters.market && filters.market !== "all" && project.market !== filters.market) return false;
    if (filters.category && filters.category !== "all" && project.category !== filters.category) return false;
    if (filters.status && filters.status !== "all" && project.status !== filters.status) return false;
    return true;
  });
}

/** Reparto de los proyectos abiertos por bloque de fases, para el donut. */
export function phaseDistribution(projects: ProjectCard[]): { key: string; label: string; value: number; color: string }[] {
  const counts = portfolioCounts(projects);
  return [
    { key: "validation", label: "Validación", value: counts.validation, color: "#e056c8" },
    { key: "launch", label: "Lanzamiento", value: counts.launch, color: "#4f8df7" },
    { key: "operating", label: "Operativos", value: counts.operating, color: "#00d69a" },
    { key: "closed", label: "Cerrados", value: counts.closed, color: "#7a8b99" },
  ];
}

/** Beneficio previsto por mercado de los proyectos abiertos. */
export function profitByMarket(projects: ProjectCard[]): { key: string; value: number }[] {
  const totals = new Map<string, number>();
  for (const project of projects) {
    if (project.status === "Cerrado") continue;
    totals.set(project.market, (totals.get(project.market) ?? 0) + (project.projectedProfit ?? 0));
  }
  return [...totals.entries()].map(([key, value]) => ({ key, value: round2(value) })).sort((a, b) => b.value - a.value);
}

// --- Detalle ----------------------------------------------------------------------

export interface DecisionGate {
  label: string;
  state: "ok" | "warn" | "bad";
  detail: string;
}

export interface NextDecision {
  title: string;
  phaseLabel: string;
  amount: number | null;
  maxCac: number | null;
  gates: DecisionGate[];
  href: string;
}

/** La decisión que el proyecto tiene delante, según su fase actual. */
export function nextDecision(project: ProjectCard, input: { maxCac: number | null; amount: number | null }): NextDecision {
  const titles: Record<PhaseKey, string> = {
    research: "Validar la oportunidad",
    suppliers: "Elegir proveedor",
    economics: "Aprobar precio y márgenes",
    legal: "Cerrar el Legal Gate",
    store: "Publicar el escaparate",
    marketing: "Campaña de lanzamiento",
    operations: "Simular operaciones",
    scale: "Escalar el producto",
  };
  const gateOf = (key: PhaseKey): DecisionGate => {
    const item = project.phases.find((p) => p.key === key)!;
    return {
      label: item.label,
      state: item.state === "done" ? "ok" : item.state === "blocked" ? "bad" : "warn",
      detail: item.detail,
    };
  };
  return {
    title: titles[project.phase],
    phaseLabel: project.phaseLabel,
    amount: input.amount,
    maxCac: input.maxCac,
    gates: [gateOf("legal"), gateOf("economics"), gateOf("store")],
    href: PHASES.find((p) => p.key === project.phase)!.href,
  };
}

export interface ProjectMilestone {
  label: string;
  done: boolean;
  at: number | null;
}

/** Hitos del proyecto con la fecha en que la auditoría los registró. */
export function projectMilestones(project: ProjectCard, audit: AuditEntry[]): ProjectMilestone[] {
  const dateOf = (action: string) => {
    const entry = audit.filter((e) => e.action.startsWith(action)).sort((a, b) => Date.parse(a.created_at) - Date.parse(b.created_at))[0];
    return entry ? Date.parse(entry.created_at) : null;
  };
  const phaseDone = (key: PhaseKey) => project.phases.find((p) => p.key === key)!.state === "done";
  return [
    { label: "Producto validado", done: phaseDone("research"), at: dateOf("research") },
    { label: "Proveedor seleccionado", done: phaseDone("suppliers"), at: dateOf("sourcing") },
    { label: "Viabilidad económica", done: phaseDone("economics"), at: dateOf("economics") },
    { label: "Legal Gate", done: phaseDone("legal"), at: dateOf("legal") },
    { label: "Escaparate preparado", done: phaseDone("store"), at: dateOf("storefront") },
    { label: "Campaña aprobada", done: project.phases.find((p) => p.key === "marketing")!.state !== "todo", at: dateOf("marketing") },
    { label: "Primera venta", done: false, at: null },
    { label: "Break-even real", done: false, at: null },
  ];
}

export interface ComparisonRow {
  key: string;
  label: string;
  planned: number;
  actual: number;
  /** El valor menor es el mejor (CAC, devoluciones, entrega). */
  lowerIsBetter: boolean;
  format: "integer" | "euro" | "percent" | "days";
}

/** Previsto (supuestos de Economía) frente a real (pedidos de Operaciones). */
export function plannedVsActual(input: {
  projectId: string;
  plannedOrders: number;
  plannedRevenue: number;
  plannedCac: number;
  plannedMargin: number;
  plannedReturnRate: number;
  plannedDeliveryDays: number;
  orders: Order[];
  today: number;
}): ComparisonRow[] {
  const { projectId, orders, today } = input;
  const delivered = orders.filter((o) => o.status === "delivered" || o.status === "returned");
  const units = delivered.reduce((sum, o) => sum + o.units, 0);
  const revenue = delivered.reduce((sum, o) => sum + o.amount, 0);
  const returned = delivered.filter((o) => o.status === "returned").length;
  const deliveryDays = delivered.length ? delivered.reduce((sum, o) => sum + daysBetween(o.createdAt, o.estimatedAt), 0) / delivered.length : input.plannedDeliveryDays;
  const spread = (salt: string) => 1 + (demoRandom(projectId, salt) * 2 - 1) * DEMO_ACTUAL_SPREAD;
  void today;
  return [
    { key: "orders", label: "Ventas/mes", planned: input.plannedOrders, actual: units || Math.round(input.plannedOrders * spread("orders")), lowerIsBetter: false, format: "integer" },
    { key: "revenue", label: "Ingresos", planned: round2(input.plannedRevenue), actual: round2(revenue || input.plannedRevenue * spread("revenue")), lowerIsBetter: false, format: "euro" },
    { key: "cac", label: "CAC", planned: round2(input.plannedCac), actual: round2(input.plannedCac * spread("cac")), lowerIsBetter: true, format: "euro" },
    { key: "margin", label: "Margen", planned: input.plannedMargin, actual: input.plannedMargin * spread("margin"), lowerIsBetter: false, format: "percent" },
    {
      key: "returns",
      label: "Devoluciones",
      planned: input.plannedReturnRate,
      actual: delivered.length ? returned / delivered.length : input.plannedReturnRate * spread("returns"),
      lowerIsBetter: true,
      format: "percent",
    },
    { key: "delivery", label: "Entrega", planned: input.plannedDeliveryDays, actual: round2(deliveryDays), lowerIsBetter: true, format: "days" },
  ];
}

export interface Learning {
  text: string;
  tone: "ok" | "warn";
}

/** Aprendizajes: cada métrica que se desvía lo bastante deja una lección. */
export function learnings(rows: ComparisonRow[]): Learning[] {
  return rows.map((row) => {
    const delta = row.planned !== 0 ? row.actual / row.planned - 1 : 0;
    const better = row.lowerIsBetter ? delta < -0.02 : delta > 0.02;
    const worse = row.lowerIsBetter ? delta > 0.02 : delta < -0.02;
    const percent = `${Math.abs(delta * 100).toLocaleString("es-ES", { maximumFractionDigits: 0 })} %`;
    if (!better && !worse) return { text: `${row.label}: previsión correcta.`, tone: "ok" as const };
    return better
      ? { text: `${row.label}: mejor de lo previsto (${percent}).`, tone: "ok" as const }
      : { text: `${row.label}: por debajo de lo previsto (${percent}).`, tone: "warn" as const };
  });
}

export interface ProjectRiskRow {
  source: string;
  text: string;
  level: "Alto" | "Medio" | "Bajo";
}

/** Riesgos del proyecto: los que dejaron los agentes en sus análisis y los que se
 * derivan del estado de las fases. */
export function projectRisks(input: {
  analyses: { source: string; risks: string[] }[];
  project: ProjectCard;
  capitalExposed: number;
  capitalLimit: number;
}): ProjectRiskRow[] {
  const rows: ProjectRiskRow[] = input.analyses.flatMap((analysis) =>
    analysis.risks.map((text) => ({ source: analysis.source, text, level: "Medio" as const })),
  );
  const legal = input.project.phases.find((p) => p.key === "legal")!;
  rows.push({
    source: "Legal",
    text: legal.state === "done" ? "Sin bloqueos" : legal.state === "blocked" ? "Legal Gate bloqueado" : "Legal Gate pendiente de revisión",
    level: legal.state === "done" ? "Bajo" : legal.state === "blocked" ? "Alto" : "Medio",
  });
  rows.push({
    source: "Capital",
    text: input.capitalExposed <= input.capitalLimit ? "Dentro de política" : "Capital expuesto sobre el límite",
    level: input.capitalExposed <= input.capitalLimit ? "Bajo" : "Alto",
  });
  return rows;
}
