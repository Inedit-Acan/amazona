import { cn } from "@/lib/utils";

export interface StackedSegment {
  key: string;
  label: string;
  value: number;
  /** Texto ya formateado del valor (importe, nº…) que se muestra en la leyenda. */
  valueLabel: string;
  /** Clase de fondo Tailwind del segmento (p. ej. `bg-primary`). */
  className: string;
}

/** Barra apilada de una sola serie con leyenda: cada segmento es una parte de un
 * total (presupuesto usado/disponible, decisiones GO/REVIEW/NO_GO…). El ancho se
 * calcula sobre `total`, o sobre la suma de segmentos si esta es mayor, para que
 * nunca desborde. La leyenda repite los valores, así que el color no es la única
 * señal. */
export function StackedBar({
  segments,
  total,
  ariaLabel,
}: {
  segments: StackedSegment[];
  total?: number;
  ariaLabel: string;
}) {
  const sum = segments.reduce((acc, s) => acc + Math.max(0, s.value), 0);
  const base = Math.max(total ?? 0, sum);

  return (
    <div className="space-y-3">
      <div className="flex h-2.5 w-full overflow-hidden rounded-full bg-muted" role="img" aria-label={ariaLabel}>
        {base > 0
          ? segments.map((segment) =>
              segment.value > 0 ? (
                <div
                  key={segment.key}
                  className={cn("h-full first:rounded-l-full last:rounded-r-full", segment.className)}
                  style={{ width: `${(segment.value / base) * 100}%` }}
                />
              ) : null,
            )
          : null}
      </div>
      <ul className="grid gap-x-4 gap-y-1.5 text-xs sm:grid-cols-2">
        {segments.map((segment) => (
          <li key={segment.key} className="flex items-center justify-between gap-2">
            <span className="flex items-center gap-2 text-muted-foreground">
              <span className={cn("size-2 shrink-0 rounded-full", segment.className)} aria-hidden />
              {segment.label}
            </span>
            <span className="font-medium tabular-nums">{segment.valueLabel}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
