export interface ColumnDatum {
  x: number;
  value: number;
}

const W = 220;
const PAD = { top: 8, right: 4, bottom: 16, left: 28 };

/** Máximo «redondo» por encima del valor mayor (1, 2, 2,5 o 5 × 10^n). */
function niceMax(max: number): number {
  if (max <= 0) return 1;
  const magnitude = 10 ** Math.floor(Math.log10(max));
  const step = [1, 1.5, 2, 2.5, 3, 4, 5, 7.5, 10].map((m) => m * magnitude).find((s) => s >= max) ?? max;
  return step;
}

/** Barras compactas de una serie temporal, con ejes y sin etiqueta por barra: el
 * `BarChart` del catálogo escribe el valor encima de cada barra y no cabe cuando
 * son veinticuatro (las requests por minuto de las últimas 24 h). */
export function ColumnChart({
  data,
  formatY,
  formatX,
  xTicks,
  ariaLabel,
  height = 140,
  color = "var(--emerald)",
}: {
  data: ColumnDatum[];
  formatY: (value: number) => string;
  formatX: (x: number) => string;
  /** x con etiqueta en el eje; por defecto, todas. */
  xTicks?: number[];
  ariaLabel: string;
  height?: number;
  color?: string;
}) {
  if (data.length === 0) return null;
  const H = height;
  const plotW = W - PAD.left - PAD.right;
  const plotH = H - PAD.top - PAD.bottom;
  const max = niceMax(Math.max(...data.map((d) => d.value)));
  const slot = plotW / data.length;
  const barW = Math.max(2, slot * 0.62);
  const yTicks = [0, max / 2, max];
  const sy = (value: number) => PAD.top + (1 - value / max) * plotH;
  const sx = (index: number) => PAD.left + slot * index + (slot - barW) / 2;

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img" aria-label={ariaLabel}>
      {yTicks.map((value) => (
        <g key={value}>
          <line x1={PAD.left} x2={W - PAD.right} y1={sy(value)} y2={sy(value)} stroke="var(--border)" strokeWidth={1} />
          <text x={PAD.left - 5} y={sy(value) + 3} textAnchor="end" className="fill-muted-foreground text-[9px]">
            {formatY(value)}
          </text>
        </g>
      ))}
      {data.map((datum, index) => (
        <rect
          key={datum.x}
          x={sx(index)}
          y={sy(datum.value)}
          width={barW}
          height={Math.max(1, plotH - (sy(datum.value) - PAD.top))}
          rx={2}
          fill={color}
          opacity={0.85}
        >
          <title>{`${formatX(datum.x)}: ${formatY(datum.value)}`}</title>
        </rect>
      ))}
      {(xTicks ?? data.map((d) => d.x)).map((x) => {
        const index = data.findIndex((d) => d.x === x);
        if (index < 0) return null;
        return (
          <text key={x} x={sx(index) + barW / 2} y={H - 5} textAnchor="middle" className="fill-muted-foreground text-[9px]">
            {formatX(x)}
          </text>
        );
      })}
    </svg>
  );
}
