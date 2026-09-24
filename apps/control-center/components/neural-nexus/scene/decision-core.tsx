"use client";

import { useMemo, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import * as THREE from "three";
import type { NodeStatus } from "@/lib/neural-nexus";
import { STATUS_COLOR } from "../nexus-theme";

const FILAMENTS = 14;
const PARTICLES = 220;

/** Filamentos internos: arcos deterministas dentro de la esfera, no una maraña
 * aleatoria que cambie en cada render. */
function useFilaments(radius: number) {
  return useMemo(() => {
    const curves: THREE.Vector3[][] = [];
    for (let i = 0; i < FILAMENTS; i++) {
      const tilt = (i / FILAMENTS) * Math.PI;
      const yaw = (i * 2.399) % (Math.PI * 2); // ángulo áureo: reparto uniforme
      const points: THREE.Vector3[] = [];
      for (let k = 0; k <= 24; k++) {
        const t = (k / 24) * Math.PI * 2;
        const r = radius * (0.62 + 0.2 * Math.sin(t * 2 + i));
        const v = new THREE.Vector3(r * Math.cos(t), r * Math.sin(t) * 0.35, r * Math.sin(t));
        v.applyAxisAngle(new THREE.Vector3(1, 0, 0), tilt);
        v.applyAxisAngle(new THREE.Vector3(0, 1, 0), yaw);
        points.push(v);
      }
      curves.push(points);
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
      const r = radius * (0.45 + 0.5 * ((i % 7) / 7));
      positions[i * 3] = r * Math.sin(phi) * Math.cos(theta);
      positions[i * 3 + 1] = r * Math.cos(phi) * 0.55;
      positions[i * 3 + 2] = r * Math.sin(phi) * Math.sin(theta);
    }
    return positions;
  }, [radius]);
}

/** Decision Engine: el elemento visual dominante de la escena
 * (especificación §7.1). Malla neural, filamentos, partículas, anillos y una
 * pulsación lenta — sin cerebro anatómico ni efectos agresivos. */
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
  const rings = useRef<THREE.Group>(null);
  const filaments = useFilaments(radius);
  const particles = useParticles(radius);
  const color = STATUS_COLOR[status];
  const opacity = dimmed ? 0.25 : 1;

  useFrame(({ clock }) => {
    if (!animate) return;
    const t = clock.elapsedTime;
    // Respiración: escala muy leve, nunca una oscilación exagerada.
    const breath = 1 + Math.sin(t * 0.7) * 0.022;
    if (group.current) group.current.scale.setScalar(breath);
    if (shell.current) {
      shell.current.rotation.y = t * 0.06;
      shell.current.rotation.x = Math.sin(t * 0.15) * 0.12;
    }
    if (rings.current) rings.current.rotation.y = -t * 0.09;
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
      {/* Halo exterior */}
      <mesh>
        <sphereGeometry args={[radius * 1.5, 24, 24]} />
        <meshBasicMaterial color={color} transparent opacity={0.05 * opacity} depthWrite={false} />
      </mesh>

      {/* Malla neural */}
      <mesh ref={shell}>
        <icosahedronGeometry args={[radius, 2]} />
        <meshBasicMaterial color={color} wireframe transparent opacity={0.22 * opacity} />
      </mesh>

      {/* Núcleo energético */}
      <mesh>
        <sphereGeometry args={[radius * 0.42, 32, 32]} />
        <meshStandardMaterial
          color={color}
          emissive={color}
          emissiveIntensity={selected ? 2.2 : 1.5}
          transparent
          opacity={0.9 * opacity}
          roughness={0.2}
        />
      </mesh>

      {/* Filamentos internos */}
      {filaments.map((points, index) => (
        <line key={index}>
          <bufferGeometry>
            <bufferAttribute attach="attributes-position" args={[new Float32Array(points.flatMap((p) => [p.x, p.y, p.z])), 3]} />
          </bufferGeometry>
          <lineBasicMaterial color={color} transparent opacity={0.16 * opacity} />
        </line>
      ))}

      {/* Partículas */}
      <points>
        <bufferGeometry>
          <bufferAttribute attach="attributes-position" args={[particles, 3]} />
        </bufferGeometry>
        <pointsMaterial color={color} size={0.035} transparent opacity={0.55 * opacity} sizeAttenuation />
      </points>

      {/* Anillos internos */}
      <group ref={rings}>
        {[1.05, 1.22].map((scale, index) => (
          <mesh key={scale} rotation={[Math.PI / 2 + index * 0.35, 0, index * 0.6]}>
            <torusGeometry args={[radius * scale, 0.008, 8, 96]} />
            <meshBasicMaterial color={color} transparent opacity={0.35 * opacity} />
          </mesh>
        ))}
      </group>
    </group>
  );
}
