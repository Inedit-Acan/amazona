import type { Agent, Approval, EconomicAnalysis, LegalAnalysis, MarketingCampaign, PipelineReview, Product, Storefront, SupplierQuote } from "./api.ts";
import { actionLabel, isExpired } from "./approvals.ts";
import {
  CAMPAIGN_DETAIL,
  DEMO_AGENT_DEPLOY_COST,
  DEMO_UNITS,
  KIND_LABELS,
  REQUEST_TEMPLATES,
  RESOLVED_STATS,
  SEVERITY_ORDER,
  SLA_HOURS,
  type RequestKind,
  type Severity,
} from "./demo/approvals.ts";
import { formatEuro } from "./format.ts";
import { launchReadiness } from "./ecommerce.ts";
import { dedupeQuotesBySupplier } from "./economics.ts";
import { buildBaseline } from "./economics-baseline.ts";
import { evaluate } from "./economics-model.ts";
import { buildLegalView } from "./legal-view.ts";
import { acquisitionPlan, planTotal } from "./marketing-view.ts";
import { rankSuppliers } from "./sourcing-view.ts";

// Vista de la pantalla de Aprobaciones y decisiones (mockup docs/design/
// aprobaciones y decisiones.png). Una aprobación real del backend solo tiene
// acción, importe, vencimiento y estado; no hay tipo, severidad, proyecto,
// agente solicitante, análisis ni impacto, y hoy la bandeja está vacía. Aquí las
// aprobaciones reales se presentan tal cual y la bandeja se completa con
// solicitudes de demostración construidas sobre datos reales: productos,
// análisis económico y legal, tienda, campaña, proveedor y agentes registrados.

const HOUR_MS = 3_600_000;
const round2 = (value: number) => Math.round(value * 100) / 100;

export interface ValidationRow {
  label: string;
  state: "ok" | "warn" | "bad";
  detail: string;
}

export interface AgentOpinion {
  agent: string;
  verdict: string;
  ok: boolean;
}

export interface RequestDetailField {
  label: string;
  value: string;
}

export interface ApprovalRequest {
  id: string;
  code: string;
  kind: RequestKind;
  kindLabel: string;
  title: string;
  severity: Severity;
  /** Proyecto y producto sobre los que se pide la decisión. */
  projectCode: string | null;
  productName: string | null;
  /** Agente que la solicita (del registro real cuando existe). */
  requestedBy: string;
  amount: number | null;
  amountLabel: string;
  requestedAt: number;
  /** Vencimiento según el SLA de su severidad. */
  expiresAt: number;
  status: "PENDING" | "APPROVED" | "REJECTED" | "EXPIRED";
  fields: RequestDetailField[];
  validations: ValidationRow[];
  opinions: AgentOpinion[];
  findings: string[];
  risks: string[];
  approveImpact: string[];
  rejectImpact: string[];
  budget: { assigned: number; spent: number; committed: number; available: number; request: number } | null;
  /** De dónde sale: aprobación del backend, revisión de pipeline o demostración. */
  source: "approval" | "review" | "demo";
  /** La solicitud es de demostración: no se puede aprobar ni rechazar. */
  isDemo: boolean;
}

export interface ProductContext {
  product: Product;
  quotes: SupplierQuote[];
  economics: EconomicAnalysis[];
  legal: LegalAnalysis[];
  storefronts: Storefront[];
  campaigns: MarketingCampaign[];
  /** Código del proyecto de ese producto (pantalla de Proyectos). */
  projectCode: string;
  market: string;
}

function severityOf(template: (typeof REQUEST_TEMPLATES)[number], blocked: boolean): Severity {
  return blocked && template.severity !== "Crítica" ? "Alta" : template.severity;
}

function agentNamed(agents: Agent[], role: string, fallback: string): string {
  return agents.find((agent) => agent.role === role)?.name ?? fallback;
}

/** Solicitudes de demostración construidas sobre el producto real más avanzado:
 * importes, validaciones y hallazgos salen de sus análisis. */
