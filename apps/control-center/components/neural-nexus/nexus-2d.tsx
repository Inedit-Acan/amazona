"use client";

import { useMemo } from "react";
import { CORE_ID, relatedIds, type GraphEdge, type GraphNode } from "@/lib/neural-nexus";
import { EDGE_COLOR, NODE_RADIUS, STATUS_COLOR } from "./nexus-theme";

/** Vista 2D: mismo dataset y mismas posiciones que la 3D, proyectadas en planta
 * (x, −z). Es la alternativa accesible y el fallback sin WebGL
 * (especificación §30): conserva colores, estados, selección y modos. */
const VIEW = { width: 720, height: 520, scale: 40 };

function project(position: [number, number, number]): { x: number; y: number } {
  return {
    x: VIEW.width / 2 + position[0] * VIEW.scale,
    // La altura del CEO se proyecta hacia arriba para que la jerarquía se lea.
    y: VIEW.height / 2 - position[2] * VIEW.scale - position[1] * VIEW.scale * 0.55,
  };
}

export function Nexus2D({
  nodes,
  edges,
  dimmed,
  selectedId,
  hoveredId,
  onSelect,
  onHover,
}: {
  nodes: GraphNode[];
  edges: GraphEdge[];
  dimmed: Set<string>;
  selectedId: string | null;
  hoveredId: string | null;
  onSelect: (id: string | null) => void;
  onHover: (id: string | null) => void;
}) {
  const byId = useMemo(() => new Map(nodes.map((node) => [node.id, node])), [nodes]);
  const focus = useMemo(() => relatedIds(edges, selectedId), [edges, selectedId]);
  const isDimmed = (id: string) => (selectedId ? !focus.has(id) : dimmed.has(id));

  return (
    <svg
      viewBox={`0 0 ${VIEW.width} ${VIEW.height}`}
      className="h-full w-full"
      role="img"
      aria-label="Grafo de agentes en vista 2D"
      onClick={() => onSelect(null)}
    >
      <rect width={VIEW.width} height={VIEW.height} fill="#030606" />

      {edges.map((edge) => {
        const from = byId.get(edge.source);
        const to = byId.get(edge.target);
        if (!from || !to) return null;
        const a = project(from.position);
        const b = project(to.position);
        const faded = isDimmed(edge.source) || isDimmed(edge.target);
        const color = edge.status === "error" ? EDGE_COLOR.incident : edge.status === "warning" ? "#f3b63f" : EDGE_COLOR[edge.type];
        return (
          <line
            key={edge.id}
            x1={a.x.toFixed(2)}
            y1={a.y.toFixed(2)}
            x2={b.x.toFixed(2)}
            y2={b.y.toFixed(2)}
            stroke={color}
            strokeWidth={edge.type === "hierarchy" ? 1 : 1.6}
            strokeDasharray={edge.type === "dependency" ? "4 4" : undefined}
            opacity={faded ? 0.08 : edge.active ? 0.7 : 0.25}
          />
        );
      })}

      {nodes.map((node) => {
        const { x, y } = project(node.position);
        const radius = (node.id === CORE_ID ? NODE_RADIUS.core * 0.55 : NODE_RADIUS[node.type]) * VIEW.scale;
        const color = STATUS_COLOR[node.status];
        const faded = isDimmed(node.id);
        const active = selectedId === node.id || hoveredId === node.id;
        return (
          <g
            key={node.id}
            transform={`translate(${x.toFixed(2)}, ${y.toFixed(2)})`}
            opacity={faded ? 0.25 : 1}
            style={{ cursor: "pointer" }}
            onClick={(event) => {
              event.stopPropagation();
              onSelect(node.id);
            }}
            onMouseEnter={() => onHover(node.id)}
            onMouseLeave={() => onHover(null)}
          >
            {active ? <circle r={radius * 1.9} fill={color} opacity={0.14} /> : null}
            <circle r={radius} fill="#030606" stroke={color} strokeWidth={node.type === "agent" ? 1.5 : 2} />
            <circle r={radius * 0.45} fill={color} opacity={node.status === "inactive" ? 0.35 : 0.9} />
            <text
              y={radius + 12}
              textAnchor="middle"
              fontSize={node.type === "agent" ? 9 : 11}
              fontWeight={node.type === "agent" ? 500 : 600}
              fill={node.type === "agent" ? "#9ca9a5" : "#f5f7f7"}
            >
              {node.label.length > 26 ? `${node.label.slice(0, 25)}…` : node.label}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
