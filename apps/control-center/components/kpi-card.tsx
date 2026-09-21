import type { ComponentType } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { DataProvenanceBadge, type DataProvenance } from "@/components/data-provenance-badge";

export function KpiCard({
  label,
  value,
  icon: Icon,
  caption,
  provenance,
  provenanceTooltip,
}: {
  label: string;
  value: string | number;
  icon: ComponentType<{ className?: string }>;
  /** Small secondary line under the value — context, not a fabricated trend. */
  caption?: string;
  provenance?: DataProvenance;
  /** Overrides the badge's default tooltip (e.g. to say what exactly is pending). */
  provenanceTooltip?: string;
}) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-2 pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">{label}</CardTitle>
        <Icon className="size-4 shrink-0 text-primary" />
      </CardHeader>
      <CardContent className="space-y-1.5">
        <p className="text-2xl font-semibold">{value}</p>
        {caption ? <p className="text-xs text-muted-foreground">{caption}</p> : null}
        {provenance ? <DataProvenanceBadge status={provenance} tooltip={provenanceTooltip} /> : null}
      </CardContent>
    </Card>
  );
}