export function demoRequests(context: ProductContext | undefined, agents: Agent[], now: number): ApprovalRequest[] {
  if (!context) return [];
  const { product, quotes, economics, legal, storefronts, campaigns, market, projectCode } = context;
  const analysis = economics[0];
  const options = dedupeQuotesBySupplier(quotes, analysis?.supplier_quote_id);
  const quote = options.find((q) => q.id === analysis?.supplier_quote_id) ?? options[0];
  const baseline = buildBaseline(quote, analysis);
  const result = evaluate(baseline.inputs);
  const legalAnalysis = legal.find((l) => l.market === market) ?? legal[0];
  const legalView = buildLegalView(market, legalAnalysis);
  const storefront = storefronts.find((s) => s.market === market) ?? storefronts[0];
  const readiness = launchReadiness({ economic: analysis, storefront, legal: legalAnalysis });
  const readyRatio = readiness.length ? readiness.filter((r) => r.state === "done").length / readiness.length : 0;
  const campaign = campaigns.find((c) => c.market === market) ?? campaigns[0];
  const plan = acquisitionPlan(campaign ? [campaign] : [], Math.round(baseline.inputs.monthlyOrders * baseline.inputs.cac));
  const monthlyBudget = planTotal(plan);
  const campaignBudget = round2(monthlyBudget / 2);
  const supplier = rankSuppliers(quotes.length ? dedupeQuotesBySupplier(quotes) : [])[0];

  const legalOk = legalView.gate.state === "ready";
  const legalRow: ValidationRow = {
    label: "Legal",
    state: legalOk ? "ok" : legalView.gate.state === "blocked" ? "bad" : "warn",
    detail: legalOk ? "Aprobado" : legalView.gate.state === "blocked" ? "Bloqueado" : "Revisión",
  };
  const economicsRow: ValidationRow = {
    label: "Economía",
    state: analysis ? (analysis.recommendation === "GO" ? "ok" : analysis.recommendation === "NO_GO" ? "bad" : "warn") : "warn",
    detail: analysis ? (analysis.recommendation === "GO" ? "Aprobado" : analysis.recommendation === "NO_GO" ? "No viable" : "Revisión") : "Sin análisis",
  };
  const storeRow: ValidationRow = {
    label: "Tienda",
    state: readyRatio >= 0.9 ? "ok" : readyRatio > 0 ? "warn" : "bad",
    detail: storefront ? `Readiness ${Math.round(readyRatio * 100)} %` : "Sin escaparate",
  };
  const financeRow: ValidationRow = {
    label: "Finanzas",
    state: campaignBudget <= monthlyBudget ? "ok" : "warn",
    detail: campaignBudget <= monthlyBudget ? "Presupuesto disponible" : "Sobre presupuesto",
  };
  const riskRow: ValidationRow = {
    label: "Riesgo",
    state: legalOk && analysis?.recommendation === "GO" ? "ok" : "warn",
    detail: legalOk && analysis?.recommendation === "GO" ? "Bajo" : "Medio-bajo",
  };
  const validations = [economicsRow, legalRow, storeRow, financeRow, riskRow];

  const projectedCac = round2(baseline.inputs.cac);
  const roas = round2(baseline.inputs.salePrice / baseline.inputs.cac);
  const opinions: AgentOpinion[] = [
    { agent: agentNamed(agents, "research", "Market Analyst"), verdict: "Oportunidad validada", ok: true },
    { agent: agentNamed(agents, "finance", "Unit Economics"), verdict: "CAC y margen dentro de objetivos", ok: analysis?.recommendation !== "NO_GO" },
    { agent: agentNamed(agents, "legal", "Product Compliance"), verdict: legalRow.detail, ok: legalOk },
    { agent: agentNamed(agents, "ecommerce", "Storefront Builder"), verdict: storeRow.detail, ok: readyRatio >= 0.9 },
    { agent: agentNamed(agents, "marketing", "Acquisition Agent"), verdict: campaign ? "Creatividades listas" : "Sin propuesta de campaña", ok: Boolean(campaign) },
    { agent: agentNamed(agents, "operations", "Operations & CS"), verdict: "Capacidad operativa confirmada", ok: true },
    { agent: agentNamed(agents, "cfo", "CFO Controller"), verdict: financeRow.detail, ok: financeRow.state === "ok" },
  ];

  const findings = [
    `CAC previsto ${formatEuro(projectedCac)} (máximo ${formatEuro(result.maxCac)}).`,
    `ROAS estimado ${roas.toLocaleString("es-ES", { maximumFractionDigits: 2 })} x.`,
    legalOk ? "Legal Gate superado." : "Legal Gate pendiente de cerrar.",
    `Margen de contribución ${(result.contributionMargin * 100).toLocaleString("es-ES", { maximumFractionDigits: 1 })} %.`,
  ];
  const risks = [
    ...(analysis?.data?.risks ?? []),
    ...(legalAnalysis?.data?.known_risks ?? []),
    ...(campaign?.data?.risks ?? []),
  ].slice(0, 3);
  if (risks.length === 0) risks.push("Previsión basada en una muestra limitada.");

  const amounts: Record<string, number | null> = {
    campaign: campaignBudget,
    supplier: supplier ? round2(supplier.quote.total_landed_cost_per_unit * DEMO_UNITS.supplierFirstOrder) : null,
    stock: round2(result.unitCost * DEMO_UNITS.anticipatedStock),
    amazon: 0,
    agent: DEMO_AGENT_DEPLOY_COST,
    legal: null,
    refund: DEMO_UNITS.refundAmount,
  };

  return REQUEST_TEMPLATES.map((template, index) => {
    const requestedAt = now - template.agedHours * HOUR_MS;
    const severity = severityOf(template, !legalOk);
    const amount = amounts[template.key] ?? null;
    const fields: RequestDetailField[] =
      template.key === "campaign"
        ? [
            { label: "Importe solicitado", value: formatEuro(campaignBudget, 0) },
            { label: "Periodo", value: `${CAMPAIGN_DETAIL.periodDays} días` },
            { label: "Canales", value: plan.slice(0, 2).map((row) => row.label).join(" + ") },
            { label: "Mercado", value: market.toUpperCase() },
            { label: "Objetivo", value: CAMPAIGN_DETAIL.objective },
            { label: "CAC máximo", value: formatEuro(result.maxCac) },
            { label: "ROAS mínimo", value: `${CAMPAIGN_DETAIL.minRoas.toLocaleString("es-ES", { maximumFractionDigits: 1 })} x` },
          ]
        : [
            { label: "Importe solicitado", value: amount === null ? "Sin coste" : formatEuro(amount, 0) },
            { label: "Producto", value: product.name },
            { label: "Mercado", value: market.toUpperCase() },
            { label: "Solicitada por", value: KIND_LABELS[template.kind] },
          ];

    return {
      id: `demo-${template.key}`,
      code: `APR-${String(852 - index).padStart(5, "0")}`,
      kind: template.kind,
      kindLabel: KIND_LABELS[template.kind],
      title: template.title,
      severity,
      projectCode,
      productName: product.name,
      requestedBy:
        template.kind === "marketing"
          ? agentNamed(agents, "marketing", "Acquisition Agent")
          : template.kind === "suppliers"
            ? agentNamed(agents, "supplier", "Supplier Finder")
            : template.kind === "operations"
              ? agentNamed(agents, "operations", "Operations Agent")
              : template.kind === "commerce"
                ? agentNamed(agents, "marketplace", "Marketplace Channel Agent")
                : template.kind === "legal"
                  ? agentNamed(agents, "legal", "Legal Agent")
                  : "System",
      amount,
      amountLabel: template.amountLabel,
      requestedAt,
      expiresAt: requestedAt + SLA_HOURS[severity] * HOUR_MS,
      status: "PENDING",
      fields,
      validations,
      opinions,
      findings,
      risks,
      approveImpact: [
        `Se autoriza ${template.approves}${amount ? ` por ${formatEuro(amount, 0)}` : ""}.`,
        `Mercado: ${market.toUpperCase()} · producto ${product.name}.`,
        "Cualquier cambio posterior requiere una nueva aprobación.",
      ],
      rejectImpact: [
        `No se ejecuta ${template.approves}.`,
        "Se mantiene el presupuesto actual y el proyecto se retrasa.",
        "La solicitud queda registrada en la auditoría.",
      ],
      budget:
        template.kind === "marketing"
          ? {
              assigned: monthlyBudget,
              spent: round2(monthlyBudget * 0.57),
              committed: round2(monthlyBudget * 0.18),
              available: round2(monthlyBudget * 0.25),
              request: campaignBudget,
            }
          : null,
      source: "demo",
      isDemo: true,
    } satisfies ApprovalRequest;
  });
}

