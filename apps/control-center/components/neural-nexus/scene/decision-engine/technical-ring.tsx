"use client";

import { useMemo, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import * as THREE from "three";
import { BRAIN, processingPhase } from "@/lib/decision-engine";
import { ENGINE_COLOR, ENGINE_OPACITY } from "../../nexus-theme";

const TICKS = 24;

/** Marcas del anillo: segmentos radiales cortos, repartidos regularmente. */
function tickSegments(radius: number): Float32Array {
  const points: number[] = [];
  for (let index = 0; index < TICKS; index++) {
    const angle = (index / TICKS) * Math.PI * 2;
    const sin = Math.sin(angle);
    const cos = Math.cos(angle);
    // Una de cada tres marcas es más larga: convierte el aro en una escala.
    const length = index % 3 === 0 ? 0.075 : 0.04;
    points.push(sin * (radius - length), 0, cos * (radius - length), sin * radius, 0, cos * radius);
  }
  return new Float32Array(points);
}

/** Anillo técnico (§9): UNO solo, horizontal, finísimo y con marcas. Es
 * referencia espacial y estado de proceso, no una plataforma de energía: nada de
 * varios aros brillantes ni de toros gruesos (§9.4). Gira muy despacio (§16). */
export function TechnicalRing({ processing, animate, dimmed }: { processing: boolean; animate: boolean; dimmed: boolean }) {
  const group = useRef<THREE.Group>(null);
  const cursor = useRef<THREE.Mesh>(null);
  const ticks = useMemo(() => tickSegments(BRAIN.ringRadius), []);
  const fade = dimmed ? 0.25 : 1;

  useFrame(({ clock }) => {
    if (animate && group.current) group.current.rotation.y = clock.elapsedTime * 0.05;
    if (!cursor.current) return;
    const material = cursor.current.material as THREE.MeshBasicMaterial;
    if (!animate || !processing) {
      material.opacity = 0;
      return;
    }
    // Testigo de proceso: una marca que da la vuelta al ritmo del ciclo.
    const phase = processingPhase(clock.elapsedTime);
    cursor.current.rotation.z = -(clock.elapsedTime / 1.9) * Math.PI * 2;
    material.opacity = (0.35 + phase.core * 0.45) * fade;
  });

  return (
    <group ref={group} position={[0, BRAIN.ringHeight, 0]}>
      <mesh rotation={[-Math.PI / 2, 0, 0]}>
        <ringGeometry args={[BRAIN.ringRadius - 0.004, BRAIN.ringRadius + 0.004, 160]} />
        <meshBasicMaterial
          color={ENGINE_COLOR.ring}
          transparent
          opacity={ENGINE_OPACITY.ring * fade}
          side={THREE.DoubleSide}
          depthWrite={false}
        />
      </mesh>

      <lineSegments>
        <bufferGeometry>
          <bufferAttribute attach="attributes-position" args={[ticks, 3]} />
        </bufferGeometry>
        <lineBasicMaterial color={ENGINE_COLOR.ring} transparent opacity={ENGINE_OPACITY.ringTick * fade} depthWrite={false} />
      </lineSegments>

      <mesh ref={cursor} rotation={[-Math.PI / 2, 0, 0]}>
        <ringGeometry args={[BRAIN.ringRadius - 0.012, BRAIN.ringRadius + 0.012, 48, 1, 0, Math.PI * 0.16]} />
        <meshBasicMaterial
          color={ENGINE_COLOR.synapseActive}
          transparent
          opacity={0}
          side={THREE.DoubleSide}
          depthWrite={false}
        />
      </mesh>
    </group>
  );
}
