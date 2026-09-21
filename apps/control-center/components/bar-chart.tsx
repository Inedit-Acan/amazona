"use client";

import { useState } from "react";
import { TableIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

export interface BarDatum {
  key: string;
  label: string;
  value: number;
  /** Patrón "emphasis": la barra destacada va en el acento y el resto en gris. */
  highlight?: boolean;
}

const WIDTH = 360;
const HEIGHT = 190;
const TOP = 26;
const BOTTOM = 30;
const PLOT = HEIGHT - TOP - BOTTOM;
const MAX_BAR = 64;

/** Barra con el extremo de datos redondeado (4 px) y la base recta, anclada a la
 * línea de cero — dataviz: "4px rounded data-end, square at the baseline". */
function barPath(x: number, width: number, zeroY: number, valueY: number): string {
  const r = Math.min(4, width / 2, Math.abs(valueY - zeroY));
  if (valueY <= zeroY) {
    // positiva: sube desde el cero, esquinas superiores redondeadas
    return `M${x},${zeroY} V${valueY + r} Q${x},${valueY} ${x + r},${valueY} H${x + width - r} Q${x + width},${valueY} ${x + width},${valueY + r} V${zeroY} Z`;
  }
  // negativa: baja desde el cero, esquinas inferiores redondeadas
  return `M${x},${zeroY} V${valueY - r} Q${x},${valueY} ${x + r},${valueY} H${x + width - r} Q${x + width},${valueY} ${x + width},${valueY - r} V${zeroY} Z`;
}

/** Gráfico de barras de una sola serie y un solo eje, con soporte de valores
 * negativos, etiqueta del valor en el extremo de cada barra (pocas barras: se
 * etiquetan todas) y vista de tabla accesible (catálogo compartido, §4). */
export function BarChart({
  data,
  formatValue,
  ariaLabel,
  valueHeader = "Valor",
}: {
  data: BarDatum[];
  formatValue: (value: number) => string;
  ariaLabel: string;
  valueHeader?: string;
}) {
  const [showTable, setShowTable] = useState(false);
  const [hovered, setHovered] = useState<string | null>(null);

  if (data.length === 0) return null;

  const max = Math.max(0, ...data.map((d) => d.value));
  const min = Math.min(0, ...data.map((d) => d.value));
  const range = max - min || 1;
  const zeroY = TOP + (max / range) * PLOT;
  const scaleY = (value: number) => TOP + ((max - value) / range) * PLOT;
  const slot = WIDTH / data.length;
  const barWidth = Math.min(MAX_BAR, slot * 0.55);
  const anyHighlight = data.some((d) => d.highlight);

  return (
    <div className="space-y-2">
      <div className="flex justify-end">
        <Button size="sm" variant="ghost" onClick={() => setShowTable((v) => !v)}>
          <TableIcon className="size-3.5" />
          {showTable ? "Ver gráfico" : "Ver tabla"}
        </Button>
      </div>

      {showTable ? (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Categoría</TableHead>
              <TableHead className="text-right">{valueHeader}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.map((d) => (
              <TableRow key={d.key}>
                <TableCell className="text-xs">{d.label}</TableCell>
                <TableCell className="text-right text-xs">{formatValue(d.value)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      ) : (
        <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} className="h-auto w-full" role="img" aria-label={ariaLabel}>
          <line x1={0} x2={WIDTH} y1={zeroY} y2={zeroY} stroke="var(--border)" strokeWidth={1} />
          {data.map((d, i) => {
            const x = slot * i + (slot - barWidth) / 2;
            const valueY = scaleY(d.value);
            const accent = anyHighlight ? d.highlight : true;
            const negative = d.value < 0;
            return (
              <g
                key={d.key}
                onPointerEnter={() => setHovered(d.key)}
                onPointerLeave={() => setHovered((h) => (h === d.key ? null : h))}
              >
                <title>{`${d.label}: ${formatValue(d.value)}`}</title>
                {/* zona de impacto más alta y ancha que la barra visible */}
                <rect x={slot * i} y={0} width={slot} height={HEIGHT} fill="transparent" />
                {Math.abs(valueY - zeroY) > 0.5 ? (
                  <path
                    d={barPath(x, barWidth, zeroY, valueY)}
                    fill={negative ? "var(--danger)" : accent ? "var(--emerald-bright)" : "var(--text-secondary)"}
                    opacity={hovered === d.key ? 1 : accent ? 0.9 : 0.55}
                  />
                ) : null}
                <text
                  x={slot * i + slot / 2}
                  y={negative ? valueY + 14 : valueY - 7}
                  textAnchor="middle"
                  fontSize={12}
                  fontWeight={600}
                  fill="var(--text-primary)"
                >
                  {formatValue(d.value)}
                </text>
                <text x={slot * i + slot / 2} y={HEIGHT - 9} textAnchor="middle" fontSize={11} fill="var(--text-secondary)">
                  {d.label}
                </text>
              </g>
            );
          })}
        </svg>
      )}
    </div>
  );
}
