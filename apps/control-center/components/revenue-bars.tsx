export interface RevenueBar {
  /** Posición del día dentro de la ventana (0 = el primero). */
  x: number;
  /** Alto de la barra (solo para dibujar); el importe exacto va en `text`. */
  value: number;
  /** Importe exacto, ya formateado, para el tooltip. */
  text: string;
  label: string;
}

const W = 560;
const PAD = { top: 10, right: 10, bottom: 22, left: 52 };

function niceMax(max: number): number {
  if (max <= 0) return 1;
  const magnitude = 10 ** Math.floor(Math.log10(max));
  return [1, 1.5, 2, 2.5, 3, 4, 5, 7.5, 10].map((m) => m * magnitude).find((s) => s >= max) ?? max;
}

/** Barras por día sobre una ventana fija de `days` días. Un día sin entradas NO tiene barra (ni una de altura cero):
 * es «sin datos», no un cero, y el hueco se ve. Solo dibuja lo que recibe. */
export function RevenueBars({
  days,
  bars,
  formatY,
  formatX,
  ariaLabel,
  height = 200,
  color = "var(--emerald)",
}: {
  days: number;
  bars: RevenueBar[];
  formatY: (value: number) => string;
  /** Etiqueta del día `x` de la ventana. */
  formatX: (x: number) => string;
  ariaLabel: string;
  height?: number;
  color?: string;
}) {
  const plotW = W - PAD.left - PAD.right;
  const plotH = height - PAD.top - PAD.bottom;
  const max = niceMax(Math.max(0, ...bars.map((bar) => bar.value)));
  const slot = plotW / days;
  const barW = Math.max(3, slot * 0.62);
  const sx = (x: number) => PAD.left + slot * x + (slot - barW) / 2;
  const sy = (value: number) => PAD.top + (1 - value / max) * plotH;
  const labelEvery = Math.max(1, Math.ceil(days / 6));

  return (
    <svg viewBox={`0 0 ${W} ${height}`} className="h-auto w-full" role="img" aria-label={ariaLabel}>
      {[0, max / 2, max].map((value) => (
        <g key={value}>
          <line x1={PAD.left} x2={W - PAD.right} y1={sy(value)} y2={sy(value)} stroke="var(--border)" strokeWidth={1} />
          <text x={PAD.left - 6} y={sy(value) + 3} textAnchor="end" className="fill-muted-foreground text-[10px]">
            {formatY(value)}
          </text>
        </g>
      ))}
      {bars.map((bar) => (
        <rect
          key={bar.x}
          x={sx(bar.x)}
          y={sy(bar.value)}
          width={barW}
          height={Math.max(2, PAD.top + plotH - sy(bar.value))}
          rx={2}
          fill={color}
          opacity={0.85}
        >
          <title>{`${bar.label}: ${bar.text}`}</title>
        </rect>
      ))}
      {Array.from({ length: days }, (_, x) => x)
        .filter((x) => x % labelEvery === 0 || x === days - 1)
        .map((x) => (
          <text key={x} x={sx(x) + barW / 2} y={height - 6} textAnchor="middle" className="fill-muted-foreground text-[10px]">
            {formatX(x)}
          </text>
        ))}
    </svg>
  );
}
