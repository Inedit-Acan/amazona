"use client";

import { useId, useState } from "react";
import { TableIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

export interface RadarAxis {
  key: string;
  label: string;
}

export interface RadarSeries {
  label: string;
  /** CSS color value. */
  color: string;
  /** 0-1 per axis key — already normalized to "higher is better" before it reaches this component. */
  values: Record<string, number>;
}

const SIZE = 220;
const CENTER = SIZE / 2;
const MAX_RADIUS = SIZE / 2 - 36;
const RINGS = [0.25, 0.5, 0.75, 1];
/** Margen lateral del lienzo para que las etiquetas largas de los ejes no se corten. */
const PAD_X = 44;

function pointFor(axisIndex: number, axisCount: number, value: number): { x: number; y: number } {
  const angle = -Math.PI / 2 + axisIndex * ((2 * Math.PI) / axisCount);
  const r = Math.max(0, Math.min(1, value)) * MAX_RADIUS;
  // Redondeado para que servidor y navegador generen exactamente el mismo SVG (hidratación).
  const round = (n: number) => Math.round(n * 100) / 100;
  return { x: round(CENTER + r * Math.cos(angle)), y: round(CENTER + r * Math.sin(angle)) };
}

function polygonPoints(axes: RadarAxis[], values: Record<string, number>): string {
  return axes.map((axis, i) => pointFor(i, axes.length, values[axis.key] ?? 0)).map((p) => `${p.x},${p.y}`).join(" ");
}

/** Two series at most (product analizado + media de mercado) — the
 * "emphasis" pattern from the dataviz skill: one accent series (the
 * story), one de-emphasis series (context), never a generated
 * categorical ramp. Always ships with a table view. */
export function RadarChart({
  axes,
  series,
  centerLabel,
}: {
  axes: RadarAxis[];
  series: RadarSeries[];
  /** Texto en el centro del radar (p. ej. el score global «91/100»). */
  centerLabel?: string;
}) {
  const clipId = useId();
  const [hoveredAxis, setHoveredAxis] = useState<number | null>(null);
  const [showTable, setShowTable] = useState(false);

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <div className="flex flex-wrap items-center gap-3">
          {series.map((s) => (
            <div key={s.label} className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <span className="inline-block h-0.5 w-4" style={{ backgroundColor: s.color }} />
              {s.label}
            </div>
          ))}
        </div>
        <Button size="sm" variant="ghost" onClick={() => setShowTable((v) => !v)}>
          <TableIcon className="size-3.5" />
          {showTable ? "Ver radar" : "Ver tabla"}
        </Button>
      </div>

      {showTable ? (
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Eje</TableHead>
                {series.map((s) => (
                  <TableHead key={s.label}>{s.label}</TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {axes.map((axis) => (
                <TableRow key={axis.key}>
                  <TableCell className="text-xs">{axis.label}</TableCell>
                  {series.map((s) => (
                    <TableCell key={s.label} className="text-xs">
                      {((s.values[axis.key] ?? 0) * 100).toFixed(0)}%
                    </TableCell>
                  ))}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      ) : (
        <svg
          viewBox={`${-PAD_X} 0 ${SIZE + 2 * PAD_X} ${SIZE}`}
          className="mx-auto h-auto w-full max-w-[340px]"
          role="img"
          aria-label={`Radar de ${axes.map((a) => a.label).join(", ")}`}
        >
          <defs>
            <clipPath id={clipId}>
              <circle cx={CENTER} cy={CENTER} r={MAX_RADIUS + 4} />
            </clipPath>
          </defs>

          {RINGS.map((ring) => (
            <polygon
              key={ring}
              points={axes.map((_, i) => {
                const p = pointFor(i, axes.length, ring);
                return `${p.x},${p.y}`;
              }).join(" ")}
              fill="none"
              stroke="var(--border)"
              strokeWidth={1}
            />
          ))}

          {axes.map((axis, i) => {
            const edge = pointFor(i, axes.length, 1);
            return (
              <line
                key={axis.key}
                x1={CENTER}
                y1={CENTER}
                x2={edge.x}
                y2={edge.y}
                stroke="var(--border)"
                strokeWidth={1}
              />
            );
          })}

          {series.map((s) => (
            <g key={s.label} clipPath={`url(#${clipId})`}>
              <polygon points={polygonPoints(axes, s.values)} fill={s.color} fillOpacity={0.12} />
              <polygon points={polygonPoints(axes, s.values)} fill="none" stroke={s.color} strokeWidth={2} />
            </g>
          ))}

          {axes.map((axis, i) => {
            const vertexPoint = pointFor(i, axes.length, 1.14);
            // Las etiquetas laterales se alinean hacia fuera para no pisar el polígono.
            const side = vertexPoint.x - CENTER;
            return (
              <text
                key={axis.key}
                x={vertexPoint.x}
                y={vertexPoint.y}
                textAnchor={side > 4 ? "start" : side < -4 ? "end" : "middle"}
                dominantBaseline="middle"
                fontSize={10}
                fill="var(--text-secondary)"
              >
                {axis.label}
              </text>
            );
          })}

          {axes.map((axis, i) => {
            const hitPoint = pointFor(i, axes.length, 1);
            return (
              <circle
                key={`hit-${axis.key}`}
                cx={hitPoint.x}
                cy={hitPoint.y}
                r={24}
                fill="transparent"
                onPointerEnter={() => setHoveredAxis(i)}
                onPointerLeave={() => setHoveredAxis((h) => (h === i ? null : h))}
              />
            );
          })}

          {series.map((s) =>
            axes.map((axis, i) => {
              const p = pointFor(i, axes.length, s.values[axis.key] ?? 0);
              return (
                <circle
                  key={`${s.label}-${axis.key}`}
                  cx={p.x}
                  cy={p.y}
                  r={hoveredAxis === i ? 4 : 3}
                  fill={s.color}
                  stroke="var(--panel)"
                  strokeWidth={2}
                />
              );
            }),
          )}

          {centerLabel ? (
            <text
              x={CENTER}
              y={CENTER}
              textAnchor="middle"
              dominantBaseline="middle"
              fontSize={18}
              fontWeight={600}
              fill="var(--text-primary)"
              stroke="var(--panel)"
              strokeWidth={4}
              paintOrder="stroke"
            >
              {centerLabel}
            </text>
          ) : null}
        </svg>
      )}

      {hoveredAxis !== null && !showTable ? (
        <div className="rounded-md border bg-popover px-3 py-2 text-xs">
          <p className="mb-1 font-medium">{axes[hoveredAxis].label}</p>
          {series.map((s) => (
            <p key={s.label} className="flex items-center gap-1.5">
              <span className="inline-block h-2 w-2 rounded-full" style={{ backgroundColor: s.color }} />
              {s.label}: <strong>{((s.values[axes[hoveredAxis].key] ?? 0) * 100).toFixed(0)}%</strong>
            </p>
          ))}
        </div>
      ) : null}
    </div>
  );
}
