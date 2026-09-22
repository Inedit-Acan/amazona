const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }

  /** Mensaje legible del backend: FastAPI responde `{"detail": "..."}`; si el
   * cuerpo no es ese JSON se devuelve tal cual. */
  get detail(): string {
    try {
      const body: unknown = JSON.parse(this.message);
      if (body && typeof body === "object" && "detail" in body && typeof body.detail === "string") {
        return body.detail;
      }
    } catch {
      // cuerpo no JSON: se usa el texto original
    }
    return this.message;
  }
}

async function authHeader(): Promise<Record<string, string>> {
  // Only relevant in the browser (client components) — server components
  // only ever issue GETs, which the backend never gates on auth.
  if (typeof window === "undefined") return {};
  const { getAccessToken } = await import("@/lib/auth");
  const token = await getAccessToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(await authHeader()), ...(init?.headers ?? {}) },
    cache: "no-store",
  });

  if (!response.ok) {
    const body = await response.text();
    throw new ApiError(body || response.statusText, response.status);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export type ProjectStatus =
  | "DRAFT"
  | "VALIDATING"
  | "APPROVED"
  | "EXECUTING"
  | "MONITORING"
  | "PAUSED"
  | "COMPLETED"
  | "REJECTED"
  | "FAILED";

export type TaskStatus =
  | "PENDING"
  | "QUEUED"
  | "RUNNING"
  | "WAITING"
  | "WAITING_APPROVAL"
  | "COMPLETED"
  | "FAILED"
  | "CANCELLED"
  | "BLOCKED";

export type DecisionStatus = "GO" | "REVIEW" | "NO_GO" | "HUMAN_APPROVAL";
export type ApprovalStatus = "PENDING" | "APPROVED" | "REJECTED" | "EXPIRED" | "CANCELLED";

export interface Objective {
  id: string;
  title: string;
  description: string | null;
  created_by: string;
  status: string;
  context: Record<string, unknown> | null;
}

export interface Product {
  id: string;
  name: string;
  category: string;
  status: string;
  created_by: string;
  source: string;
}

export interface Project {
  id: string;
  objective_id: string;
  name: string;
  status: ProjectStatus;
}

export interface Task {
  id: string;
  project_id: string;
  name: string;
  capability: string;
  status: TaskStatus;
  input: Record<string, unknown> | null;
  output: Record<string, unknown> | null;
  error: string | null;
}

export interface Agent {
  id: string;
  name: string;
  role: string;
  capabilities: string[];
  status: string;
  reliability_score: number;
  version: string;
  cost_profile: Record<string, unknown>;
}

export interface DecisionEvidence {
  source: string;
  summary: string;
  data: Record<string, unknown> | null;
}

export interface Decision {
  id: string;
  project_id: string;
  status: DecisionStatus;
  opportunity_score: number | null;
  confidence: number | null;
  rationale: string | null;
  correlation_id: string;
  evidence: DecisionEvidence[];
}

export interface RunResult {
  id: string;
  project_id: string;
  status: DecisionStatus;
  opportunity_score: number | null;
  confidence: number | null;
  rationale: string | null;
  correlation_id: string;
}

export interface Approval {
  id: string;
  decision_id: string;
  action: string;
  amount: number | null;
  status: ApprovalStatus;
  expires_at: string | null;
  resolved_at: string | null;
  resolved_by: string | null;
}

export interface AuditEntry {
  id: string;
  actor: string;
  action: string;
  resource: string;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  correlation_id: string;
  created_at: string;
}

export interface AgentExecution {
  id: string;
  agent_id: string;
  capability: string;
  duration_ms: number;
  success: boolean;
  correlation_id: string;
  created_at: string;
}

export interface DetailedHealth {
  database: "ok" | "error";
  migration: string | null;
  supabase_configured: boolean;
}

export type IncidentSeverity = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
export type IncidentStatus = "OPEN" | "RESOLVED";

export interface Incident {
  id: string;
  title: string;
  description: string | null;
  severity: IncidentSeverity;
  status: IncidentStatus;
  resolved_at: string | null;
  created_at: string;
}

export interface ResearchCandidate {
  product_id: string;
  name: string;
  category: string;
  opportunity_score: number | null;
  confidence: number | null;
  data: {
    demand_signal?: number;
    competition_level?: string;
    /** Radar axes added Milestone 26 — absent on analyses persisted before it. */
    future_outlook_signal?: number;
    regulatory_risk_signal?: number;
    scalability_signal?: number;
    niche_rationale?: string;
    [key: string]: unknown;
  };
}

export interface ResearchRun {
  correlation_id: string;
  candidates: ResearchCandidate[];
}

export interface SupplierQuote {
  id: string;
  product_id: string;
  supplier_id: string;
  unit_price: number;
  moq: number;
  lead_time_days: number;
  verified: boolean;
  reliability_score: number;
  logistics_cost_per_unit: number;
  total_landed_cost_per_unit: number;
  data: {
    name?: string;
    region?: string;
    notes?: string;
    [key: string]: unknown;
  } | null;
}

export interface SourcingRun {
  correlation_id: string;
  quotes: SupplierQuote[];
}

export interface EconomicScenario {
  monthly_unit_sales: number;
  margin_percent: number;
  monthly_revenue: number;
  monthly_profit: number;
}

export interface EconomicAnalysis {
  correlation_id: string;
  product_id: string;
  supplier_quote_id: string;
  sale_price: number;
  monthly_fixed_costs: number;
  margin_percent: number;
  recommendation: "GO" | "REVIEW" | "NO_GO";
  confidence: number;
  data: {
    scenarios?: Record<"conservative" | "base" | "optimistic", EconomicScenario>;
    risks?: string[];
    evidence?: string[];
    [key: string]: unknown;
  } | null;
}

export interface EconomicsTimeseriesPoint {
  day: string;
  analyses_count: number;
  avg_margin_percent: number;
  avg_sale_price: number;
}

export interface RegulatoryChange {
  date: string;
  description: string;
}

export interface LegalAnalysis {
  correlation_id: string;
  product_id: string;
  supplier_quote_id: string | null;
  market: string;
  restricted: boolean | null;
  recommendation: "GO" | "REVIEW" | "NO_GO";
  confidence: number;
  data: {
    required_certifications?: string[];
    known_risks?: string[];
    recent_changes?: RegulatoryChange[];
    terms_and_conditions?: string;
    risks?: string[];
    evidence?: string[];
    [key: string]: unknown;
  } | null;
}

export interface LandingPageCopy {
  headline: string;
  subheadline: string;
  price_display: string;
  bullets: string[];
  cta: string;
}

export interface PaymentGatewayPlan {
  gateway: string;
  mode: string;
  checklist: string[];
  requires_human_approval: boolean;
}

export interface CatalogEntry {
  sku: string;
  price: number | null;
  category: string;
  market: string;
  restricted: boolean | null;
  lead_time_days: number | null;
}

export interface Storefront {
  correlation_id: string;
  product_id: string;
  market: string;
  store_slug: string;
  launch_status: "READY" | "NEEDS_REVIEW" | "BLOCKED";
  recommendation: "GO" | "REVIEW" | "NO_GO";
  confidence: number;
  data: {
    landing_page_copy?: LandingPageCopy;
    payment_gateway_plan?: PaymentGatewayPlan;
    catalog_entry?: CatalogEntry;
    conversion_tips?: string[];
    risks?: string[];
    evidence?: string[];
    [key: string]: unknown;
  } | null;
}

export interface ListingContent {
  title: string;
  bullet_points: string[];
  backend_keywords: string[];
}

export interface CompetitionAnalysis {
  competitor_count: number;
  avg_price: number;
  avg_rating: number;
  buy_box_difficulty: string;
  data_origin: string;
}

export interface CommissionBreakdown {
  referral_fee_percent: number;
  fulfillment_fee_per_unit: number;
  net_margin_per_unit: number | null;
}

export interface InventoryPolicy {
  tracking_enabled: boolean;
  fulfillment_method: string;
}

export interface MarketplaceListing {
  correlation_id: string;
  product_id: string;
  storefront_id: string | null;
  market: string;
  platform: string;
  listing_status: "READY" | "NEEDS_REVIEW" | "BLOCKED";
  recommendation: "GO" | "REVIEW" | "NO_GO";
  confidence: number;
  data: {
    listing_content?: ListingContent;
    competition_analysis?: CompetitionAnalysis;
    commission_breakdown?: CommissionBreakdown;
    inventory_policy?: InventoryPolicy;
    risks?: string[];
    evidence?: string[];
    [key: string]: unknown;
  } | null;
}

export interface AudienceSegment {
  name: string;
  age_range: string;
  interests: string[];
  estimated_reach: number;
}

export interface AdCreative {
  headline: string;
  primary_text: string;
  cta: string;
  image_brief: string;
}

export interface PerformanceEstimate {
  avg_cpc: number;
  avg_ctr: number;
  conversion_rate: number;
  data_origin: string;
  projected_roas: number | null;
}

export interface MarketingCampaign {
  correlation_id: string;
  product_id: string;
  marketplace_listing_id: string | null;
  market: string;
  platform: string;
  daily_budget: number;
  campaign_status: "READY" | "NEEDS_REVIEW" | "BLOCKED";
  recommendation: "GO" | "REVIEW" | "NO_GO";
  confidence: number;
  data: {
    audience_segments?: AudienceSegment[];
    ad_creative?: AdCreative;
    performance_estimate?: PerformanceEstimate;
    budget_recommendation?: string;
    risks?: string[];
    evidence?: string[];
    [key: string]: unknown;
  } | null;
}

export interface TrackingStage {
  stage: string;
  day_offset: number;
}

export interface OrderTracking {
  stages: TrackingStage[];
  lead_time_days_used: number;
}

export interface SimulatedOrder {
  order_id: string;
  quantity: number;
  tracking: OrderTracking;
}

export interface SupplierCoordination {
  lead_time_days: number | null;
  supplier_verified: boolean | null;
}

export interface ReturnPolicy {
  eligibility_window_days: number;
  restocking_fee_percent: number;
  refund_estimate: number | null;
}

export interface SupportTicketExample {
  ticket_type: string;
  ai_resolvable: boolean;
  escalation_reason: string | null;
}

export interface OperationsRecord {
  correlation_id: string;
  product_id: string;
  marketing_campaign_id: string | null;
  market: string;
  operations_status: "READY" | "NEEDS_REVIEW" | "BLOCKED";
  recommendation: "GO" | "REVIEW" | "NO_GO";
  confidence: number;
  data: {
    order?: SimulatedOrder;
    supplier_coordination?: SupplierCoordination;
    return_policy?: ReturnPolicy;
    support_ticket_example?: SupportTicketExample;
    risks?: string[];
    evidence?: string[];
    [key: string]: unknown;
  } | null;
}

export interface CFOReport {
  correlation_id: string;
  financial_health_status: "HEALTHY" | "AT_RISK" | "CRITICAL" | "NEEDS_REVIEW";
  recommendation: "GO" | "REVIEW" | "NO_GO";
  confidence: number;
  data: {
    no_go_ratio: number | null;
    budget_utilization: number | null;
    total_products_analyzed: number;
    go_count: number;
    review_count: number;
    no_go_count: number;
    total_campaigns: number;
    active_campaigns: number;
    total_daily_budget: number;
    total_budget_hard_limit: number;
    total_reserved: number;
    total_committed: number;
    total_spent: number;
    risks?: string[];
    evidence?: string[];
    [key: string]: unknown;
  } | null;
}

export interface PipelineStep {
  correlation_id: string;
  entity_id?: string;
  status?: string;
  recommendation?: string;
  candidate_count?: number;
}

export interface PipelineRun {
  correlation_id: string;
  product_id: string | null;
  category: string;
  market: string;
  status: "COMPLETED" | "PARTIAL";
  failed_step: string | null;
  needs_review: boolean;
  steps: Record<string, PipelineStep>;
}

export interface PipelineReview {
  id: string;
  pipeline_run_id: string;
  reasons: string[];
  status: "PENDING" | "APPROVED" | "REJECTED";
  resolved_at: string | null;
  resolved_by: string | null;
  correlation_id: string;
}

export interface PipelineKillSwitchState {
  enabled: boolean;
  reason: string | null;
  updated_by: string | null;
}

export const api = {
  createObjective: (payload: { title: string; description?: string; created_by: string; context?: unknown }) =>
    request<Objective>("/api/objectives", { method: "POST", body: JSON.stringify(payload) }),
  runObjective: (objectiveId: string) =>
    request<RunResult>(`/api/objectives/${objectiveId}/run`, { method: "POST" }),
  listProducts: (status?: string) =>
    request<Product[]>(`/api/products${status ? `?status=${encodeURIComponent(status)}` : ""}`),
  listProjects: () => request<Project[]>("/api/projects"),
  getProject: (projectId: string) => request<Project>(`/api/projects/${projectId}`),
  listTasks: (projectId: string) => request<Task[]>(`/api/tasks?project_id=${projectId}`),
  listAgents: () => request<Agent[]>("/api/agents"),
  getDecision: (decisionId: string) => request<Decision>(`/api/decisions/${decisionId}`),
  listDecisionsForProject: (projectId: string) => request<Decision[]>(`/api/decisions?project_id=${projectId}`),
  listApprovals: () => request<Approval[]>("/api/approvals"),
  approveApproval: (approvalId: string, actor: string) =>
    request<Approval>(`/api/approvals/${approvalId}/approve`, {
      method: "POST",
      body: JSON.stringify({ actor }),
    }),
  rejectApproval: (approvalId: string, actor: string) =>
    request<Approval>(`/api/approvals/${approvalId}/reject`, {
      method: "POST",
      body: JSON.stringify({ actor }),
    }),
  listAudit: (correlationId?: string) =>
    request<AuditEntry[]>(`/api/audit${correlationId ? `?correlation_id=${correlationId}` : ""}`),
  listAgentExecutions: () => request<AgentExecution[]>("/api/agent-executions"),
  getHealth: () => request<DetailedHealth>("/health/detailed"),
  listIncidents: () => request<Incident[]>("/api/incidents"),
  createIncident: (payload: { title: string; description?: string; severity: IncidentSeverity; actor: string }) =>
    request<Incident>("/api/incidents", { method: "POST", body: JSON.stringify(payload) }),
  resolveIncident: (incidentId: string, actor: string) =>
    request<Incident>(`/api/incidents/${incidentId}/resolve`, {
      method: "POST",
      body: JSON.stringify({ actor }),
    }),
  createResearchRun: (payload: { category: string; keywords?: string[]; max_results?: number }) =>
    request<ResearchRun>("/api/research/runs", { method: "POST", body: JSON.stringify(payload) }),
  getResearchRun: (correlationId: string) => request<ResearchRun>(`/api/research/runs/${correlationId}`),
  createSourcingRun: (payload: {
    product_id: string;
    category: string;
    destination_region: string;
    max_results?: number;
  }) => request<SourcingRun>("/api/sourcing/runs", { method: "POST", body: JSON.stringify(payload) }),
  listProductSuppliers: (productId: string) =>
    request<SupplierQuote[]>(`/api/products/${productId}/suppliers`),
  createEconomicAnalysisRun: (payload: {
    product_id: string;
    supplier_quote_id: string;
    sale_price: number;
    monthly_fixed_costs?: number;
  }) => request<EconomicAnalysis>("/api/economics/runs", { method: "POST", body: JSON.stringify(payload) }),
  listProductEconomics: (productId: string) =>
    request<EconomicAnalysis[]>(`/api/products/${productId}/economics`),
  getEconomicsTimeseries: (days = 30) =>
    request<EconomicsTimeseriesPoint[]>(`/api/economics/analyses/timeseries?days=${days}`),
  createLegalAnalysisRun: (payload: {
    product_id: string;
    market: string;
    certification_available?: boolean;
  }) => request<LegalAnalysis>("/api/legal/runs", { method: "POST", body: JSON.stringify(payload) }),
  listProductLegal: (productId: string) => request<LegalAnalysis[]>(`/api/products/${productId}/legal`),
  createStorefrontRun: (payload: { product_id: string; market: string }) =>
    request<Storefront>("/api/ecommerce/runs", { method: "POST", body: JSON.stringify(payload) }),
  listProductStorefronts: (productId: string) =>
    request<Storefront[]>(`/api/products/${productId}/storefronts`),
  createMarketplaceListingRun: (payload: { product_id: string; market: string; platform?: string }) =>
    request<MarketplaceListing>("/api/marketplace/runs", { method: "POST", body: JSON.stringify(payload) }),
  listProductMarketplaceListings: (productId: string) =>
    request<MarketplaceListing[]>(`/api/products/${productId}/marketplace-listings`),
  createMarketingCampaignRun: (payload: {
    product_id: string;
    market: string;
    platform?: string;
    daily_budget?: number;
  }) => request<MarketingCampaign>("/api/marketing/runs", { method: "POST", body: JSON.stringify(payload) }),
  listProductCampaigns: (productId: string) =>
    request<MarketingCampaign[]>(`/api/products/${productId}/campaigns`),
  createOperationsRun: (payload: { product_id: string; market: string }) =>
    request<OperationsRecord>("/api/operations/runs", { method: "POST", body: JSON.stringify(payload) }),
  listProductOperations: (productId: string) =>
    request<OperationsRecord[]>(`/api/products/${productId}/operations`),
  createCFORun: () => request<CFOReport>("/api/cfo/runs", { method: "POST" }),
  getCFORun: (correlationId: string) => request<CFOReport>(`/api/cfo/runs/${correlationId}`),
  listCFORuns: () => request<CFOReport[]>("/api/cfo/runs"),
  createPipelineRun: (payload: {
    category: string;
    sale_price: number;
    destination_region: string;
    market?: string;
    marketplace_platform?: string;
    marketing_platform?: string;
    daily_budget?: number;
    monthly_fixed_costs?: number;
    certification_available?: boolean;
    max_results?: number;
  }) => request<PipelineRun>("/api/pipeline/runs", { method: "POST", body: JSON.stringify(payload) }),
  listPipelineRuns: () => request<PipelineRun[]>("/api/pipeline/runs"),
  listPipelineReviews: () => request<PipelineReview[]>("/api/pipeline/reviews"),
  approvePipelineReview: (reviewId: string, actor: string) =>
    request<PipelineReview>(`/api/pipeline/reviews/${reviewId}/approve`, {
      method: "POST",
      body: JSON.stringify({ actor }),
    }),
  rejectPipelineReview: (reviewId: string, actor: string) =>
    request<PipelineReview>(`/api/pipeline/reviews/${reviewId}/reject`, {
      method: "POST",
      body: JSON.stringify({ actor }),
    }),
  getPipelineKillSwitch: () => request<PipelineKillSwitchState>("/api/pipeline/kill-switch"),
  setPipelineKillSwitch: (payload: { enabled: boolean; reason?: string; actor: string }) =>
    request<PipelineKillSwitchState>("/api/pipeline/kill-switch", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
};
