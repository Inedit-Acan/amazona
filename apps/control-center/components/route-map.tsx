"use client";

import { geoNaturalEarth1, geoPath } from "d3-geo";
import { feature } from "topojson-client";
import type { GeometryCollection, Topology } from "topojson-specification";
import worldTopology from "world-atlas/countries-110m.json";
import { cn } from "@/lib/utils";

export interface MapPoint {
  id: string;
  label: string;
  /** [lon, lat]. */
  lonLat: [number, number];
  /** both = el mismo punto es origen y destino (p. ej. proveedor en la UE con destino UE). */
  kind: "origin" | "destination" | "both";
  /** Estado del punto (Operaciones: normal, retraso, incidencia). Sin tono, el
   * color depende solo de si es origen o destino. */
  tone?: "ok" | "warn" | "bad";
  /** Líneas pequeñas bajo la etiqueta (p. ej. «124 pedidos»). */
  caption?: string[];
}

const TONE_COLOR: Record<"ok" | "warn" | "bad", string> = {
  ok: "var(--emerald-bright)",
  warn: "var(--warning)",
  bad: "var(--danger)",
};

export interface MapRoute {
  id: string;
  /** id del punto de origen. */
  from: string;
  /** id del punto de destino. */
  to: string;
}

const WIDTH = 800;
const HEIGHT = 420;
const ANTARCTICA_ID = "010";

// Geometría de países (Natural Earth, 110m) proyectada una sola vez por módulo.
const projection = geoNaturalEarth1().fitExtent(
  [
    [6, 6],
    [WIDTH - 6, HEIGHT - 6],
  ],
  { type: "Sphere" },
);
const pathGenerator = geoPath(projection);
const topology = worldTopology as unknown as Topology;
const countries = feature(topology, topology.objects.countries as GeometryCollection);
const COUNTRY_PATHS = countries.features
  .filter((f) => String(f.id) !== ANTARCTICA_ID)
  .map((f) => pathGenerator(f))
  .filter((d): d is string => d !== null);

function project(lonLat: [number, number]): [number, number] | null {
  return projection(lonLat);
}

function routePath(from: MapPoint, to: MapPoint): string | null {
  if (from.lonLat[0] === to.lonLat[0] && from.lonLat[1] === to.lonLat[1]) return null;
  return pathGenerator({ type: "LineString", coordinates: [from.lonLat, to.lonLat] });
}

/** Mapa mundial 2.5D con puntos y rutas (§6.6 de la spec de paneles). Es
 * puramente presentacional: dibuja los puntos y rutas que recibe, en las
 * coordenadas que recibe. No conoce proveedores ni decide qué es una ruta. */
