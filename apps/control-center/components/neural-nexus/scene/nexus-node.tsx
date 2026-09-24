"use client";

import { useRef } from "react";
import { Billboard, Html } from "@react-three/drei";
import { useFrame } from "@react-three/fiber";
import * as THREE from "three";
import type { GraphNode } from "@/lib/neural-nexus";
import { NODE_ICON, NODE_RADIUS, STATUS_COLOR, STATUS_GLOW } from "../nexus-theme";

/** Un nodo del grafo (CEO, dominio o agente). Como en el mockup: un anillo
 * luminoso con el icono dentro, mirando siempre a la cámara —así se lee como un
 * círculo perfecto desde cualquier ángulo—, un punto de estado y la etiqueta
 * debajo. El color nunca va solo: hay icono, punto y texto. */
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
  const halo = useRef<THREE.Mesh>(null);
  const ring = useRef<THREE.Mesh>(null);
  const radius = NODE_RADIUS[node.type];
  const color = STATUS_COLOR[node.status];
  const base = STATUS_GLOW[node.status];
  const pulsing = node.status === "running" || node.status === "error";
  const opacity = dimmed ? 0.18 : 1;
  const Icon = NODE_ICON[node.icon];
  const active = selected || hovered;

  useFrame(({ clock }) => {
    const pulse = animate && pulsing ? (Math.sin(clock.elapsedTime * 2.2) + 1) / 2 : 0;
    if (halo.current) {
      const material = halo.current.material as THREE.MeshBasicMaterial;
      material.opacity = (0.1 + pulse * 0.12 + (active ? 0.16 : 0)) * opacity;
      halo.current.scale.setScalar(1 + pulse * 0.12);
    }
    if (ring.current) {
      const material = ring.current.material as THREE.MeshBasicMaterial;
      // El anillo va por encima de 1 a propósito: es lo que enciende el bloom.
      material.opacity = (base + pulse * 0.45 + (active ? 0.5 : 0)) * opacity;
    }
  });

  return (
    <group position={node.position} scale={active ? 1.16 : 1}>
      <Billboard>
        {/* Halo: lo que el bloom convierte en resplandor. */}
        <mesh ref={halo}>
          <circleGeometry args={[radius * 2.6, 32]} />
          <meshBasicMaterial color={color} transparent opacity={0.1} depthWrite={false} blending={THREE.AdditiveBlending} />
        </mesh>

        {/* Disco interior oscuro: recorta el anillo contra el fondo. */}
        <mesh
          position={[0, 0, 0.001]}
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
          <circleGeometry args={[radius, 48]} />
          <meshBasicMaterial color="#04100e" transparent opacity={0.92 * opacity} />
        </mesh>

        {/* Anillo luminoso */}
        <mesh ref={ring} position={[0, 0, 0.002]}>
          <ringGeometry args={[radius * 0.87, radius, 64]} />
          <meshBasicMaterial color={color} transparent opacity={base * opacity} side={THREE.DoubleSide} />
        </mesh>

        {/* Anillo exterior fino, como en el mockup */}
        <mesh position={[0, 0, 0.002]}>
          <ringGeometry args={[radius * 1.22, radius * 1.26, 64]} />
          <meshBasicMaterial color={color} transparent opacity={0.28 * opacity} side={THREE.DoubleSide} />
        </mesh>

        {/* Punto de estado: el estado no depende solo del color del anillo. */}
        <mesh position={[radius * 0.95, radius * 0.95, 0.003]}>
          <circleGeometry args={[radius * 0.2, 16]} />
          <meshBasicMaterial color={color} transparent opacity={opacity} />
        </mesh>

        {Icon ? (
          <Html center distanceFactor={9} zIndexRange={[12, 0]} style={{ pointerEvents: "none", opacity: dimmed ? 0.3 : 1 }}>
            <Icon size={node.type === "agent" ? 15 : 22} color={color} strokeWidth={1.75} />
          </Html>
        ) : null}
      </Billboard>

      <Html
        position={[0, -(radius + 0.34), 0]}
        center
        distanceFactor={10}
        zIndexRange={[11, 0]}
        style={{ pointerEvents: "none", opacity: dimmed ? 0.3 : 1 }}
      >
        <div
          style={{
            color: node.type === "agent" ? "#cbd6d2" : "#f5f7f7",
            fontSize: node.type === "agent" ? 11 : 13,
            fontWeight: 600,
            letterSpacing: "0.01em",
            textShadow: "0 1px 6px rgba(0,0,0,0.95)",
            maxWidth: node.type === "agent" ? 108 : 150,
            textAlign: "center",
            lineHeight: 1.15,
          }}
        >
          {node.label}
        </div>
      </Html>
    </group>
  );
}
