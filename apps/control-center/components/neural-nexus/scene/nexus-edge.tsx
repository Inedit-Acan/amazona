"use client";

import { useMemo, useRef } from "react";
import { Line } from "@react-three/drei";
import { useFrame } from "@react-three/fiber";
import * as THREE from "three";
import type { GraphEdge, GraphNode } from "@/lib/neural-nexus";
import { EDGE_COLOR } from "../nexus-theme";

/** Partículas que recorren una conexión activa (especificación §12.2). */
const PARTICLES_PER_EDGE = 3;

function curveBetween(from: [number, number, number], to: [number, number, number]): THREE.QuadraticBezierCurve3 {
  const a = new THREE.Vector3(...from);
  const b = new THREE.Vector3(...to);
  const mid = a.clone().lerp(b, 0.5);
  // La curvatura levanta el tramo para que los radios no se solapen en el centro.
  mid.y += a.distanceTo(b) * 0.16;
  return new THREE.QuadraticBezierCurve3(a, mid, b);
}

export function NexusEdge({
  edge,
  from,
  to,
  dimmed,
  highlighted,
  animate,
  showParticles,
}: {
  edge: GraphEdge;
  from: GraphNode;
  to: GraphNode;
  dimmed: boolean;
  highlighted: boolean;
  animate: boolean;
  showParticles: boolean;
}) {
  const curve = useMemo(() => curveBetween(from.position, to.position), [from.position, to.position]);
  const points = useMemo(() => curve.getPoints(28), [curve]);
  const particles = useRef<THREE.Group>(null);

  const color = edge.status === "error" ? EDGE_COLOR.incident : edge.status === "warning" ? "#f3b63f" : EDGE_COLOR[edge.type];
  const base = edge.type === "hierarchy" ? (to.type === "agent" ? 0.14 : 0.26) : 0.5;
  const opacity = dimmed ? base * 0.3 : highlighted ? Math.min(1, base + 0.5) : edge.active ? Math.min(1, base + 0.28) : base;
  const width = edge.type === "hierarchy" ? (to.type === "agent" ? 1 : 1.4) : 1.8;

  const flowing = showParticles && edge.active && animate;

  useFrame(({ clock }) => {
    if (!flowing || !particles.current) return;
    particles.current.children.forEach((child, index) => {
      const t = (clock.elapsedTime * 0.28 + index / PARTICLES_PER_EDGE) % 1;
      const point = curve.getPoint(t);
      child.position.set(point.x, point.y, point.z);
      const material = (child as THREE.Mesh).material as THREE.MeshBasicMaterial;
      // Se desvanece al llegar, para que el recorrido tenga principio y final.
      material.opacity = Math.sin(t * Math.PI) * 0.9;
    });
  });

  return (
    <group>
      <Line points={points} color={color} lineWidth={highlighted ? width + 0.8 : width} transparent opacity={opacity} />
      {flowing ? (
        <group ref={particles}>
          {Array.from({ length: PARTICLES_PER_EDGE }, (_, index) => (
            <mesh key={index}>
              <sphereGeometry args={[0.055, 8, 8]} />
              <meshBasicMaterial color={color} transparent opacity={0.8} />
            </mesh>
          ))}
        </group>
      ) : null}
    </group>
  );
}
