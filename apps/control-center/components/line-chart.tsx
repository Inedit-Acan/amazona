"use client";

import { useRef, useState } from "react";

export interface LineSeries {
  key: string;
  label: string;
  /** Color CSS (variable o hex). */
  color: string;
  points: { x: number; y: number }[];
}

export interface LineMarker {
  x: number;
  y: number;
  /** Líneas de la etiqueta que acompaña al punto. */
  label: string[];
}

const W = 560;
const PAD = { top: 12, right: 14, bottom: 34, left: 52 };

function niceStep(span: number, count: number): number {
  const raw = span / count || 1;
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * magnitude).find((s) => s >= raw) ?? raw;
  return step;
}

/** Gráfico de líneas multi-serie en SVG: rejilla, ejes, leyenda, puntos, tooltip
 * al pasar el cursor (el valor de cada serie en la x más cercana) y marcadores
 * con etiqueta (p. ej. el punto de equilibrio). Solo dibuja lo que recibe. */
export function LineChart({
  series,
  ariaLabel,
  formatY,
  xLabel,
  yLabel,
  hoverTitle = (x) => String(x),
  defaultHoverX,
  markers = [],
  height = 230,
  legend = true,
}: {
  series: LineSeries[];
  ariaLabel: string;
  formatY: (value: number) => string;
  xLabel?: string;
  yLabel?: string;
  hoverTitle?: (x: number) => string;
  /** x con el tooltip visible de entrada (como en el mockup). */
  defaultHoverX?: number;
  markers?: LineMarker[];
  height?: number;
  legend?: boolean;
}) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [hoverX, setHoverX] = useState<number | undefined>(defaultHoverX);

  const H = height;
  const xs = [...new Set(series.flatMap((s) => s.points.map((p) => p.x)))].sort((a, b) => a - b);
  const ys = series.flatMap((s) => s.points.map((p) => p.y)).concat(markers.map((m) => m.y), 0);
  const step = niceStep(Math.max(...ys) - Math.min(...ys), 4);
  const yMin = Math.floor(Math.min(...ys) / step) * step;
  const yMax = Math.ceil(Math.max(...ys) / step) * step || step;
  const xMin = xs[0] ?? 0;
  const xMax = xs[xs.length - 1] ?? 1;
  const sx = (x: number) => PAD.left + ((x - xMin) / (xMax - xMin || 1)) * (W - PAD.left - PAD.right);
  const sy = (y: number) => PAD.top + (1 - (y - yMin) / (yMax - yMin || 1)) * (H - PAD.top - PAD.bottom);
  const yTicks: number[] = [];
  for (let v = yMin; v <= yMax + step / 2; v += step) yTicks.push(Math.round(v * 100) / 100);

  function onMove(event: React.MouseEvent<SVGSVGElement>) {
    const rect = svgRef.current?.getBoundingClientRect();
    if (!rect || xs.length === 0) return;
    const x = xMin + (((event.clientX - rect.left) / rect.width) * W - PAD.left) / (W - PAD.left - PAD.right) * (xMax - xMin);
    setHoverX(xs.reduce((best, v) => (Math.abs(v - x) < Math.abs(best - x) ? v : best), xs[0]));
  }

  const hovered =
    hoverX === undefined
      ? []
      : series.flatMap((s) => {
          const p = s.points.find((point) => point.x === hoverX);
          return p ? [{ series: s, point: p }] : [];
        });
  const tooltipLeft = hoverX !== undefined && sx(hoverX) > W * 0.6;

  return (
    <div className="space-y-2">
      {legend ? (
        <ul className="flex flex-wrap justify-center gap-x-4 gap-y-1 text-[11px] text-muted-foreground">
          {series.map((s) => (
            <li key={s.key} className="flex items-center gap-1.5">
              <span className="size-2 rounded-full" style={{ background: s.color }} aria-hidden />
              {s.label}
            </li>
          ))}
        </ul>
      ) : null}
      <svg
        ref={svgRef}
        viewBox={`0 0 ${W} ${H}`}
        className="h-auto w-full select-none"
        role="img"
        aria-label={ariaLabel}
        onMouseMove={onMove}
        onMouseLeave={() => setHoverX(defaultHoverX)}
      >
        {yTicks.map((v) => (
          <g key={v}>
            <line
              x1={PAD.left}
              x2={W - PAD.right}
              y1={sy(v)}
              y2={sy(v)}
              stroke="currentColor"
              className={v === 0 ? "text-muted-foreground/50" : "text-border"}
              strokeWidth={1}
            />
            <text x={PAD.left - 6} y={sy(v) + 3} textAnchor="end" className="fill-muted-foreground text-[10px]">
              {formatY(v)}
            </text>
          </g>
        ))}
        {xs.map((x) => (
          <text key={x} x={sx(x)} y={H - PAD.bottom + 14} textAnchor="middle" className="fill-muted-foreground text-[10px]">
            {x}
          </text>
        ))}
        {xLabel ? (
          <text x={(PAD.left + W - PAD.right) / 2} y={H - 4} textAnchor="middle" className="fill-muted-foreground text-[10px]">
            {xLabel}
          </text>
        ) : null}
        {yLabel ? (
          <text
            x={12}
            y={(PAD.top + H - PAD.bottom) / 2}
            textAnchor="middle"
            transform={`rotate(-90 12 ${(PAD.top + H - PAD.bottom) / 2})`}
            className="fill-muted-foreground text-[10px]"
          >
            {yLabel}
          </text>
        ) : null}

        {hoverX !== undefined ? (
          <line
            x1={sx(hoverX)}
            x2={sx(hoverX)}
            y1={PAD.top}
            y2={H - PAD.bottom}
            stroke="currentColor"
            strokeDasharray="3 3"
            className="text-muted-foreground/60"
          />
        ) : null}

        {series.map((s) => (
          <g key={s.key}>
            <polyline
              fill="none"
              stroke={s.color}
              strokeWidth={2}
              strokeLinejoin="round"
              points={s.points.map((p) => `${sx(p.x)},${sy(p.y)}`).join(" ")}
            />
            {s.points.map((p) => (
              <circle key={p.x} cx={sx(p.x)} cy={sy(p.y)} r={p.x === hoverX ? 4.5 : 2.5} fill={s.color} />
            ))}
          </g>
        ))}

        {markers.map((m) => {
          const boxW = 86;
          const boxH = 12 + m.label.length * 12;
          const bx = Math.min(Math.max(sx(m.x) - boxW / 2, PAD.left), W - PAD.right - boxW);
          const by = Math.max(sy(m.y) - boxH - 10, PAD.top);
          return (
            <g key={`${m.x}-${m.y}`}>
              <circle cx={sx(m.x)} cy={sy(m.y)} r={5} className="fill-foreground stroke-background" strokeWidth={2} />
              <rect x={bx} y={by} width={boxW} height={boxH} rx={6} className="fill-panel-2 stroke-border" />
              {m.label.map((line, k) => (
                <text key={k} x={bx + boxW / 2} y={by + 15 + k * 12} textAnchor="middle" className="fill-foreground text-[10px]">
                  {line}
                </text>
              ))}
            </g>
          );
        })}

        {hovered.length > 0 && hoverX !== undefined ? (
          <g>
            {(() => {
              const boxW = 140;
              const boxH = 22 + hovered.length * 14;
              const bx = tooltipLeft ? sx(hoverX) - boxW - 10 : sx(hoverX) + 10;
              const by = PAD.top;
              return (
                <>
                  <rect x={bx} y={by} width={boxW} height={boxH} rx={6} className="fill-panel-2 stroke-border" />
                  <text x={bx + 10} y={by + 15} className="fill-foreground text-[10px] font-medium">
                    {hoverTitle(hoverX)}
                  </text>
                  {hovered.map(({ series: s, point }, k) => (
                    <g key={s.key}>
                      <circle cx={bx + 13} cy={by + 26 + k * 14} r={3} fill={s.color} />
                      <text x={bx + 21} y={by + 29 + k * 14} className="fill-foreground text-[10px]">
                        {s.label}: {formatY(point.y)}
                      </text>
                    </g>
                  ))}
                </>
              );
            })()}
          </g>
        ) : null}
      </svg>
    </div>
  );
}
