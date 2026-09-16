const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
    this.name = "ApiError";
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

export interface ResearchCandidate {
  product_id: string;
  name: string;
  category: string;
  opportunity_score: number | null;
  confidence: number | null;
  data: {
    demand_signal?: number;
    competition_level?: string;
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

export const api = {
  createObjective: (payload: { title: string; description?: string; created_by: string; context?: unknown }) =>
    request<Objective>("/api/objectives", { method: "POST", body: JSON.stringify(payload) }),
  runObjective: (objectiveId: string) =>
    request<RunResult>(`/api/objectives/${objectiveId}/run`, { method: "POST" }),
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
  createResearchRun: (payload: { category: string; keywords?: string[]; max_results?: number }) =>
    request<ResearchRun>("/api/research/runs", { method: "POST", body: JSON.stringify(payload) }),
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
};
