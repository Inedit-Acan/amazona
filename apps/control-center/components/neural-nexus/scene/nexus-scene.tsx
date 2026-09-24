"use client";

import { useEffect, useMemo, useRef, type ComponentRef, type RefObject } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import { OrbitControls } from "@react-three/drei";
import * as THREE from "three";
import { CORE_ID, relatedIds, type GraphEdge, type GraphMode, type GraphNode } from "@/lib/neural-nexus";
import { NODE_RADIUS } from "../nexus-theme";
import { DecisionCore } from "./decision-core";
import { NexusEdge } from "./nexus-edge";
import { NexusNode } from "./nexus-node";

const AMBIENT_PARTICLES = 160;
const CAMERA_HOME: [number, number, number] = [0, 5.4, 13.5];

/** Polvo ambiental: pocas partículas, muy tenues, solo para dar profundidad. */
function AmbientParticles({ animate }: { animate: boolean }) {
  const points = useRef<THREE.Points>(null);
  const positions = useMemo(() => {
    const array = new Float32Array(AMBIENT_PARTICLES * 3);
    for (let i = 0; i < AMBIENT_PARTICLES; i++) {
      const phi = Math.acos(1 - (2 * (i + 0.5)) / AMBIENT_PARTICLES);
      const theta = Math.PI * (1 + Math.sqrt(5)) * i;
      const r = 9 + (i % 5) * 1.6;
      array[i * 3] = r * Math.sin(phi) * Math.cos(theta);
      array[i * 3 + 1] = r * Math.cos(phi) * 0.5;
      array[i * 3 + 2] = r * Math.sin(phi) * Math.sin(theta);
    }
    return array;
  }, []);

  useFrame(({ clock }) => {
    if (animate && points.current) points.current.rotation.y = clock.elapsedTime * 0.012;
  });

  return (
    <points ref={points}>
      <bufferGeometry>
        <bufferAttribute attach="attributes-position" args={[positions, 3]} />
      </bufferGeometry>
      <pointsMaterial color="#22c997" size={0.03} transparent opacity={0.28} sizeAttenuation />
    </points>
  );
}

/** Barrido de escáner: una onda que se expande por el plano del anillo, muy de
 * vez en cuando (especificación §12.5). */
function ScanWave({ animate }: { animate: boolean }) {
  const mesh = useRef<THREE.Mesh>(null);
  useFrame(({ clock }) => {
    if (!mesh.current) return;
    if (!animate) {
      mesh.current.visible = false;
      return;
    }
    const cycle = 9;
    const t = clock.elapsedTime % cycle;
    const progress = t / 3.2;
    mesh.current.visible = progress <= 1;
    if (progress <= 1) {
      mesh.current.scale.setScalar(0.4 + progress * 8);
      const material = mesh.current.material as THREE.MeshBasicMaterial;
      material.opacity = 0.16 * (1 - progress);
    }
  });
  return (
    <mesh ref={mesh} rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.9, 0]}>
      <ringGeometry args={[0.92, 1, 96]} />
      <meshBasicMaterial color="#15f0b2" transparent opacity={0.16} side={THREE.DoubleSide} depthWrite={false} />
    </mesh>
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

  return (
    <Canvas
      camera={{ position: CAMERA_HOME, fov: 42 }}
      dpr={[1, 1.75]}
      onPointerMissed={() => onSelect(null)}
      gl={{ antialias: true }}
    >
      <color attach="background" args={["#030606"]} />
      <fog attach="fog" args={["#030606", 14, 30]} />
      <ambientLight intensity={0.45} />
      <pointLight position={[0, 6, 6]} intensity={1.1} color="#15f0b2" />
      <pointLight position={[-9, -4, -8]} intensity={0.4} color="#28e5d0" />

      <AmbientParticles animate={animate} />
      <ScanWave animate={animate} />

      {edges.map((edge) => {
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
            onSelect={() => onSelect(node.id)}
            onHover={(hovered) => onHover(hovered ? node.id : null)}
          />
        ) : (
          <NexusNode
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

      <CameraRig resetToken={resetToken} controls={controls} />
      <OrbitControls
        ref={controls}
        enableDamping
        dampingFactor={0.08}
        enablePan={false}
        minDistance={7}
        maxDistance={22}
        // Nunca por debajo del horizonte ni cenital: la escena no se invierte.
        minPolarAngle={Math.PI * 0.12}
        maxPolarAngle={Math.PI * 0.52}
        autoRotate={false}
      />
    </Canvas>
  );
}