/** Aprobación real del backend presentada como solicitud de la bandeja. */
export function requestFromApproval(approval: Approval, now: number): ApprovalRequest {
  const requestedAt = approval.expires_at ? new Date(approval.expires_at).getTime() - 24 * HOUR_MS : now;
  const expired = isExpired(approval, new Date(now));
  return {
    id: approval.id,
    code: `APR-${approval.id.slice(0, 5).toUpperCase()}`,
    kind: "finance",
    kindLabel: KIND_LABELS.finance,
    title: actionLabel(approval.action),
    severity: approval.amount !== null && approval.amount > 1000 ? "Crítica" : "Alta",
    projectCode: null,
    productName: null,
    requestedBy: "Director ejecutivo",
    amount: approval.amount,
    amountLabel: "Importe",
    requestedAt,
    expiresAt: approval.expires_at ? new Date(approval.expires_at).getTime() : requestedAt + 24 * HOUR_MS,
    status: expired ? "EXPIRED" : (approval.status as ApprovalRequest["status"]),
    fields: [
      { label: "Acción", value: actionLabel(approval.action) },
      { label: "Importe solicitado", value: approval.amount === null ? "Sin coste" : formatEuro(approval.amount) },
      { label: "Estado", value: approval.status },
    ],
    validations: [],
    opinions: [],
    findings: [],
    risks: [],
    approveImpact: [
      `Se autoriza «${actionLabel(approval.action)}».`,
      "El importe pasa de reservado a comprometido en el presupuesto.",
      "Autoriza solo esta acción y queda registrado en la auditoría.",
    ],
    rejectImpact: [`No se ejecuta «${actionLabel(approval.action)}».`, "Se libera la reserva del presupuesto.", "La solicitud queda registrada en la auditoría."],
    budget: null,
    source: "approval",
    isDemo: false,
  };
}

