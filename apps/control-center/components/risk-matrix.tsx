import { cn } from "@/lib/utils";

export interface RiskPoint {
  name: string;
  /** 1 = baja … 3 = alta. */
  probability: number;
  /** 1 = bajo … 4 = crítico. */
  impact: number;
}

const PROBABILITY = ["Alta", "Media", "Baja"];
const IMPACT = ["Bajo", "Medio", "Alto", "Crítico"];

function cellTone(score: number): string {
  if (score >= 9) return "bg-destructive/35";
  if (score >= 6) return "bg-destructive/20";
  if (score >= 3) return "bg-warning/15";
  return "bg-primary/15";
}

function dotTone(score: number): string {
  if (score >= 9) return "bg-destructive";
  if (score >= 6) return "bg-[#f8925c]";
  if (score >= 3) return "bg-warning";
  return "bg-primary";
}

/** Matriz probabilidad × impacto con un punto por riesgo (el nombre va en el tooltip). */
export function RiskMatrix({ risks, className }: { risks: RiskPoint[]; className?: string }) {
  return (
    <div className={cn("grid grid-cols-[auto_repeat(4,minmax(0,1fr))] gap-1 text-[11px] text-muted-foreground", className)}>
      {PROBABILITY.map((label, row) => {
        const probability = 3 - row;
        return [
          <span key={`l-${label}`} className="flex items-center pr-1">
            {label}
          </span>,
          ...IMPACT.map((_, col) => {
            const impact = col + 1;
            const here = risks.filter((r) => r.probability === probability && r.impact === impact);
            return (
              <div
                key={`${probability}-${impact}`}
                className={cn("flex aspect-square min-h-8 flex-wrap items-center justify-center gap-1 rounded-sm", cellTone(probability * impact))}
              >
                {here.map((r) => (
                  <span key={r.name} title={r.name} className={cn("size-2.5 rounded-full ring-2 ring-background", dotTone(probability * impact))} />
                ))}
              </div>
            );
          }),
        ];
      })}
      <span />
      {IMPACT.map((label) => (
        <span key={label} className="text-center">
          {label}
        </span>
      ))}
    </div>
  );
}
