import type { Decision } from "@/lib/api";
import { deriveHealthDimensions, overallRisk, type HealthStatus } from "@/lib/decision-health";
import { StatusChip } from "@/components/status-chip";

const RISK_LABEL: Record<ReturnType<typeof overallRisk>, string> = {
  low: "Riesgo bajo",
  medium: "Riesgo medio",
  high: "Riesgo alto",
};

const RISK_CHIP_STATUS: Record<ReturnType<typeof overallRisk>, string> = {
  low: "GO",
  medium: "REVIEW",
  high: "NO_GO",
};

const DIMENSION_CHIP_STATUS: Record<HealthStatus, string> = {
  GO: "GO",
  REVIEW: "REVIEW",
  NO_GO: "NO_GO",
  PENDING: "PENDING",
};

/** Multidimensional, explicable health score (parte2.md §5.6) — built
 * from the real per-agent recommendation on each piece of Decision
 * evidence, never a single opaque number. Only the 4 dimensions this
 * project's Decision can actually evidence (see lib/decision-health.ts
 * for why canal/marketing/operaciones aren't included).
 *
 * `compact` renders a single overall-risk chip (project list rows);
 * the full dimension breakdown is only shown on the project detail
 * page, where there's room to label each one. */
export function ProjectHealth({ decision, compact = false }: { decision: Decision | null; compact?: boolean }) {
  const dimensions = deriveHealthDimensions(decision);
  const risk = overallRisk(dimensions);

  if (compact) {
    return <StatusChip status={RISK_CHIP_STATUS[risk]} />;
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <p className="text-sm font-medium">Project Health</p>
        <StatusChip status={RISK_CHIP_STATUS[risk]} />
      </div>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {dimensions.map((dimension) => (
          <div key={dimension.key} className="rounded-md border px-2 py-1.5 text-center">
            <p className="text-xs text-muted-foreground">{dimension.label}</p>
            <StatusChip status={DIMENSION_CHIP_STATUS[dimension.status]} />
          </div>
        ))}
      </div>
      <p className="text-xs text-muted-foreground">{RISK_LABEL[risk]}</p>
    </div>
  );
}
