import type { ComponentType } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { DataProvenanceBadge, type DataProvenance } from "@/components/data-provenance-badge";

export function KpiCard({
  label,
  value,
  icon: Icon,
  caption,
  provenance,
}: {
  label: string;
  value: string | number;
  icon: ComponentType<{ className?: string }>;
  /** Small secondary line under the value — context, not a fabricated trend. */
  caption?: string;
  provenance?: DataProvenance;
}) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">{label}</CardTitle>
        <Icon className="size-4 text-primary" />
      </CardHeader>
      <CardContent>
        <div className="flex items-end justify-between gap-2">
          <p className="text-2xl font-semibold">{value}</p>
          {provenance ? <DataProvenanceBadge status={provenance} /> : null}
        </div>
        {caption ? <p className="mt-1 text-xs text-muted-foreground">{caption}</p> : null}
      </CardContent>
    </Card>
  );
}
