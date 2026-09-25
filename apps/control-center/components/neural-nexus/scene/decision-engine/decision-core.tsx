"use client";

import { useRef } from "react";
import { Billboard } from "@react-three/drei";
import { Select } from "@react-three/postprocessing";
import { useFrame, type ThreeEvent } from "@react-three/fiber";
import type * as THREE from "three";
import { BRAIN, processingPhase } from "@/lib/decision-engine";
import { ENGINE_COLOR, ENGINE_OPACITY } from "../../nexus-theme";

/** Núcleo geométrico de decisión (§8). Es el elemento más importante de la
 * escena y el único con glow relevante, pero pequeño: un poliedro facetado del
 * 18 % del ancho del cerebro, nunca una esfera. El halo es mínimo y de caída
 * corta, para separarlo del fondo sin cubrir el cerebro (§8.6 y §10).
 *
 * Mientras procesa sube de intensidad y al decidir emite un pulso de ±3 % de
 * escala (§15.3), siempre alrededor del mismo baseline. */
export function DecisionCore({
  color,
  processing,
  animate,
  dimmed,
  selected,
  hovered,
  onSelect,
  onHover,
}: {
  color: string;
  /** Hay trabajo en curso: el núcleo sigue la secuencia de §17. */
  processing: boolean;
  animate: boolean;
  dimmed: boolean;
  selected: boolean;
  hovered: boolean;
  onSelect: () => void;
  onHover: (hovered: boolean) => void;
}) {
  const group = useRef<THREE.Group>(null);
  const crystal = useRef<THREE.MeshStandardMaterial>(null);
  const halo = useRef<THREE.MeshBasicMaterial>(null);
  const active = selected || hovered;
  const fade = dimmed ? 0.3 : 1;

  useFrame(({ clock }) => {
    const elapsed = clock.elapsedTime;
    const phase = animate && processing ? processingPhase(elapsed) : null;
    // En reposo, respiración mínima; procesando, la secuencia de §17. Las dos
    // son ondas alrededor de un baseline: ningún valor decae para siempre.
    const breathing = animate ? (Math.sin(elapsed * 0.6) + 1) / 2 : 0.5;
    const level = 0.58 + breathing * 0.14 + (phase ? phase.core * 0.9 + phase.pulse * 0.6 : 0) + (active ? 0.5 : 0);

    if (crystal.current) crystal.current.emissiveIntensity = level * fade;
    if (halo.current) halo.current.opacity = (ENGINE_OPACITY.halo + (phase?.pulse ?? 0) * 0.05 + (active ? 0.03 : 0)) * fade;
    if (group.current) {
      if (animate) group.current.rotation.y = elapsed * 0.13;
      group.current.rotation.x = 0.28;
      group.current.scale.setScalar(1 + (phase?.pulse ?? 0) * 0.03 + (selected ? 0.05 : 0));
    }
  });

  const pick = (event: ThreeEvent<MouseEvent>) => {
    event.stopPropagation();
    onSelect();
  };

  return (
    <group ref={group} renderOrder={3}>
      {/* Halo: mínimo, de caída corta y muy por dentro del cerebro (§10). */}
      <Billboard>
        <mesh renderOrder={3}>
          <circleGeometry args={[BRAIN.coreRadius * 1.7, 32]} />
          <meshBasicMaterial ref={halo} color={color} transparent opacity={ENGINE_OPACITY.halo} depthWrite={false} />
        </mesh>
      </Billboard>

      <Select enabled={!dimmed}>
        {/* Poliedro facetado: cristalino, preciso y nítido (§8.5). */}
        <mesh
          renderOrder={4}
          onClick={pick}
          onPointerOver={(event) => {
            event.stopPropagation();
            onHover(true);
          }}
          onPointerOut={() => onHover(false)}
        >
          <icosahedronGeometry args={[BRAIN.coreRadius, 0]} />
          <meshStandardMaterial
            ref={crystal}
            color={ENGINE_COLOR.coreCenter}
            emissive={color}
            emissiveIntensity={0.62}
            roughness={0.12}
            metalness={0.2}
            flatShading
          />
        </mesh>

        {/* Arista exterior: marca las facetas sin añadir masa luminosa. */}
        <mesh renderOrder={4}>
          <icosahedronGeometry args={[BRAIN.coreRadius * 1.24, 0]} />
          <meshBasicMaterial color={color} wireframe transparent opacity={0.3 * fade} depthWrite={false} />
        </mesh>
      </Select>
    </group>
  );
}