/** Revisión de pipeline del backend (ADR 0006) en la misma bandeja. */
export function requestFromReview(review: PipelineReview, now: number): ApprovalRequest {
  return {
    id: review.id,
    code: `REV-${review.id.slice(0, 5).toUpperCase()}`,
    kind: "operations",
    kindLabel: KIND_LABELS.operations,
    title: "Revisión de ejecución del pipeline",
    severity: "Alta",
    projectCode: null,
    productName: null,
    requestedBy: "Pipeline",
    amount: null,
    amountLabel: "Sin coste",
    requestedAt: now,
    expiresAt: now + SLA_HOURS.Alta * HOUR_MS,
    status: review.status === "PENDING" ? "PENDING" : (review.status as ApprovalRequest["status"]),
    fields: [
      { label: "Ejecución", value: review.pipeline_run_id },
      { label: "Estado", value: review.status },
      { label: "Motivos", value: String(review.reasons.length) },
    ],
    validations: [],
    opinions: [],
    findings: [],
    risks: review.reasons,
    approveImpact: ["La ejecución del pipeline continúa.", "Queda registrada en la auditoría."],
    rejectImpact: ["La ejecución del pipeline no continúa.", "Queda registrada en la auditoría."],
    budget: null,
    source: "review",
    isDemo: false,
  };
}

// --- Bandeja ---------------------------------------------------------------------

export interface InboxKpis {
  pending: number;
  critical: number;
  expiringSoon: number;
  approvedToday: number;
  averageMinutes: number;
}

export function inboxKpis(requests: ApprovalRequest[], now: number): InboxKpis {
  const pending = requests.filter((request) => request.status === "PENDING");
  return {
    pending: pending.length,
    critical: pending.filter((request) => request.severity === "Crítica").length,
    expiringSoon: pending.filter((request) => request.expiresAt - now <= 4 * HOUR_MS).length,
    approvedToday: RESOLVED_STATS.approved,
    averageMinutes: RESOLVED_STATS.averageMinutes,
  };
}

export type InboxFilter = "pending" | "all" | "critical" | RequestKind;