export function RouteMap({
  points,
  routes,
  selectedPointId,
  onSelectPoint,
  legend,
  ariaLabel = "Mapa de rutas de abastecimiento",
  className,
}: {
  points: MapPoint[];
  routes: MapRoute[];
  selectedPointId?: string | null;
  onSelectPoint?: (id: string) => void;
  /** Sustituye la leyenda por defecto (origen / ruta / destino). */
  legend?: { color: string; label: string }[];
  ariaLabel?: string;
  className?: string;
}) {
  const byId = new Map(points.map((p) => [p.id, p]));
  const drawn = routes
    .map((route) => {
      const from = byId.get(route.from);
      const to = byId.get(route.to);
      if (!from || !to) return null;
      const d = routePath(from, to);
      return d ? { route, d, selected: route.from === selectedPointId } : null;
    })
    .filter((r): r is { route: MapRoute; d: string; selected: boolean } => r !== null)
    .sort((a, b) => Number(a.selected) - Number(b.selected));

  return (
    <div className={cn("relative", className)}>
      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        className="h-auto w-full"
        role="group"
        aria-label={ariaLabel}
      >
        <g>
          {COUNTRY_PATHS.map((d, i) => (
            <path key={i} d={d} fill="#0a3230" stroke="#16524d" strokeWidth={0.6} />
          ))}
        </g>

        {drawn.map(({ route, d, selected }) => (
          <path
            key={route.id}
            d={d}
            fill="none"
            stroke="var(--emerald-bright)"
            strokeWidth={selected ? 2 : 1.25}
            strokeDasharray="5 4"
            strokeLinecap="round"
            opacity={selected ? 1 : 0.4}
            className={selected ? "drop-shadow-[0_0_4px_var(--emerald)]" : undefined}
          />
        ))}

        {points.map((point) => {
          const xy = project(point.lonLat);
          if (!xy) return null;
          const [x, y] = xy;
          const isDestination = point.kind !== "origin";
          const color = point.tone ? TONE_COLOR[point.tone] : isDestination ? "var(--cyan-accent)" : "var(--emerald-bright)";
          const selected = point.id === selectedPointId;
          const clickable = Boolean(onSelectPoint) && point.kind !== "destination";
          const labelOnLeft = x > WIDTH - 130;
          return (
            <g
              key={point.id}
              role={clickable ? "button" : undefined}
              tabIndex={clickable ? 0 : undefined}
              aria-label={clickable ? `Seleccionar origen ${point.label}` : point.label}
              aria-pressed={clickable ? selected : undefined}
              onClick={clickable ? () => onSelectPoint?.(point.id) : undefined}
              onKeyDown={
                clickable
                  ? (event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        onSelectPoint?.(point.id);
                      }
                    }
                  : undefined
              }
              className={cn(clickable && "cursor-pointer outline-none focus-visible:[&_.halo]:opacity-100")}
            >
              <circle
                className="halo"
                cx={x}
                cy={y}
                r={selected ? 13 : 10}
                fill={color}
                opacity={selected ? 0.35 : 0.18}
              />
              {isDestination ? (
                <circle cx={x} cy={y} r={6.5} fill="var(--panel)" stroke={color} strokeWidth={2.5} />
              ) : (
                <circle cx={x} cy={y} r={5} fill={color} stroke="var(--panel)" strokeWidth={2} />
              )}
              {point.kind === "both" ? <circle cx={x} cy={y} r={2.5} fill="var(--emerald-bright)" /> : null}
              {clickable ? <circle cx={x} cy={y} r={18} fill="transparent" /> : null}
              <text
                x={labelOnLeft ? x - 12 : x + 12}
                y={y + 4}
                textAnchor={labelOnLeft ? "end" : "start"}
                fontSize={12}
                fontWeight={selected ? 600 : 500}
                fill="var(--text-primary)"
                stroke="var(--background)"
                strokeWidth={3}
                paintOrder="stroke"
                pointerEvents="none"
              >
                {point.label}
              </text>
              {(point.caption ?? []).map((line, k) => (
                <text
                  key={line}
                  x={labelOnLeft ? x - 12 : x + 12}
                  y={y + 17 + k * 12}
                  textAnchor={labelOnLeft ? "end" : "start"}
                  fontSize={10}
                  fill="var(--text-secondary)"
                  stroke="var(--background)"
                  strokeWidth={3}
                  paintOrder="stroke"
                  pointerEvents="none"
                >
                  {line}
                </text>
              ))}
            </g>
          );
        })}
      </svg>

      <ul className="pointer-events-none absolute bottom-2 left-2 space-y-1 rounded-md border bg-card/85 px-2.5 py-2 text-[11px] text-muted-foreground backdrop-blur-sm">
        {legend ? (
          legend.map((item) => (
            <li key={item.label} className="flex items-center gap-1.5">
              <span className="size-2 rounded-full" style={{ background: item.color }} /> {item.label}
            </li>
          ))
        ) : (
          <>
        <li className="flex items-center gap-1.5">
          <span className="size-2 rounded-full bg-emerald-bright" /> Origen del proveedor
        </li>
        <li className="flex items-center gap-1.5">
          <span className="w-3.5 border-t border-dashed border-emerald-bright" /> Ruta logística
        </li>
        <li className="flex items-center gap-1.5">
          <span className="size-2 rounded-full border-2 border-cyan-accent" /> Destino
        </li>
          </>
        )}
      </ul>
    </div>
  );
}
