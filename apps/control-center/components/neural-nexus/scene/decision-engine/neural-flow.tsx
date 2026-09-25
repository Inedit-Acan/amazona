"use client";

import { useMemo, useRef } from "react";
import { Line } from "@react-three/drei";
import { Select } from "@react-three/postprocessing";
import { useFrame } from "@react-three/fiber";
import * as THREE from "three";
import { processingPhase } from "@/lib/decision-engine";
import { ENGINE_OPACITY } from "../../nexus-theme";
import type { ActiveRoute } from "./neural-network";

/** Tamaño del testigo que recorre la ruta. Pequeño: informa, no decora (§19). */
const MARKER_RADIUS = 0.028;

/** Rutas neurales activas (§15 y §17): la señal entra por la zona del dominio,
 * recorre la red y converge en el núcleo; después el resultado sale por el mismo
 * camino. Solo se dibujan las rutas de los dominios que están haciendo algo, y
 * el color es el de SU estado —rojo solo en la ruta afectada, nunca en todo el
 * cerebro (§26)—.
 *
 * Es de lo poco que pasa por el bloom selectivo (§21). */
export function NeuralFlow({ routes, animate, dimmed }: { routes: ActiveRoute[]; animate: boolean; dimmed: boolean }) {
  const curves = useMemo(
    () =>
      routes.map(({ route, color }) => ({
        color,
        curve: new THREE.CatmullRomCurve3(route.path.map((point) => new THREE.Vector3(...point))),
      })),
    [routes],
  );
  const markers = useRef<THREE.Group>(null);

  useFrame(({ clock }) => {
    if (!markers.current) return;
    const phase = animate ? processingPhase(clock.elapsedTime) : null;
    // Entrada de la zona al núcleo; salida del núcleo a la zona.
    const reach = phase ? (phase.signal ?? (phase.output === null ? null : 1 - phase.output)) : null;
    markers.current.children.forEach((child, index) => {
      const material = (child as THREE.Mesh).material as THREE.MeshBasicMaterial;
      if (reach === null || dimmed) {
        material.opacity = 0;
        return;
      }
      const point = curves[index]?.curve.getPoint(reach);
      if (!point) return;
      child.position.copy(point);
      // Aparece, recorre y se apaga: siempre vuelve a cero al cerrar el ciclo.
      material.opacity = Math.sin(reach * Math.PI) ** 0.6;
    });
  });

  if (routes.length === 0) return null;

  return (
    <Select enabled={!dimmed}>
      <group renderOrder={5}>
        {curves.map(({ curve, color }, index) => (
          <Line
            key={index}
            points={curve.getPoints(32)}
            color={color}
            lineWidth={1.2}
            transparent
            opacity={(dimmed ? 0.1 : ENGINE_OPACITY.route) * 0.55}
            depthWrite={false}
          />
        ))}
        <group ref={markers}>
          {curves.map(({ color }, index) => (
            <mesh key={index}>
              <sphereGeometry args={[MARKER_RADIUS, 8, 8]} />
              <meshBasicMaterial color={color} transparent opacity={0} depthWrite={false} />
            </mesh>
          ))}
        </group>
      </group>
    </Select>
  );
}
