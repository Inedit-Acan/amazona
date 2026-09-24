"use client";

import { useRef } from "react";
import { Billboard, Html } from "@react-three/drei";
import { Select } from "@react-three/postprocessing";
import { useFrame, type ThreeEvent } from "@react-three/fiber";
import type * as THREE from "three";
import type { GraphNode } from "@/lib/neural-nexus";
import {
  NODE_ICON,
  NODE_RADIUS,
  NODE_SURFACE,
  STATUS_BLOOMS,
  STATUS_COLOR,
  STATUS_EMISSIVE,
  STATUS_RING_OPACITY,
} from "../nexus-theme";

/** Distancia de cámara por debajo de la cual se leen las etiquetas de agente
 * (§3.8: los agentes se ven según zoom u hover; dominios y CEO, siempre). */
const AGENT_LABEL_DISTANCE = 17;

/** Nodo de precisión (§26): superficie oscura, anillo fino, anillo interior,
 * icono, punto de estado y un microhalo — nunca un disco de glow grande. Mira
 * siempre a la cámara, así que se lee como un círculo exacto desde cualquier
 * ángulo. Es la pieza común de CEO, dominios y agentes: lo único que cambia es
 * el tamaño, el grosor del borde y si su etiqueta está siempre visible. */
export function PrecisionNode({
  node,
  dimmed,
  selected,
  hovered,
  animate,
  onSelect,
  onHover,
}: {
  node: GraphNode;
  dimmed: boolean;
  selected: boolean;
  hovered: boolean;
  animate: boolean;
  onSelect: () => void;
  onHover: (hovered: boolean) => void;
}) {
  const halo = useRef<THREE.Mesh>(null);
  const ring = useRef<THREE.MeshStandardMaterial>(null);
  const group = useRef<THREE.Group>(null);
  const label = useRef<HTMLDivElement>(null);

  const radius = NODE_RADIUS[node.type];
  const color = STATUS_COLOR[node.status];
  const emissive = STATUS_EMISSIVE[node.status];
  const ringOpacity = STATUS_RING_OPACITY[node.status];
  const isAgent = node.type === "agent";
  // Los dominios y el CEO llevan el borde más grueso: la jerarquía también se
  // lee en el trazo, no solo en el tamaño (§5.4).
  const ringWidth = isAgent ? 0.055 : 0.08;
  const active = selected || hovered;
  const pulses = node.status === "running" || node.status === "error" || node.status === "waiting";
  const blooms = STATUS_BLOOMS[node.status] || node.type === "ceo" || active;

  useFrame(({ clock, camera }) => {
    // Animación periódica alrededor de un baseline: nunca un decaimiento
    // multiplicativo, que es lo que hacía que la escena se «apagara» (§20).
    const wave = animate && pulses ? (Math.sin(clock.elapsedTime * (node.status === "waiting" ? 1.1 : 2.2)) + 1) / 2 : 0;
    const fade = dimmed ? 0.28 : 1;

    if (ring.current) {
      ring.current.emissiveIntensity = (emissive + wave * 0.35 + (active ? 0.5 : 0)) * fade;
      ring.current.opacity = ringOpacity * fade;
    }
    if (halo.current) {
      const material = halo.current.material as THREE.MeshBasicMaterial;
      // Microhalo: solo cuando el nodo está haciendo algo o tiene el foco.
      material.opacity = (blooms ? 0.055 + wave * 0.05 : 0) + (active ? 0.09 : 0);
    }
    if (group.current) {
      const scale = selected ? 1.18 : hovered ? 1.09 : 1;
      group.current.scale.setScalar(scale);
    }
    if (label.current) {
      const visible = !isAgent || active || camera.position.length() < AGENT_LABEL_DISTANCE;
      label.current.style.opacity = String(visible ? (dimmed ? 0.3 : 1) : 0);
    }
  });

  const pick = (event: ThreeEvent<MouseEvent>) => {
    event.stopPropagation();
    onSelect();
  };
  const enter = (event: ThreeEvent<PointerEvent>) => {
    event.stopPropagation();
    onHover(true);
  };

  const Icon = NODE_ICON[node.icon];

  return (
    <group ref={group} position={node.position}>
      <Billboard>
        {/* Microhalo, pequeño y casi invisible en reposo. */}
        <mesh ref={halo}>
          <circleGeometry args={[radius * 1.5, 32]} />
          <meshBasicMaterial color={color} transparent opacity={0} depthWrite={false} />
        </mesh>

        {/* Superficie: oscura y opaca, recorta el nodo contra el fondo. */}
        <mesh position={[0, 0, 0.002]} onClick={pick} onPointerOver={enter} onPointerOut={() => onHover(false)}>
          <circleGeometry args={[radius, 48]} />
          <meshStandardMaterial
            color={NODE_SURFACE}
            emissive={color}
            emissiveIntensity={dimmed ? 0.02 : 0.06}
            roughness={0.85}
            metalness={0.1}
          />
        </mesh>

        <Select enabled={blooms && !dimmed}>
          {/* Anillo principal */}
          <mesh position={[0, 0, 0.004]}>
            <ringGeometry args={[radius - ringWidth, radius, 64]} />
            <meshStandardMaterial
              ref={ring}
              color={color}
              emissive={color}
              emissiveIntensity={emissive}
              transparent
              opacity={ringOpacity}
              roughness={0.5}
            />
          </mesh>
        </Select>

        {/* Anillo secundario, más fino y apagado: da la sensación de pieza
            mecanizada sin añadir masa luminosa. */}
        <mesh position={[0, 0, 0.003]}>
          <ringGeometry args={[radius * 1.2, radius * 1.22, 64]} />
          <meshBasicMaterial color={color} transparent opacity={(dimmed ? 0.06 : 0.22) * (isAgent ? 0.7 : 1)} depthWrite={false} />
        </mesh>

        {/* Punto de estado: el estado no depende solo del color del anillo. */}
        <mesh position={[radius * 0.78, radius * 0.78, 0.005]}>
          <circleGeometry args={[radius * 0.17, 16]} />
          <meshBasicMaterial color={color} transparent opacity={dimmed ? 0.3 : 1} />
        </mesh>

        {Icon ? (
          <Html center distanceFactor={9} zIndexRange={[12, 0]} style={{ pointerEvents: "none", opacity: dimmed ? 0.3 : 0.92 }}>
            <Icon size={isAgent ? 14 : node.type === "ceo" ? 22 : 18} color={color} strokeWidth={1.6} />
          </Html>
        ) : null}
      </Billboard>

      <Html
        position={[0, -(radius + 0.3), 0]}
        center
        distanceFactor={10}
        zIndexRange={[11, 0]}
        style={{ pointerEvents: "none" }}
      >
        <div
          ref={label}
          style={{
            // Sin glow en el texto (§15): blanco roto para lo principal, gris
            // frío para los agentes, y una sombra muy suave que lo despega.
            color: isAgent ? "#9ca9a5" : "#f5f7f7",
            fontSize: isAgent ? 10.5 : node.type === "ceo" ? 13 : 12,
            fontWeight: isAgent ? 500 : 600,
            letterSpacing: "0.01em",
            textShadow: "0 1px 3px rgba(0,0,0,0.9)",
            maxWidth: isAgent ? 104 : 148,
            textAlign: "center",
            lineHeight: 1.15,
            transition: "opacity 160ms linear",
          }}
        >
          {node.label}
        </div>
      </Html>
    </group>
  );
}
