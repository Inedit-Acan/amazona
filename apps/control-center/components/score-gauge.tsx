import { cn } from "@/lib/utils";

const WIDTH = 120;
const HEIGHT = 72;
const CX = 60;
const CY = 62;
const RADIUS = 48;

function toneFor(value: number, max: number): { stroke: string; className: string } {
  const ratio = value / max;
  if (ratio >= 0.75) return { stroke: "var(--emerald-bright)", className: "drop-shadow-[0_0_5px_var(--emerald)]" };
  if (ratio >= 0.5) return { stroke: "var(--warning)", className: "" };
  return { stroke: "var(--danger)", className: "" };
}

/** Medidor semicircular de un score (ReadinessScore del catálogo, §4). El número
 * siempre va escrito en el centro: el color solo refuerza, nunca es el único
 * canal (accesibilidad, §6). El caller decide qué significa `value` — este
 * componente no calcula ningún score. */
export function ScoreGauge({
  value,
  max = 100,
  label,
  className,
}: {
  value: number;
  max?: number;
  /** Etiqueta bajo el medidor, p. ej. "Fiabilidad". */
  label?: string;
  className?: string;
}) {
  const clamped = Math.max(0, Math.min(max, value));
  const fraction = clamped / max;
  const angle = Math.PI - fraction * Math.PI;
  const endX = CX + RADIUS * Math.cos(angle);
  const endY = CY - RADIUS * Math.sin(angle);
  const tone = toneFor(clamped, max);
  const rounded = Math.round(clamped);

  return (
    <div className={cn("flex flex-col items-center", className)}>
      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        className="h-auto w-full max-w-[9rem]"
        role="img"
        aria-label={`${label ?? "Score"}: ${rounded} de ${max}`}
      >
        <path
          d={`M ${CX - RADIUS} ${CY} A ${RADIUS} ${RADIUS} 0 0 1 ${CX + RADIUS} ${CY}`}
          fill="none"
          stroke="var(--panel-hover)"
          strokeWidth={8}
          strokeLinecap="round"
        />
        {fraction > 0 ? (
          <path
            d={`M ${CX - RADIUS} ${CY} A ${RADIUS} ${RADIUS} 0 0 1 ${endX} ${endY}`}
            fill="none"
            stroke={tone.stroke}
            strokeWidth={8}
            strokeLinecap="round"
            className={tone.className}
          />
        ) : null}
        <text x={CX} y={CY - 8} textAnchor="middle" fontSize={26} fontWeight={600} fill="var(--text-primary)">
          {rounded}
        </text>
        <text x={CX} y={CY + 6} textAnchor="middle" fontSize={9} fill="var(--text-secondary)">
          /{max}
        </text>
      </svg>
      {label ? <p className="-mt-1 text-xs text-muted-foreground">{label}</p> : null}
    </div>
  );
}
