"use client";

import { useMemo, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import * as THREE from "three";
import {
  SYNAPSE_SIZE,
  neuralMesh,
  processingPhase,
  type Hemisphere,
  type NeuralRoute,
} from "@/lib/decision-engine";
import { ENGINE_COLOR, ENGINE_OPACITY } from "../../nexus-theme";

const WIRE = new THREE.Color(ENGINE_COLOR.wireframe);
const SYNAPSE = new THREE.Color(ENGINE_COLOR.synapse);
/** La red y los nodos no se pueden pinchar: la selección va por el casco y por
 * el núcleo, y así el raycaster tampoco los recorre en cada frame. */
const NO_RAYCAST = () => {};
/** Anchura del frente de activación a lo largo de la ruta. */
const WAVE = 0.3;

export interface ActiveRoute {
  route: NeuralRoute;
  color: THREE.Color;
}

/** Red neural y nodos sinápticos de un hemisferio (§6 y §7).
 *
 * La red es lo que define el cerebro y existe aunque no haya glow (§6.1). Solo
 * se dibujan los enlaces que entran en la densidad pedida —30–40 % en reposo,
 * 45–65 % ejecutando (§6.3)—, así que un enlace apagado no es una línea negra:
 * sencillamente no está en la geometría. La malla se construye una vez por
 * densidad y no se toca por frame (§29).
 *
 * La activación NUNCA es un parpadeo aleatorio (§7.4): un frente recorre las
 * rutas de los dominios que están haciendo algo y enciende los nodos por los que
 * pasa, siempre alrededor de su intensidad de reposo (§31). */
export function NeuralNetwork({
  side,
  density,
  routes,
  animate,
  dimmed,
}: {
  side: Hemisphere;
  density: number;
  routes: ActiveRoute[];
  animate: boolean;
  dimmed: boolean;
}) {
  const mesh = useMemo(() => neuralMesh(side), [side]);

  // Enlaces visibles a esta densidad, con su color ya calculado: los del borde
  // de la densidad entran más tenues, así que cambiar de estado no los enciende
  // de golpe.
  const links = useMemo(() => {
    const visible: number[] = [];
    for (let index = 0; index < mesh.linkThreshold.length; index++) {
      if (mesh.linkThreshold[index] < density) visible.push(index);
    }
    const positions = new Float32Array(visible.length * 6);
    const colors = new Float32Array(visible.length * 6);
    visible.forEach((link, slot) => {
      const level = 0.45 + 0.55 * (1 - mesh.linkThreshold[link] / density);
      for (let end = 0; end < 2; end++) {
        const point = mesh.links[link * 2 + end];
        const offset = slot * 6 + end * 3;
        positions[offset] = mesh.points[point * 3];
        positions[offset + 1] = mesh.points[point * 3 + 1];
        positions[offset + 2] = mesh.points[point * 3 + 2];
        colors[offset] = WIRE.r * level;
        colors[offset + 1] = WIRE.g * level;
        colors[offset + 2] = WIRE.b * level;
      }
    });
    return { positions, colors };
  }, [mesh, density]);

  // Intensidad de reposo de cada nodo: algunos quedan casi apagados (§7.3).
  const base = useMemo(() => {
    const colors = new Float32Array(mesh.pointBase.length * 3);
    for (let index = 0; index < mesh.pointBase.length; index++) {
      const level = Math.max(0.05, mesh.pointBase[index]);
      colors[index * 3] = SYNAPSE.r * level;
      colors[index * 3 + 1] = SYNAPSE.g * level;
      colors[index * 3 + 2] = SYNAPSE.b * level;
    }
    return colors;
  }, [mesh]);

  const live = useMemo(() => Float32Array.from(base), [base]);
  const colorAttribute = useRef<THREE.BufferAttribute>(null);
  const lit = useRef<number[]>([]);

  useFrame(({ clock }) => {
    const attribute = colorAttribute.current;
    if (!attribute) return;
    const array = attribute.array as Float32Array;

    // Primero se devuelve al baseline lo que se encendió en el frame anterior:
    // la intensidad se restaura siempre, nunca se arrastra (§31).
    let changed = lit.current.length > 0;
    for (const index of lit.current) {
      array[index * 3] = base[index * 3];
      array[index * 3 + 1] = base[index * 3 + 1];
      array[index * 3 + 2] = base[index * 3 + 2];
    }
    lit.current.length = 0;

    if (animate && routes.length > 0) {
      const phase = processingPhase(clock.elapsedTime);
      // La señal entra de la zona al núcleo y el resultado sale al revés (§15).
      const reach = phase.signal ?? (phase.output === null ? null : 1 - phase.output);
      if (reach !== null) {
        for (const { route, color } of routes) {
          if (route.side !== side) continue;
          const steps = route.synapses.length + 1;
          route.synapses.forEach((index, step) => {
            const distance = Math.abs(reach - (step + 1) / steps);
            if (distance >= WAVE) return;
            const strength = (1 - distance / WAVE) ** 2;
            array[index * 3] = base[index * 3] + (color.r - base[index * 3]) * strength;
            array[index * 3 + 1] = base[index * 3 + 1] + (color.g - base[index * 3 + 1]) * strength;
            array[index * 3 + 2] = base[index * 3 + 2] + (color.b - base[index * 3 + 2]) * strength;
            lit.current.push(index);
            changed = true;
          });
        }
      }
    }

    if (changed) attribute.needsUpdate = true;
  });

  const fade = dimmed ? 0.22 : 1;

  return (
    <group>
      <lineSegments renderOrder={1} raycast={NO_RAYCAST}>
        <bufferGeometry>
          <bufferAttribute attach="attributes-position" args={[links.positions, 3]} />
          <bufferAttribute attach="attributes-color" args={[links.colors, 3]} />
        </bufferGeometry>
        {/* Línea muy fina y por debajo de los nodos en protagonismo (§6.4). */}
        <lineBasicMaterial vertexColors transparent opacity={ENGINE_OPACITY.link * fade} depthWrite={false} />
      </lineSegments>

      <points renderOrder={2} raycast={NO_RAYCAST}>
        <bufferGeometry>
          <bufferAttribute attach="attributes-position" args={[mesh.points, 3]} />
          <bufferAttribute ref={colorAttribute} attach="attributes-color" args={[live, 3]} />
        </bufferGeometry>
        <pointsMaterial
          vertexColors
          size={SYNAPSE_SIZE}
          sizeAttenuation
          transparent
          opacity={ENGINE_OPACITY.synapse * fade}
          depthWrite={false}
        />
      </points>
    </group>
  );
}
