"use client";

import { useMemo, useRef } from "react";
import { Line } from "@react-three/drei";
import { Select } from "@react-three/postprocessing";
import { useFrame } from "@react-three/fiber";
import * as THREE from "three";
import { CEO_ID, CORE_ID, type GraphEdge, type GraphNode } from "@/lib/neural-nexus";
import { EDGE_COLOR, EDGE_OPACITY } from "../nexus-theme";

/** Pocas partículas y pequeñas: enseñar información, no montar un espectáculo
 * (§12). Viajan por la curva, se desvanecen al llegar y vuelven a salir. */
const PARTICLES_PER_EDGE = 2;

function curveBetween(from: [number, number, number], to: [number, number, number]): THREE.QuadraticBezierCurve3 {
  const a = new THREE.Vector3(...from);
  const b = new THREE.Vector3(...to);
  const mid = a.clone().lerp(b, 0.5);
  // Curvatura leve: separa los radios sin convertirlos en arcos teatrales.
  mid.y += a.distanceTo(b) * 0.1;
  return new THREE.QuadraticBezierCurve3(a, mid, b);
}

/** Opacidad base de cada tramo de la jerarquía (§11): el enlace CEO–núcleo es el
 * más claro, el núcleo–dominio fino y el dominio–agente aún más ligero. */
function baseOpacity(edge: GraphEdge, to: GraphNode): number {
  if (edge.type !== "hierarchy") return EDGE_OPACITY.contextual;
  if (edge.source === CEO_ID || edge.target === CEO_ID) return EDGE_OPACITY.ceoToCore;
  if (edge.source === CORE_ID || edge.target === CORE_ID) return EDGE_OPACITY.coreToDomain;
  return to.type === "agent" ? EDGE_OPACITY.domainToAgent : EDGE_OPACITY.coreToDomain;
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
  // Cuando un extremo es el Decision Engine, la conexión no va a su centro: entra
  // por la zona neural que le corresponde a ese dominio (§13.2 y §14).
  const curve = useMemo(
    () =>
      curveBetween(
        edge.source === CORE_ID && edge.anchor ? edge.anchor : from.position,
        edge.target === CORE_ID && edge.anchor ? edge.anchor : to.position,
      ),
    [edge.source, edge.target, edge.anchor, from.position, to.position],
  );
  const points = useMemo(() => curve.getPoints(24), [curve]);
  const particles = useRef<THREE.Group>(null);

  const color = edge.status === "error" ? EDGE_COLOR.incident : edge.status === "warning" ? "#f3b63f" : EDGE_COLOR[edge.type];
  const base = baseOpacity(edge, to);
  const opacity = dimmed
    ? EDGE_OPACITY.dimmed
    : highlighted
      ? Math.min(1, base + 0.45)
      : edge.active
        ? Math.min(EDGE_OPACITY.active, base + 0.3)
        : base;
  const width = edge.type === "hierarchy" && to.type === "agent" ? 0.8 : 1.1;
  const flowing = showParticles && edge.active && animate && !dimmed;

  useFrame(({ clock }) => {
    if (!flowing || !particles.current) return;
    particles.current.children.forEach((child, index) => {
      const t = (clock.elapsedTime * 0.26 + index / PARTICLES_PER_EDGE) % 1;
      const point = curve.getPoint(t);
      child.position.set(point.x, point.y, point.z);
      const material = (child as THREE.Mesh).material as THREE.MeshBasicMaterial;
      // Estela corta: aparece, recorre y se apaga al llegar.
      material.opacity = Math.sin(t * Math.PI) ** 1.5;
    });
  });

  return (
    <group>
      <Line points={points} color={color} lineWidth={highlighted ? width + 0.6 : width} transparent opacity={opacity} />
      {flowing ? (
        <Select enabled>
          <group ref={particles}>
            {Array.from({ length: PARTICLES_PER_EDGE }, (_, index) => (
              <mesh key={index}>
                <sphereGeometry args={[0.042, 8, 8]} />
                <meshBasicMaterial color={color} transparent opacity={0} depthWrite={false} />
              </mesh>
            ))}
          </group>
        </Select>
      ) : null}
    </group>
  );
}
