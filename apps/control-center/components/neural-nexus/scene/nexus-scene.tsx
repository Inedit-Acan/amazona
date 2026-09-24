"use client";

import { useEffect, useMemo, useRef, type ComponentRef, type RefObject } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import { OrbitControls } from "@react-three/drei";
import { EffectComposer, SelectiveBloom, Selection, Vignette } from "@react-three/postprocessing";
import * as THREE from "three";
import { CORE_ID, LAYOUT, relatedIds, type GraphEdge, type GraphMode, type GraphNode } from "@/lib/neural-nexus";
import { NODE_RADIUS } from "../nexus-theme";
import { DecisionCore } from "./decision-core";
import { NexusEdge } from "./nexus-edge";
import { NexusLighting } from "./nexus-lighting";
import { OrbitRings } from "./orbit-rings";
import { PrecisionNode } from "./precision-node";

const AMBIENT_PARTICLES = 90;
/** Vista inicial: el CEO entero arriba, el núcleo centrado, el anillo de
 * dominios bien separado y los agentes dentro de cuadro, con margen y sin una
 * inclinación que comprima la escena (§10). */
const CAMERA_HOME: [number, number, number] = [0, 5.6, 13.6];

/** Polvo ambiental: muy pocas partículas y muy tenues, solo para que el fondo
 * no sea un vacío plano. */
function AmbientParticles({ animate }: { animate: boolean }) {
  const points = useRef<THREE.Points>(null);
  const positions = useMemo(() => {
    const array = new Float32Array(AMBIENT_PARTICLES * 3);
    for (let i = 0; i < AMBIENT_PARTICLES; i++) {
      const phi = Math.acos(1 - (2 * (i + 0.5)) / AMBIENT_PARTICLES);
      const theta = Math.PI * (1 + Math.sqrt(5)) * i;
      const r = 10 + (i % 5) * 1.7;
      array[i * 3] = r * Math.sin(phi) * Math.cos(theta);
      array[i * 3 + 1] = r * Math.cos(phi) * 0.45;
      array[i * 3 + 2] = r * Math.sin(phi) * Math.sin(theta);
    }
    return array;
  }, []);

  useFrame(({ clock }) => {
    if (animate && points.current) points.current.rotation.y = clock.elapsedTime * 0.008;
  });

  return (
    <points ref={points}>
      <bufferGeometry>
        <bufferAttribute attach="attributes-position" args={[positions, 3]} />
      </bufferGeometry>
      <pointsMaterial color="#22c997" size={0.028} transparent opacity={0.22} sizeAttenuation depthWrite={false} />
    </points>
  );
}

type Controls = ComponentRef<typeof OrbitControls>;

function CameraRig({ resetToken, controls }: { resetToken: number; controls: RefObject<Controls | null> }) {
  useEffect(() => {
    controls.current?.reset();
  }, [resetToken, controls]);
  return null;
}

