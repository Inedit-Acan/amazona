"use client";

import { useRef } from "react";
import { Html } from "@react-three/drei";
import { useFrame } from "@react-three/fiber";
import type * as THREE from "three";
import type { GraphNode } from "@/lib/neural-nexus";
import { STATUS_GLOW, STATUS_COLOR, NODE_RADIUS } from "../nexus-theme";

/** Un nodo del grafo (CEO, dominio o agente). El núcleo tiene su propio
 * componente. Anillo exterior + esfera, etiqueta siempre visible y halo cuando
 * está seleccionado o en hover — el estado nunca depende solo del color. */
export function NexusNode({
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
  const material = useRef<THREE.MeshStandardMaterial>(null);
  const ring = useRef<THREE.Mesh>(null);
  const radius = NODE_RADIUS[node.type];
  const color = STATUS_COLOR[node.status];
  const base = STATUS_GLOW[node.status];
  const pulsing = node.status === "running" || node.status === "error";
  const opacity = dimmed ? 0.22 : 1;

  useFrame(({ clock }) => {
    if (!material.current) return;
    const pulse = animate && pulsing ? Math.sin(clock.elapsedTime * 2.4) * 0.3 : 0;
    material.current.emissiveIntensity = (base + pulse) * (dimmed ? 0.3 : 1) + (selected || hovered ? 0.6 : 0);
    if (ring.current && animate) ring.current.rotation.z = clock.elapsedTime * (node.type === "ceo" ? 0.35 : 0.2);
  });

  const scale = selected ? 1.25 : hovered ? 1.12 : 1;

  return (
    <group position={node.position} scale={scale}>
      <mesh
        onClick={(event) => {
          event.stopPropagation();
          onSelect();
        }}
        onPointerOver={(event) => {
          event.stopPropagation();
          onHover(true);
        }}
        onPointerOut={() => onHover(false)}
      >
        <sphereGeometry args={[radius, 24, 24]} />
        <meshStandardMaterial
          ref={material}
          color={color}
          emissive={color}
          emissiveIntensity={base}
          transparent
          opacity={opacity}
          roughness={0.3}
          metalness={0.1}
        />
      </mesh>

      {/* Anillo del nodo: refuerza la jerarquía sin depender del tamaño. */}
      <mesh ref={ring} rotation={[Math.PI / 2, 0, 0]}>
        <torusGeometry args={[radius * 1.55, radius * 0.06, 8, 48]} />
        <meshBasicMaterial color={color} transparent opacity={0.45 * opacity} />
      </mesh>

      {selected || hovered ? (
        <mesh>
          <sphereGeometry args={[radius * 2.1, 16, 16]} />
          <meshBasicMaterial color={color} transparent opacity={0.12} depthWrite={false} />
        </mesh>
      ) : null}

      <Html
        position={[0, -(radius + 0.32), 0]}
        center
        distanceFactor={11}
        zIndexRange={[20, 0]}
        style={{ pointerEvents: "none", opacity: dimmed ? 0.35 : 1 }}
      >
        <div
          style={{
            color: node.type === "agent" ? "#9ca9a5" : "#f5f7f7",
            fontSize: node.type === "agent" ? 10 : 12,
            fontWeight: node.type === "agent" ? 500 : 600,
            letterSpacing: node.type === "domain" ? "0.02em" : undefined,
            textShadow: "0 1px 4px rgba(0,0,0,0.9)",
            whiteSpace: "nowrap",
            textAlign: "center",
          }}
        >
          {node.label}
        </div>
      </Html>
    </group>
  );
}
