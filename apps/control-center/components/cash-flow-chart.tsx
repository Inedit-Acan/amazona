export interface CashFlowPoint {
  label: string;
  inflow: number;
  outflow: number;
  /** Saldo acumulado al cierre del mes. */
  balance: number;
  /** El mes es previsión, no cierre real. */
  forecast: boolean;
}

const W = 720;
const PAD = { top: 16, right: 16, bottom: 34, left: 58 };

function niceStep(span: number, count: number): number {
  const raw = span / count || 1;
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  return [1, 2, 2.5, 5, 10].map((m) => m * magnitude).find((s) => s >= raw) ?? raw;
}

/** Cash flow mensual: barras de entradas y salidas, línea de saldo (continua en
 * los meses cerrados y discontinua en la previsión) y marca del mes en curso.
 * Solo dibuja lo que recibe; no sabe de dónde salen las cifras. */
export function CashFlowChart({
  points,
  formatValue,
  height = 260,
  warning,
  ariaLabel,
}: {
  points: CashFlowPoint[];
  formatValue: (value: number) => string;
  height?: number;
  /** Aviso anclado al mes indicado (p. ej. tensión de caja prevista). */
  warning?: { index: number; lines: string[] };
  ariaLabel: string;
}) {
  const H = height;
  const values = points.flatMap((p) => [p.inflow, -p.outflow, p.balance]).concat(0);
  const step = niceStep(Math.max(...values) - Math.min(...values), 4);
  const yMin = Math.floor(Math.min(...values) / step) * step;
  const yMax = Math.ceil(Math.max(...values) / step) * step || step;
  const plotW = W - PAD.left - PAD.right;
  const slot = plotW / (points.length || 1);
  const barW = Math.min(18, slot / 3.2);
  const cx = (index: number) => PAD.left + slot * (index + 0.5);
  const sy = (value: number) => PAD.top + (1 - (value - yMin) / (yMax - yMin || 1)) * (H - PAD.top - PAD.bottom);
  const zero = sy(0);

  const ticks: number[] = [];
  for (let v = yMin; v <= yMax + step / 2; v += step) ticks.push(Math.round(v * 100) / 100);

  const realPoints = points.map((p, k) => ({ p, k })).filter(({ p }) => !p.forecast);
  const lastReal = realPoints.length ? realPoints[realPoints.length - 1].k : -1;
  const line = (from: number, to: number) =>
    points
      .slice(from, to + 1)
      .map((p, k) => `${cx(from + k).toFixed(1)},${sy(p.balance).toFixed(1)}`)
      .join(" ");

  return (
    <div className="space-y-2">
      <ul className="flex flex-wrap justify-center gap-x-4 gap-y-1 text-[11px] text-muted-foreground">
        <li className="flex items-center gap-1.5">
          <span className="size-2 rounded-full bg-primary" aria-hidden /> Entradas
        </li>
        <li className="flex items-center gap-1.5">
          <span className="size-2 rounded-full bg-destructive" aria-hidden /> Salidas
        </li>
        <li className="flex items-center gap-1.5">
          <span className="w-3.5 border-t-2 border-foreground" aria-hidden /> Saldo real
        </li>
        <li className="flex items-center gap-1.5">
          <span className="w-3.5 border-t-2 border-dashed border-foreground" aria-hidden /> Forecast
        </li>
      </ul>

      <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img" aria-label={ariaLabel}>
        {ticks.map((v) => (
          <g key={v}>
            <line x1={PAD.left} x2={W - PAD.right} y1={sy(v)} y2={sy(v)} stroke="currentColor" className={v === 0 ? "text-muted-foreground/50" : "text-border"} strokeWidth={1} />
            <text x={PAD.left - 6} y={sy(v) + 3} textAnchor="end" className="fill-muted-foreground text-[10px]">
              {formatValue(v)}
            </text>
          </g>
        ))}

        {points.map((point, k) => (
          <g key={point.label + k} opacity={point.forecast ? 0.45 : 1}>
            <rect x={cx(k) - barW - 1} y={sy(Math.max(0, point.inflow))} width={barW} height={Math.abs(zero - sy(point.inflow))} rx={3} className="fill-primary" />
            <rect x={cx(k) + 1} y={zero} width={barW} height={Math.abs(sy(-point.outflow) - zero)} rx={3} className="fill-destructive" />
            <text x={cx(k)} y={H - PAD.bottom + 14} textAnchor="middle" className="fill-muted-foreground text-[10px]">
              {point.label}
            </text>
          </g>
        ))}

        {lastReal >= 0 ? (
          <>
            <line
              x1={cx(lastReal) + slot / 2}
              x2={cx(lastReal) + slot / 2}
              y1={PAD.top}
              y2={H - PAD.bottom}
              stroke="currentColor"
              className="text-muted-foreground"
              strokeDasharray="4 4"
            />
            <text x={cx(lastReal) + slot / 2 + 4} y={PAD.top + 10} className="fill-muted-foreground text-[10px]">
              Hoy
            </text>
            <polyline points={line(0, lastReal)} fill="none" stroke="var(--text-primary)" strokeWidth={2} strokeLinejoin="round" />
          </>
        ) : null}
        {lastReal < points.length - 1 ? (
          <polyline
            points={line(Math.max(0, lastReal), points.length - 1)}
            fill="none"
            stroke="var(--text-primary)"
            strokeWidth={2}
            strokeDasharray="5 4"
            strokeLinejoin="round"
          />
        ) : null}
        {points.map((point, k) => (
          <circle key={`dot-${k}`} cx={cx(k)} cy={sy(point.balance)} r={3} fill="var(--text-primary)" />
        ))}

        {warning && warning.index >= 0 && warning.index < points.length
          ? (() => {
              const boxW = 168;
              const boxH = 14 + warning.lines.length * 12;
              const bx = Math.min(Math.max(cx(warning.index) - boxW / 2, PAD.left), W - PAD.right - boxW);
              const by = PAD.top + 6;
              return (
                <g>
                  <rect x={bx} y={by} width={boxW} height={boxH} rx={6} className="fill-panel-2 stroke-warning" />
                  {warning.lines.map((text, k) => (
                    <text key={text} x={bx + 10} y={by + 15 + k * 12} className="fill-warning text-[10px]">
                      {text}
                    </text>
                  ))}
                </g>
              );
            })()
          : null}
      </svg>
    </div>
  );
}
