/** Minigráfico de tendencia (línea con área suave), sin ejes. */
export function Sparkline({
  values,
  width = 72,
  height = 24,
  color = "var(--emerald)",
  className,
}: {
  values: number[];
  width?: number;
  height?: number;
  color?: string;
  className?: string;
}) {
  if (values.length < 2) return null;
  const min = Math.min(...values);
  const span = Math.max(...values) - min || 1;
  const points = values.map((v, k) => [
    ((k / (values.length - 1)) * (width - 2) + 1).toFixed(1),
    (height - 2 - ((v - min) / span) * (height - 4)).toFixed(1),
  ]);
  const line = points.map((p) => p.join(",")).join(" ");
  return (
    <svg viewBox={`0 0 ${width} ${height}`} width={width} height={height} className={className} aria-hidden>
      <polygon points={`1,${height} ${line} ${width - 1},${height}`} fill={color} fillOpacity={0.12} />
      <polyline points={line} fill="none" stroke={color} strokeWidth={1.75} strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}
