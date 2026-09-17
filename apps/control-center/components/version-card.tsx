import { DataProvenanceBadge } from "@/components/data-provenance-badge";

function formatCostEntry(key: string, value: unknown): string {
  const label = key.replace(/_/g, " ");
  if (typeof value === "number") return `${label}: ${value}`;
  return `${label}: ${String(value)}`;
}

/** parte2.md §6.10 "Versionado" scoped to what the registry actually
 * tracks today — a single current version per agent, no history, no
 * evaluation score, no production/staging split, no rollback (none of
 * that is persisted anywhere yet). `version` comes straight from
 * AgentDescriptor.version (verified — it's the literal value the
 * registry assigns, not a computed estimate); `cost_profile` is a
 * declared nominal figure (e.g. simulated_cost_per_task), so it's
 * marked as an estimate rather than a measurement. */
export function VersionCard({ version, costProfile }: { version: string; costProfile: Record<string, unknown> }) {
  const costEntries = Object.entries(costProfile);

  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
      <div className="flex items-center gap-1.5">
        <span className="text-muted-foreground">Versión</span>
        <span className="font-mono">{version}</span>
        <DataProvenanceBadge status="verified" tooltip="Versión asignada por el registro de agentes." />
      </div>
      {costEntries.length > 0 ? (
        <div className="flex items-center gap-1.5">
          <span className="text-muted-foreground">{costEntries.map(([k, v]) => formatCostEntry(k, v)).join(", ")}</span>
          <DataProvenanceBadge status="estimated" tooltip="Coste nominal declarado, no medido por ejecución." />
        </div>
      ) : null}
    </div>
  );
}
