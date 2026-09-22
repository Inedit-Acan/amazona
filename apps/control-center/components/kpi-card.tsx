import type { ComponentType, ReactNode } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { DataProvenanceBadge, type DataProvenance } from "@/components/data-provenance-badge";
import { cn } from "@/lib/utils";

export type KpiTone = "default" | "success" | "warning" | "danger";

export function KpiCard({
  label,
  value,
  icon: Icon,
  caption,
  provenance,
  provenanceTooltip,
  tone = "default",
  accent = false,
  footer,
}: {
  label: string;
  value: string | number;
  icon?: ComponentType<{ className?: string }>;
  /** Small secondary line under the value — context, not a fabricated trend. */
  caption?: string;
  provenance?: DataProvenance;
  /** Overrides the badge's default tooltip (e.g. to say what exactly is pending). */
  provenanceTooltip?: string;
  /** Resalta las tarjetas cuyo valor es un veredicto (p. ej. Legal Gate). */
  tone?: KpiTone;
  /** Valor en el color primario sin resaltar la tarjeta (los importes en verde del mockup). */
  accent?: boolean;
  /** Línea inferior libre (chip «Editable», barra de riesgo…), bajo el caption. */
  footer?: ReactNode;
}) {
  return (
    <Card
      className={cn(
        tone === "success" && "bg-primary/5 ring-primary/40",
        tone === "warning" && "bg-amber-500/5 ring-amber-500/40",
        tone === "danger" && "bg-red-500/5 ring-red-500/40",
      )}
    >
      <CardHeader className="flex flex-row items-center justify-between gap-2 pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">{label}</CardTitle>
        {Icon ? <Icon className="size-4 shrink-0 text-primary" /> : null}
      </CardHeader>
      <CardContent className="space-y-1.5">
        <p
          className={cn(
            "text-2xl leading-tight font-semibold",
            (tone === "success" || accent) && "text-primary",
            tone === "warning" && "text-amber-500",
            tone === "danger" && "text-red-500",
          )}
        >
          {value}
        </p>
        {caption ? <p className="text-xs text-muted-foreground">{caption}</p> : null}
        {footer}
        {provenance ? <DataProvenanceBadge status={provenance} tooltip={provenanceTooltip} /> : null}
      </CardContent>
    </Card>
  );
}
