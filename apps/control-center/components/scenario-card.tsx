import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

export interface ScenarioMetric {
  label: string;
  value: string;
}

/** Tarjeta de un escenario (ScenarioCard del catálogo, §4): un resultado
 * principal grande y las métricas de apoyo debajo. No calcula nada — quien la
 * usa decide qué escenario es el "actual" (`highlighted`) y qué valores muestra. */
export function ScenarioCard({
  title,
  icon: Icon,
  badge,
  highlighted = false,
  headline,
  metrics,
}: {
  title: string;
  icon?: LucideIcon;
  /** Etiqueta pequeña junto al título (p. ej. «Actual»). */
  badge?: string;
  highlighted?: boolean;
  headline: { label: string; value: string; negative?: boolean };
  metrics: ScenarioMetric[];
}) {
  return (
    <div
      className={cn(
        "rounded-xl border p-4",
        highlighted ? "border-primary bg-primary/5 shadow-[0_0_18px_-8px_var(--emerald)]" : "bg-background/40",
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <p className={cn("flex items-center gap-1.5 text-sm font-semibold", highlighted && "text-primary")}>
          {Icon ? <Icon className="size-4 shrink-0" /> : null}
          {title}
        </p>
        {badge ? (
          <span className="rounded-md bg-primary px-1.5 py-0.5 text-[10px] font-medium text-primary-foreground">
            {badge}
          </span>
        ) : null}
      </div>
      <p className={cn("mt-2 text-2xl font-semibold", headline.negative && "text-destructive")}>{headline.value}</p>
      <p className="text-[11px] text-muted-foreground">{headline.label}</p>
      <dl className="mt-3 space-y-1 border-t pt-3 text-xs">
        {metrics.map((metric) => (
          <div key={metric.label} className="flex justify-between gap-2">
            <dt className="text-muted-foreground">{metric.label}</dt>
            <dd className="font-medium">{metric.value}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
