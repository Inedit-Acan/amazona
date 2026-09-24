"use client";

import { useMemo, useRef } from "react";
import { Billboard, Html } from "@react-three/drei";
import { Select } from "@react-three/postprocessing";
import { useFrame } from "@react-three/fiber";
import * as THREE from "three";
import type { NodeStatus } from "@/lib/neural-nexus";
import { STATUS_COLOR } from "../nexus-theme";

const FILAMENTS = 18;
const PARTICLES = 260;
/** Achatamiento del elipsoide: el núcleo es una lente, no una bola. */
const FLATTEN = 0.6;

/** Filamentos internos: arcos deterministas dentro del elipsoide, no una maraña
 * aleatoria que cambie en cada render. */
function useFilaments(radius: number) {
  return useMemo(() => {
    const curves: Float32Array[] = [];
    for (let i = 0; i < FILAMENTS; i++) {
      const tilt = (i / FILAMENTS) * Math.PI;
      const yaw = (i * 2.399) % (Math.PI * 2); // ángulo áureo: reparto uniforme
      const points: number[] = [];
      for (let k = 0; k <= 28; k++) {
        const t = (k / 28) * Math.PI * 2;
        const r = radius * (0.55 + 0.22 * Math.sin(t * 2 + i));
        const v = new THREE.Vector3(r * Math.cos(t), r * Math.sin(t) * 0.4, r * Math.sin(t));
        v.applyAxisAngle(new THREE.Vector3(1, 0, 0), tilt);
        v.applyAxisAngle(new THREE.Vector3(0, 1, 0), yaw);
        points.push(v.x, v.y * FLATTEN, v.z);
      }
      curves.push(new Float32Array(points));
    }
    return curves;
  }, [radius]);
}

/** Nube de partículas interna con posiciones deterministas. */
function useParticles(radius: number) {
  return useMemo(() => {
    const positions = new Float32Array(PARTICLES * 3);
    for (let i = 0; i < PARTICLES; i++) {
      const phi = Math.acos(1 - (2 * (i + 0.5)) / PARTICLES);
      const theta = Math.PI * (1 + Math.sqrt(5)) * i;
      const r = radius * (0.3 + 0.62 * ((i % 13) / 13));
      positions[i * 3] = r * Math.sin(phi) * Math.cos(theta);
      positions[i * 3 + 1] = r * Math.cos(phi) * FLATTEN * 0.8;
      positions[i * 3 + 2] = r * Math.sin(phi) * Math.sin(theta);
    }
    return positions;
  }, [radius]);
}

/** Decision Engine (§27): la única pieza con complejidad holográfica de la
 * escena, pero por DETALLE, no por masa luminosa. Capas de baja intensidad
 * combinadas con precisión —núcleo, wireframe, partículas, filamentos y dos
 * anillos de energía finos— y el brillo saliendo de dentro hacia fuera.
 * Pulsación de ±3 %, siempre alrededor del mismo baseline. */
export function DecisionCore({
  radius,
  status,
  animate,
  dimmed,
  selected,
  hovered,
  onSelect,
  onHover,
}: {
  radius: number;
  status: NodeStatus;
  animate: boolean;
  dimmed: boolean;
  selected: boolean;
  hovered: boolean;
  onSelect: () => void;
  onHover: (hovered: boolean) => void;
}) {
  const group = useRef<THREE.Group>(null);
  const wire = useRef<THREE.Mesh>(null);
  const rings = useRef<THREE.Group>(null);
  const inner = useRef<THREE.MeshStandardMaterial>(null);
  const filaments = useFilaments(radius);
  const particles = useParticles(radius);
  const color = STATUS_COLOR[status];
  const fade = dimmed ? 0.22 : 1;
  const active = selected || hovered;

  useFrame(({ clock }) => {
    if (!animate) return;
    const t = clock.elapsedTime;
    // Respiración de ±3 %: se nota que está vivo, no que vibra.
    if (group.current) group.current.scale.setScalar(1 + Math.sin(t * 0.55) * 0.03);
    if (wire.current) wire.current.rotation.y = t * 0.045;
    if (rings.current) rings.current.rotation.y = -t * 0.07;
    if (inner.current) inner.current.emissiveIntensity = (1.5 + Math.sin(t * 0.9) * 0.3 + (active ? 0.6 : 0)) * fade;
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
      {/* Halo suave y CONTENIDO: apenas 1,25 radios, no la mancha de antes. */}
      <mesh scale={[1, FLATTEN, 1]}>
        <sphereGeometry args={[radius * 1.25, 24, 24]} />
        <meshBasicMaterial color={color} transparent opacity={0.035 * fade} depthWrite={false} />
      </mesh>

      {/* Malla neural: wireframe fino, la mayor parte del detalle del núcleo. */}
      <mesh ref={wire} scale={[1, FLATTEN, 1]}>
        <icosahedronGeometry args={[radius, 3]} />
        <meshBasicMaterial color={color} wireframe transparent opacity={0.17 * fade} depthWrite={false} />
      </mesh>

      {/* Filamentos internos */}
      {filaments.map((points, index) => (
        <line key={index}>
          <bufferGeometry>
            <bufferAttribute attach="attributes-position" args={[points, 3]} />
          </bufferGeometry>
          <lineBasicMaterial color={color} transparent opacity={0.12 * fade} depthWrite={false} />
        </line>
      ))}

      {/* Partículas internas */}
      <points>
        <bufferGeometry>
          <bufferAttribute attach="attributes-position" args={[particles, 3]} />
        </bufferGeometry>
        <pointsMaterial color={color} size={0.032} transparent opacity={0.55 * fade} sizeAttenuation depthWrite={false} />
      </points>

      <Select enabled={!dimmed}>
        {/* Núcleo energético: pequeño y brillante. Es el foco de la escena y lo
            único que de verdad ilumina desde dentro. */}
        <mesh scale={[1, FLATTEN, 1]}>
          <sphereGeometry args={[radius * 0.34, 32, 32]} />
          <meshStandardMaterial ref={inner} color={color} emissive={color} emissiveIntensity={1.5} roughness={0.3} />
        </mesh>

        {/* Dos anillos de energía finos */}
        <group ref={rings}>
          {[1.02, 1.16].map((scale, index) => (
            <mesh key={scale} rotation={[Math.PI / 2 + index * 0.3, 0, index * 0.55]}>
              <torusGeometry args={[radius * scale, 0.006, 8, 128]} />
              <meshStandardMaterial color={color} emissive={color} emissiveIntensity={1.1} transparent opacity={0.5 * fade} />
            </mesh>
          ))}
        </group>
      </Select>

      <Billboard position={[0, -radius * FLATTEN - 0.34, 0]}>
        <Html center distanceFactor={10} zIndexRange={[14, 0]} style={{ pointerEvents: "none", opacity: dimmed ? 0.3 : 1 }}>
          <div
            style={{
              color: "#f5f7f7",
              fontSize: 13,
              fontWeight: 700,
              letterSpacing: "0.14em",
              textShadow: "0 1px 3px rgba(0,0,0,0.9)",
              whiteSpace: "nowrap",
            }}
          >
            DECISION ENGINE
          </div>
        </Html>
      </Billboard>
    </group>
  );
}
