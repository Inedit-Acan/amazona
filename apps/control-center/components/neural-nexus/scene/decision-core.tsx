"use client";

import { useMemo, useRef } from "react";
import { Billboard, Html } from "@react-three/drei";
import { useFrame } from "@react-three/fiber";
import * as THREE from "three";
import type { NodeStatus } from "@/lib/neural-nexus";
import { STATUS_COLOR } from "../nexus-theme";

const FILAMENTS = 26;
const PARTICLES = 340;

/** Filamentos internos: arcos deterministas dentro del elipsoide, no una maraña
 * aleatoria que cambie en cada render. */
function useFilaments(radius: number) {
  return useMemo(() => {
    const curves: Float32Array[] = [];
    for (let i = 0; i < FILAMENTS; i++) {
      const tilt = (i / FILAMENTS) * Math.PI;
      const yaw = (i * 2.399) % (Math.PI * 2); // ángulo áureo: reparto uniforme
      const points: number[] = [];
      for (let k = 0; k <= 30; k++) {
        const t = (k / 30) * Math.PI * 2;
        const r = radius * (0.58 + 0.24 * Math.sin(t * 2 + i));
        const v = new THREE.Vector3(r * Math.cos(t), r * Math.sin(t) * 0.42, r * Math.sin(t));
        v.applyAxisAngle(new THREE.Vector3(1, 0, 0), tilt);
        v.applyAxisAngle(new THREE.Vector3(0, 1, 0), yaw);
        // El núcleo es un elipsoide achatado, como en el mockup.
        points.push(v.x, v.y * 0.62, v.z);
      }
      curves.push(new Float32Array(points));
    }
    return curves;
  }, [radius]);
}

/** Nube de partículas dentro del núcleo, con posiciones deterministas. */
function useParticles(radius: number) {
  return useMemo(() => {
    const positions = new Float32Array(PARTICLES * 3);
    for (let i = 0; i < PARTICLES; i++) {
      const phi = Math.acos(1 - (2 * (i + 0.5)) / PARTICLES);
      const theta = Math.PI * (1 + Math.sqrt(5)) * i;
      const r = radius * (0.35 + 0.6 * ((i % 11) / 11));
      positions[i * 3] = r * Math.sin(phi) * Math.cos(theta);
      positions[i * 3 + 1] = r * Math.cos(phi) * 0.42;
      positions[i * 3 + 2] = r * Math.sin(phi) * Math.sin(theta);
    }
    return positions;
  }, [radius]);
}

/** Decision Engine: el elemento visual dominante de la escena
 * (especificación §7.1). Elipsoide de malla neural con filamentos, partículas,
 * un disco de luz en el plano del anillo y su nombre escrito dentro — sin
 * cerebro anatómico ni efectos agresivos. */
export function DecisionCore({
  radius,
  status,
  animate,
  dimmed,
  selected,
  onSelect,
  onHover,
}: {
  radius: number;
  status: NodeStatus;
  animate: boolean;
  dimmed: boolean;
  selected: boolean;
  onSelect: () => void;
  onHover: (hovered: boolean) => void;
}) {
  const group = useRef<THREE.Group>(null);
  const shell = useRef<THREE.Mesh>(null);
  const inner = useRef<THREE.Mesh>(null);
  const filaments = useFilaments(radius);
  const particles = useParticles(radius);
  const color = STATUS_COLOR[status];
  const opacity = dimmed ? 0.2 : 1;

  useFrame(({ clock }) => {
    if (!animate) return;
    const t = clock.elapsedTime;
    // Respiración: escala muy leve, nunca una oscilación exagerada.
    if (group.current) group.current.scale.setScalar(1 + Math.sin(t * 0.7) * 0.02);
    if (shell.current) shell.current.rotation.y = t * 0.05;
    if (inner.current) {
      const material = inner.current.material as THREE.MeshBasicMaterial;
      material.opacity = (0.55 + Math.sin(t * 1.1) * 0.18) * opacity;
    }
  });

  return (
    <group
      ref={group}
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
      {/* Disco de luz en el plano del anillo: el resplandor horizontal del mockup. */}
      <mesh rotation={[-Math.PI / 2, 0, 0]}>
        <circleGeometry args={[radius * 2.9, 64]} />
        <meshBasicMaterial color={color} transparent opacity={0.07 * opacity} depthWrite={false} blending={THREE.AdditiveBlending} />
      </mesh>

      {/* Halo esférico */}
      <mesh scale={[1, 0.66, 1]}>
        <sphereGeometry args={[radius * 1.45, 24, 24]} />
        <meshBasicMaterial color={color} transparent opacity={0.06 * opacity} depthWrite={false} blending={THREE.AdditiveBlending} />
      </mesh>

      {/* Malla neural */}
      <mesh ref={shell} scale={[1, 0.66, 1]}>
        <icosahedronGeometry args={[radius, 3]} />
        <meshBasicMaterial color={color} wireframe transparent opacity={0.2 * opacity} />
      </mesh>

      {/* Núcleo energético */}
      <mesh ref={inner} scale={[1, 0.66, 1]}>
        <sphereGeometry args={[radius * 0.5, 32, 32]} />
        <meshBasicMaterial color={color} transparent opacity={0.55 * opacity} blending={THREE.AdditiveBlending} depthWrite={false} />
      </mesh>

      {/* Filamentos internos */}
      {filaments.map((points, index) => (
        <line key={index}>
          <bufferGeometry>
            <bufferAttribute attach="attributes-position" args={[points, 3]} />
          </bufferGeometry>
          <lineBasicMaterial color={color} transparent opacity={0.14 * opacity} blending={THREE.AdditiveBlending} />
        </line>
      ))}

      {/* Partículas */}
      <points>
        <bufferGeometry>
          <bufferAttribute attach="attributes-position" args={[particles, 3]} />
        </bufferGeometry>
        <pointsMaterial color={color} size={0.04} transparent opacity={0.7 * opacity} sizeAttenuation blending={THREE.AdditiveBlending} />
      </points>

      <Billboard position={[0, -radius * 0.82, 0]}>
        <Html center distanceFactor={10} zIndexRange={[14, 0]} style={{ pointerEvents: "none", opacity: dimmed ? 0.3 : 1 }}>
          <div
            style={{
              color: "#f5f7f7",
              fontSize: 15,
              fontWeight: 700,
              letterSpacing: "0.1em",
              textShadow: `0 0 14px ${color}, 0 1px 6px rgba(0,0,0,0.95)`,
              whiteSpace: "nowrap",
              opacity: selected ? 1 : 0.92,
            }}
          >
            DECISION ENGINE
          </div>
        </Html>
      </Billboard>
    </group>
  );
}
