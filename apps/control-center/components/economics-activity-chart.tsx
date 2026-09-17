"use client";

import { useId, useState } from "react";
import { TableIcon } from "lucide-react";
import type { EconomicsTimeseriesPoint } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

const BAR_MAX_WIDTH = 22;
const BAR_GAP = 2;
const CHART_HEIGHT = 160;
const AXIS_PADDING = 24;

function niceMax(value: number): number {
  if (value <= 0) return 1;
  const magnitude = 10 ** Math.floor(Math.log10(value));
  return Math.ceil(value / magnitude) * magnitude;
}

function formatDay(day: string): string {
  const date = new Date(`${day}T00:00:00`);
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export function EconomicsActivityChart({ points }: { points: EconomicsTimeseriesPoint[] }) {
  const gradientId = useId();
  const [hovered, setHovered] = useState<number | null>(null);
  const [showTable, setShowTable] = useState(false);

  if (points.length === 0) {
    return <p className="py-6 text-center text-sm text-muted-foreground">Sin análisis económicos todavía.</p>;
  }

  const maxCount = niceMax(Math.max(...points.map((p) => p.analyses_count)));
  const chartWidth = points.length * (BAR_MAX_WIDTH + BAR_GAP);
  const scaleY = (count: number) => (count / maxCount) * CHART_HEIGHT;

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <p className="text-xs text-muted-foreground">Análisis económicos por día — recuento real</p>
        <Button size="sm" variant="ghost" onClick={() => setShowTable((v) => !v)}>
          <TableIcon className="size-3.5" />
          {showTable ? "Ver gráfico" : "Ver tabla"}
        </Button>
      </div>

      {showTable ? (
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Día</TableHead>
                <TableHead>Análisis</TableHead>
                <TableHead>Margen medio</TableHead>
                <TableHead>Precio medio</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {points.map((point) => (
                <TableRow key={point.day}>
                  <TableCell className="text-xs">{point.day}</TableCell>
                  <TableCell className="text-xs">{point.analyses_count}</TableCell>
                  <TableCell className="text-xs">{(point.avg_margin_percent * 100).toFixed(1)}%</TableCell>
                  <TableCell className="text-xs">${point.avg_sale_price.toFixed(2)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      ) : (
        <div className="relative">
          <svg
            viewBox={`0 0 ${chartWidth} ${CHART_HEIGHT + AXIS_PADDING}`}
            className="h-[184px] w-full"
            role="img"
            aria-label="Análisis económicos por día, últimos 30 días"
          >
            <defs>
              <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="var(--emerald-bright)" />
                <stop offset="100%" stopColor="var(--emerald)" />
              </linearGradient>
            </defs>
            <line
              x1={0}
              y1={CHART_HEIGHT}
              x2={chartWidth}
              y2={CHART_HEIGHT}
              stroke="var(--border)"
              strokeWidth={1}
            />
            {points.map((point, i) => {
              const barHeight = Math.max(scaleY(point.analyses_count), point.analyses_count > 0 ? 2 : 0);
              const x = i * (BAR_MAX_WIDTH + BAR_GAP);
              const y = CHART_HEIGHT - barHeight;
              const isHovered = hovered === i;
              return (
                <g key={point.day}>
                  <rect
                    x={x}
                    y={y}
                    width={BAR_MAX_WIDTH}
                    height={barHeight}
                    rx={4}
                    fill={`url(#${gradientId})`}
                    opacity={isHovered ? 1 : 0.85}
                    onPointerEnter={() => setHovered(i)}
                    onPointerLeave={() => setHovered((h) => (h === i ? null : h))}
                  />
                  {/* transparent hit target taller than the bar itself, per dataviz skill §interaction */}
                  <rect
                    x={x}
                    y={0}
                    width={BAR_MAX_WIDTH}
                    height={CHART_HEIGHT}
                    fill="transparent"
                    onPointerEnter={() => setHovered(i)}
                    onPointerLeave={() => setHovered((h) => (h === i ? null : h))}
                  />
                  {i === 0 || i === points.length - 1 || isHovered ? (
                    <text
                      x={x + BAR_MAX_WIDTH / 2}
                      y={CHART_HEIGHT + 16}
                      textAnchor="middle"
                      fontSize={9}
                      fill="var(--text-secondary)"
                    >
                      {formatDay(point.day)}
                    </text>
                  ) : null}
                </g>
              );
            })}
          </svg>

          {hovered !== null ? (
            <div
              className="pointer-events-none absolute top-0 -translate-x-1/2 rounded-md border bg-popover px-2.5 py-1.5 text-xs shadow-md"
              style={{ left: `${((hovered * (BAR_MAX_WIDTH + BAR_GAP) + BAR_MAX_WIDTH / 2) / chartWidth) * 100}%` }}
            >
              <p className="font-medium">{formatDay(points[hovered].day)}</p>
              <p>
                <strong>{points[hovered].analyses_count}</strong> análisis
              </p>
              <p className="text-muted-foreground">
                Margen medio {(points[hovered].avg_margin_percent * 100).toFixed(1)}% · precio medio $
                {points[hovered].avg_sale_price.toFixed(2)}
              </p>
            </div>
          ) : null}
        </div>
      )}
    </div>
  );
}
