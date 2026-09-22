import { cn } from "@/lib/utils";

/** Anillo de porcentaje con el valor escrito en el centro (p. ej. el
 * cumplimiento general de Legal). `value` es una fracción 0–1. */
export function RingGauge({ value, size = 56, className }: { value: number; size?: number; className?: string }) {
  const clamped = Math.max(0, Math.min(1, value));
  const r = 22;
  const circumference = 2 * Math.PI * r;
  const tone = clamped >= 0.85 ? "var(--emerald-bright)" : clamped >= 0.6 ? "var(--warning)" : "var(--danger)";
  return (
    <svg viewBox="0 0 56 56" width={size} height={size} className={cn("shrink-0", className)} role="img" aria-label={`${Math.round(clamped * 100)} %`}>
      <circle cx="28" cy="28" r={r} fill="none" stroke="var(--panel-hover)" strokeWidth="6" />
      <circle
        cx="28"
        cy="28"
        r={r}
        fill="none"
        stroke={tone}
        strokeWidth="6"
        strokeLinecap="round"
        strokeDasharray={`${(clamped * circumference).toFixed(2)} ${circumference.toFixed(2)}`}
        transform="rotate(-90 28 28)"
      />
      <text x="28" y="29" textAnchor="middle" dominantBaseline="middle" fontSize="13" fontWeight="600" fill="var(--text-primary)">
        {Math.round(clamped * 100)}%
      </text>
    </svg>
  );
}
