import { cn } from "@/lib/utils";

export interface RankedItem {
  key: string;
  label: string;
  /** Línea pequeña bajo la etiqueta (categoría, estado…). */
  sublabel?: string;
  /** Valor con el que se dibuja la barra; null = sin dato (sin barra). */
  value: number | null;
  valueLabel: string;
}

/** Ranking horizontal de una sola métrica con soporte de valores negativos: la
 * barra parte de una línea de cero y los negativos van en el color de peligro.
 * Solo dibuja; el orden y el formato los decide quien la usa. */
export function RankedBars({ items, ariaLabel }: { items: RankedItem[]; ariaLabel: string }) {
  const values = items.flatMap((i) => (i.value === null ? [] : [i.value]));
  const positiveMax = Math.max(0, ...values);
  const negativeMax = Math.max(0, ...values.map((v) => -v));
  const span = positiveMax + negativeMax || 1;
  const zeroAt = (negativeMax / span) * 100;

  return (
    <ul className="space-y-3" aria-label={ariaLabel}>
      {items.map((item) => {
        const width = item.value === null ? 0 : (Math.abs(item.value) / span) * 100;
        const negative = item.value !== null && item.value < 0;
        return (
          <li key={item.key} className="space-y-1.5">
            <div className="flex items-baseline justify-between gap-3">
              <div className="min-w-0">
                <p className="truncate text-sm font-medium">{item.label}</p>
                {item.sublabel ? <p className="truncate text-[11px] text-muted-foreground">{item.sublabel}</p> : null}
              </div>
              <p className={cn("shrink-0 text-sm font-medium tabular-nums", negative && "text-destructive")}>
                {item.valueLabel}
              </p>
            </div>
            <div className="relative h-1.5 rounded-full bg-muted" role="img" aria-label={`${item.label}: ${item.valueLabel}`}>
              {item.value !== null ? (
                <div
                  className={cn("absolute top-0 h-full rounded-full", negative ? "bg-destructive" : "bg-primary")}
                  style={{ width: `${width}%`, left: negative ? `${zeroAt - width}%` : `${zeroAt}%` }}
                />
              ) : null}
              {negativeMax > 0 ? (
                <span className="absolute top-[-2px] h-2.5 w-px bg-border" style={{ left: `${zeroAt}%` }} aria-hidden />
              ) : null}
            </div>
          </li>
        );
      })}
    </ul>
  );
}