export function NexusScene({
  nodes,
  edges,
  mode,
  dimmed,
  selectedId,
  hoveredId,
  animate,
  resetToken,
  onSelect,
  onHover,
}: {
  nodes: GraphNode[];
  edges: GraphEdge[];
  mode: GraphMode;
  dimmed: Set<string>;
  selectedId: string | null;
  hoveredId: string | null;
  animate: boolean;
  resetToken: number;
  onSelect: (id: string | null) => void;
  onHover: (id: string | null) => void;
}) {
  const controls = useRef<Controls>(null);
  const byId = useMemo(() => new Map(nodes.map((node) => [node.id, node])), [nodes]);
  const focus = useMemo(() => relatedIds(edges, selectedId), [edges, selectedId]);
  const showParticles = mode !== "architecture";

  // Al seleccionar, lo no relacionado se atenúa; si no hay selección manda el modo.
  const isDimmed = (id: string) => (selectedId ? !focus.has(id) : dimmed.has(id));

  // Las conexiones cruzadas están ocultas por defecto (§3.6): salen en Ejecución
  // e Incidencias, y también al seleccionar un nodo, pero solo las suyas.
  const visible = useMemo(
    () =>
      edges.filter((edge) => {
        if (edge.type === "hierarchy") return true;
        if (mode !== "architecture") return true;
        return selectedId !== null && (edge.source === selectedId || edge.target === selectedId);
      }),
    [edges, mode, selectedId],
  );

  return (
    <Canvas
      camera={{ position: CAMERA_HOME, fov: 40 }}
      dpr={[1, 1.75]}
      onPointerMissed={() => onSelect(null)}
      // Exposición y espacio de color fijados a mano: nada los toca en marcha,
      // así que la escena no se oscurece con el tiempo (§21).
      gl={{ antialias: true, toneMapping: THREE.ACESFilmicToneMapping, toneMappingExposure: 1, outputColorSpace: THREE.SRGBColorSpace }}
    >
      <color attach="background" args={["#030606"]} />
      {/* Fog mínimo y lejano: la profundidad la dan la posición y la luz, no la
          neblina (§29). */}
      <fog attach="fog" args={["#030606", 24, 46]} />

      <Selection>
        <NexusLighting />
        <AmbientParticles animate={animate} />
        <OrbitRings animate={animate} />

        {visible.map((edge) => {
          const from = byId.get(edge.source);
          const to = byId.get(edge.target);
          if (!from || !to) return null;
          const related = selectedId !== null && focus.has(edge.source) && focus.has(edge.target);
          return (
            <NexusEdge
              key={edge.id}
              edge={edge}
              from={from}
              to={to}
              dimmed={isDimmed(edge.source) || isDimmed(edge.target)}
              highlighted={related}
              animate={animate}
              showParticles={showParticles}
            />
          );
        })}

        {nodes.map((node) =>
          node.id === CORE_ID ? (
            <DecisionCore
              key={node.id}
              radius={NODE_RADIUS.core}
              status={node.status}
              animate={animate}
              dimmed={isDimmed(node.id)}
              selected={selectedId === node.id}
              hovered={hoveredId === node.id}
              onSelect={() => onSelect(node.id)}
              onHover={(hovered) => onHover(hovered ? node.id : null)}
            />
          ) : (
            <PrecisionNode
              key={node.id}
              node={node}
              dimmed={isDimmed(node.id)}
              selected={selectedId === node.id}
              hovered={hoveredId === node.id}
              animate={animate}
              onSelect={() => onSelect(node.id)}
              onHover={(hovered) => onHover(hovered ? node.id : null)}
            />
          ),
        )}

        {/* Bloom SELECTIVO (§7): solo lo que va dentro de un <Select> —el núcleo,
            el CEO, los nodos activos, los avisos, los errores y las partículas de
            flujo— pasa por él. Los rótulos son DOM y quedan fuera por definición,
            y las órbitas, los agentes en reposo y las conexiones inactivas no se
            seleccionan nunca, así que la escena se sostiene con el bloom casi
            apagado. La viñeta es muy sutil, solo para cerrar los bordes. */}
        <EffectComposer enableNormalPass={false} multisampling={4}>
          <SelectiveBloom intensity={0.85} luminanceThreshold={0.35} luminanceSmoothing={0.3} mipmapBlur radius={0.55} />
          <Vignette offset={0.32} darkness={0.42} eskil={false} />
        </EffectComposer>
      </Selection>

      <CameraRig resetToken={resetToken} controls={controls} />
      <OrbitControls
        ref={controls}
        enableDamping
        dampingFactor={0.08}
        enablePan={false}
        minDistance={9}
        maxDistance={24}
        // Ni cenital ni por debajo del horizonte: la escena nunca se invierte ni
        // se aplana hasta perder la jerarquía de planos.
        minPolarAngle={Math.PI * 0.2}
        maxPolarAngle={Math.PI * 0.46}
        target={[0, LAYOUT.coreHeight, 0]}
      />
    </Canvas>
  );
}