export const INBOX_FILTERS: { key: InboxFilter; label: string }[] = [
  { key: "pending", label: "Pendientes" },
  { key: "all", label: "Todas" },
  { key: "critical", label: "Críticas" },
  { key: "finance", label: "Finanzas" },
  { key: "commerce", label: "Lanzamientos" },
  { key: "suppliers", label: "Proveedores" },
  { key: "marketing", label: "Marketing" },
  { key: "legal", label: "Legal" },
  { key: "operations", label: "Operaciones" },
  { key: "agents", label: "Agentes" },
];

export function countFor(requests: ApprovalRequest[], filter: InboxFilter): number {
  return filterRequests(requests, { filter }).length;
}

export type InboxSort = "recent" | "oldest" | "severity" | "amount";

export const SORT_LABELS: Record<InboxSort, string> = {
  recent: "Más recientes",
  oldest: "Más antiguas",
  severity: "Por severidad",
  amount: "Por importe",
};

export function filterRequests(requests: ApprovalRequest[], input: { filter: InboxFilter; query?: string }): ApprovalRequest[] {
  const query = (input.query ?? "").trim().toLowerCase();
  return requests.filter((request) => {
    if (input.filter === "pending" && request.status !== "PENDING") return false;
    if (input.filter === "critical" && request.severity !== "Crítica") return false;
    if (input.filter !== "pending" && input.filter !== "all" && input.filter !== "critical" && request.kind !== input.filter) return false;
    if (!query) return true;
    return `${request.code} ${request.title} ${request.productName ?? ""} ${request.requestedBy}`.toLowerCase().includes(query);
  });
}

export function sortRequests(requests: ApprovalRequest[], sort: InboxSort): ApprovalRequest[] {
  const copy = [...requests];
  if (sort === "recent") return copy.sort((a, b) => b.requestedAt - a.requestedAt);
  if (sort === "oldest") return copy.sort((a, b) => a.requestedAt - b.requestedAt);
  if (sort === "amount") return copy.sort((a, b) => (b.amount ?? 0) - (a.amount ?? 0));
  return copy.sort((a, b) => SEVERITY_ORDER.indexOf(a.severity) - SEVERITY_ORDER.indexOf(b.severity) || b.requestedAt - a.requestedAt);
}

/** Reparto por tipo de las solicitudes de la bandeja más las ya resueltas. */
export function requestsByKind(requests: ApprovalRequest[]): { key: RequestKind; label: string; value: number }[] {
  const totals = new Map<RequestKind, number>();
  for (const request of requests) totals.set(request.kind, (totals.get(request.kind) ?? 0) + 1);
  return [...totals.entries()]
    .map(([key, value]) => ({ key, label: KIND_LABELS[key], value }))
    .sort((a, b) => b.value - a.value);
}

export interface StatusShare {
  label: string;
  value: number;
  share: number;
  tone: "ok" | "warn" | "bad" | "neutral";
}

/** Estado de las solicitudes de los últimos 30 días (las resueltas son de demostración). */
export function statusShares(requests: ApprovalRequest[]): StatusShare[] {
  const pending = requests.filter((request) => request.status === "PENDING").length;
  const rows: { label: string; value: number; tone: StatusShare["tone"] }[] = [
    { label: "Aprobadas", value: RESOLVED_STATS.approved, tone: "ok" },
    { label: "Rechazadas", value: RESOLVED_STATS.rejected, tone: "bad" },
    { label: "En revisión", value: RESOLVED_STATS.inReview, tone: "warn" },
    { label: "Pendientes", value: pending, tone: "warn" },
    { label: "Retiradas", value: RESOLVED_STATS.withdrawn, tone: "neutral" },
    { label: "Vencidas", value: RESOLVED_STATS.expired, tone: "bad" },
  ];
  const total = rows.reduce((sum, row) => sum + row.value, 0) || 1;
  return rows.map((row) => ({ ...row, share: row.value / total }));
}

/** Tiempo restante hasta el vencimiento, en horas (negativo si ya venció). */
export function hoursLeft(request: ApprovalRequest, now: number): number {
  return (request.expiresAt - now) / HOUR_MS;
}
