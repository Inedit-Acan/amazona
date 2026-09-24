"use client";

import { useMemo, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import * as THREE from "three";
import { LAYOUT } from "@/lib/neural-nexus";
import { EDGE_OPACITY } from "../nexus-theme";

/** Marcas cada 45°, alineadas con los ocho dominios: convierten la órbita en un
 * instrumento de medida en vez de un aro decorativo (§13). */
function ticks(radius: number, height: number): Float32Array {
  const points: number[] = [];
  for (let index = 0; index < 8; index++) {
    const angle = (LAYOUT.startAngleDeg + index * LAYOUT.stepDeg) * (Math.PI / 180);
    const sin = Math.sin(angle);
    const cos = -Math.cos(angle);
    points.push(sin * (radius - 0.09), height, cos * (radius - 0.09), sin * (radius + 0.09), height, cos * (radius + 0.09));
  }
  return new Float32Array(points);
}

/** Órbitas: líneas extremadamente finas y de baja opacidad, guía espacial y nada
 * más. Nunca aros brillantes sólidos (§3.5, §13). La rotación es muy lenta y solo
 * afecta a los aros, jamás a los nodos: la memoria espacial se conserva. */
export function OrbitRings({ animate }: { animate: boolean }) {
  const group = useRef<THREE.Group>(null);
  const rings = useMemo(
    () => [
      { radius: LAYOUT.domainRadius, height: LAYOUT.domainHeight, accent: true },
      { radius: LAYOUT.agentRadius, height: LAYOUT.agentHeight, accent: true },
      { radius: (LAYOUT.domainRadius + LAYOUT.agentRadius) / 2, height: (LAYOUT.domainHeight + LAYOUT.agentHeight) / 2, accent: false },
    ],
    [],
  );
  const domainTicks = useMemo(() => ticks(LAYOUT.domainRadius, LAYOUT.domainHeight), []);

  useFrame(({ clock }) => {
    if (animate && group.current) group.current.rotation.y = clock.elapsedTime * 0.012;
  });

  return (
    <group ref={group}>
      {rings.map((ring) => (
        <mesh key={ring.radius} rotation={[-Math.PI / 2, 0, 0]} position={[0, ring.height, 0]}>
          <ringGeometry args={[ring.radius - 0.004, ring.radius + 0.004, 160]} />
          <meshBasicMaterial
            color="#22c997"
            transparent
            opacity={ring.accent ? EDGE_OPACITY.orbitAccent : EDGE_OPACITY.orbit}
            side={THREE.DoubleSide}
            depthWrite={false}
          />
        </mesh>
      ))}
      <lineSegments>
        <bufferGeometry>
          <bufferAttribute attach="attributes-position" args={[domainTicks, 3]} />
        </bufferGeometry>
        <lineBasicMaterial color="#22c997" transparent opacity={EDGE_OPACITY.orbitAccent} depthWrite={false} />
      </lineSegments>
    </group>
  );
}
