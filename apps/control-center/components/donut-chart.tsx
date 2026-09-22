/** Anillo segmentado (reparto de un total: atribución de ingresos, mix de
 * canales…) con el total escrito en el centro. Solo dibuja lo que recibe; los
 * `value` no tienen que sumar 1. */
export function DonutChart({
  segments,
  centerLabel,
  centerCaption,
  size = 132,
  ariaLabel,
}: {
  segments: { key: string; value: number; color: string }[];
  centerLabel: string;
  centerCaption?: string;
  size?: number;
  ariaLabel: string;
}) {
  const r = 40;
  const circumference = 2 * Math.PI * r;
  const total = segments.reduce((sum, s) => sum + Math.max(0, s.value), 0);
  const gap = segments.length > 1 ? 1.5 : 0;
  const starts = segments.map((_, k) =>
    segments.slice(0, k).reduce((sum, s) => sum + (Math.max(0, s.value) / (total || 1)) * circumference, 0),
  );
  return (
    <svg viewBox="0 0 100 100" width={size} height={size} className="shrink-0" role="img" aria-label={ariaLabel}>
      <circle cx="50" cy="50" r={r} fill="none" stroke="var(--panel-hover)" strokeWidth="11" />
      {total > 0
        ? segments.map((s, k) => {
            const length = (Math.max(0, s.value) / total) * circumference;
            const dash = Math.max(0, length - gap);
            return (
              <circle
                key={s.key}
                cx="50"
                cy="50"
                r={r}
                fill="none"
                stroke={s.color}
                strokeWidth="11"
                strokeDasharray={`${dash.toFixed(2)} ${(circumference - dash).toFixed(2)}`}
                strokeDashoffset={(-starts[k]).toFixed(2)}
                transform="rotate(-90 50 50)"
              />
            );
          })
        : null}
      <text x="50" y={centerCaption ? 47 : 51} textAnchor="middle" dominantBaseline="middle" fontSize="13" fontWeight="600" fill="var(--text-primary)">
        {centerLabel}
      </text>
      {centerCaption ? (
        <text x="50" y="60" textAnchor="middle" dominantBaseline="middle" fontSize="5.5" className="fill-muted-foreground">
          {centerCaption}
        </text>
      ) : null}
    </svg>
  );
}
