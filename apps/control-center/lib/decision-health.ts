import type { Decision } from "@/lib/api";

export type HealthStatus = "GO" | "REVIEW" | "NO_GO" | "PENDING";

export interface HealthDimension {
  key: string;
  label: string;
  status: HealthStatus;
}

function findEvidence(decision: Decision, source: string) {
  return decision.evidence.find((e) => e.source === source);
}

/** Every AgentResult (and therefore every DecisionEvidence.data, per
 * backend/app/ceo/orchestrator.py's `{**output.data, recommendation:
 * output.recommendation, ...}` spread) carries its own `recommendation`
 * — the real per-agent GO/REVIEW/NO_GO, not the aggregate decision
 * status. */
function dimensionStatus(decision: Decision, source: string): HealthStatus {
  const evidence = findEvidence(decision, source);
  if (!evidence) return "PENDING";
  const recommendation = evidence.data?.recommendation;
  if (recommendation === "NO_GO") return "NO_GO";
  if (recommendation === "REVIEW" || recommendation === "HUMAN_APPROVAL") return "REVIEW";
  return "GO";
}

/** The 4 dimensions this system can actually score, from the same
 * evidence sources the CEOOrchestrator produces (backend/app/ceo/
 * orchestrator.py SPECIALIST_TASK_NAMES) — mercado/proveedor/economía/
 * legal. canal/marketing/operaciones aren't linked back to a Project in
 * a way this page can resolve without extra fan-out queries, so they're
 * left out rather than shown as a fabricated "pending" placeholder for
 * dimensions the spec names but this data model doesn't track per
 * project (parte2.md §5.6). */
export function deriveHealthDimensions(decision: Decision | null): HealthDimension[] {
  if (!decision) {
    return [
      { key: "market", label: "Mercado", status: "PENDING" },
      { key: "supplier", label: "Proveedor", status: "PENDING" },
      { key: "economics", label: "Economía", status: "PENDING" },
      { key: "legal", label: "Legal", status: "PENDING" },
    ];
  }
  return [
    { key: "market", label: "Mercado", status: dimensionStatus(decision, "product_validation") },
    { key: "supplier", label: "Proveedor", status: dimensionStatus(decision, "supplier_sourcing") },
    { key: "economics", label: "Economía", status: dimensionStatus(decision, "finance_validation") },
    { key: "legal", label: "Legal", status: dimensionStatus(decision, "legal_validation") },
  ];
}

/** Overall risk, aggregated from the dimensions above — any NO_GO makes
 * the whole project high risk, any REVIEW/PENDING makes it medium,
 * everything GO makes it low. Same "worst dimension wins" logic a
 * human reading the evidence would apply by hand. */
export function overallRisk(dimensions: HealthDimension[]): "low" | "medium" | "high" {
  if (dimensions.some((d) => d.status === "NO_GO")) return "high";
  if (dimensions.some((d) => d.status === "REVIEW" || d.status === "PENDING")) return "medium";
  return "low";
}
