import type { Agent, AgentExecution, AuditEntry } from "./api.ts";
import type { ActivitySource } from "./ceo-activity-reads.ts";

// Apoyo común de las pruebas de «Actividad registrada» y «Ejecuciones por área» (M47, Commit 5). No es una prueba: no acaba en
// `.test.ts`, así que `node --test` no lo ejecuta.

/** El instante de «ahora» de todas las pruebas: el 15 de octubre de 2026 a las 12:00 UTC. */
export const NOW = Date.parse("2026-10-15T12:00:00Z");
export const MINUTE = 60_000;

const iso = (ms: number) => new Date(ms).toISOString();

export const entry = (id: string, over: Partial<AuditEntry> = {}): AuditEntry => ({
  id,
  actor: "ceo",
  action: "project.created",
  resource: `project:${id}`,
  before: null,
  after: null,
  correlation_id: "corr-1",
  created_at: iso(NOW - 60 * MINUTE),
  ...over,
});

/** `count` entradas en el orden REAL del backend: `created_at` ascendente (la más antigua primero). El id crece con el tiempo. */
export function auditAscending(count: number, over: (index: number) => Partial<AuditEntry> = () => ({})): AuditEntry[] {
  return Array.from({ length: count }, (_unused, index) =>
    entry(`a${String(index + 1).padStart(4, "0")}`, { created_at: iso(NOW - (count - index) * MINUTE), ...over(index) }),
  );
}

/** `count` entradas en el orden que pide el frontend nuevo (`order=desc`): la más reciente primero. Es la lista ascendente al revés. */
export const auditDescending = (count: number, over?: (index: number) => Partial<AuditEntry>): AuditEntry[] => auditAscending(count, over).reverse();

/** Entradas ya en orden descendente: la primera es la más reciente (hace 1 min) y cada una es 1 min más antigua. Los ids son `a1`, `a2`… */
export function stack(...patches: Partial<AuditEntry>[]): AuditEntry[] {
  return patches.map((patch, index) => entry(`a${index + 1}`, { created_at: iso(NOW - (index + 1) * MINUTE), ...patch }));
}

export const execution = (id: string, agentId: string, over: Partial<AgentExecution> = {}): AgentExecution => ({
  id,
  agent_id: agentId,
  capability: "research",
  duration_ms: 1000,
  success: true,
  correlation_id: "corr-1",
  created_at: iso(NOW - 30 * MINUTE),
  ...over,
});

const agent = (id: string, role: string, name: string): Agent => ({
  id,
  name,
  role,
  capabilities: [`cap-${role}`],
  status: "AVAILABLE",
  reliability_score: 1,
  version: "1.0.0",
  cost_profile: { simulated_cost_per_task: 0 },
});

/** Los 13 agentes del registro por defecto del backend (`build_default_agent_manager`). */
export const REGISTRY: Agent[] = [
  agent("agent-product-1", "product", "Product Validation Agent"),
  agent("agent-supplier-1", "supplier", "Supplier Sourcing Agent"),
  agent("agent-finance-1", "finance", "Finance Validation Agent"),
  agent("agent-legal-1", "legal", "Legal Validation Agent"),
  agent("agent-product-research-1", "research", "Product Research Agent"),
  agent("agent-supplier-sourcing-1", "sourcing", "Supplier Sourcing Research Agent"),
  agent("agent-economic-analysis-1", "economics", "Economic Analysis and Risk Agent"),
  agent("agent-legal-compliance-1", "legal_compliance", "Legal Compliance Analysis Agent"),
  agent("agent-ecommerce-storefront-1", "ecommerce", "Ecommerce Storefront Generation Agent"),
  agent("agent-marketplace-listing-1", "marketplace", "Marketplace Listing Optimization Agent"),
  agent("agent-marketing-campaign-1", "marketing", "Marketing Campaign Planning Agent"),
  agent("agent-operations-1", "operations", "Operations and Customer Service Agent"),
  agent("agent-cfo-1", "cfo", "CFO Financial Health Agent"),
];

export { agent as makeAgent };

/** Una fuente completa con tres lecturas que cuentan sus llamadas. */
export function fakeSource(over: Partial<ActivitySource> = {}): ActivitySource & { calls: Record<string, number> } {
  const calls: Record<string, number> = { listAudit: 0, listAgents: 0, listAgentExecutions: 0 };
  const counted =
    <T>(name: string, value: (...args: never[]) => Promise<T>) =>
    (...args: unknown[]) => {
      calls[name] += 1;
      return (value as (...received: unknown[]) => Promise<T>)(...args);
    };
  return {
    calls,
    listAudit: counted("listAudit", over.listAudit ?? (async () => [])),
    listAgents: counted("listAgents", over.listAgents ?? (async () => REGISTRY)),
    listAgentExecutions: counted("listAgentExecutions", over.listAgentExecutions ?? (async () => [])),
  };
}
