"use client";

import { useEffect, useMemo, useRef, type ComponentRef, type RefObject } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import { OrbitControls } from "@react-three/drei";
import { Bloom, EffectComposer } from "@react-three/postprocessing";
import * as THREE from "three";
import { CORE_ID, LAYOUT, relatedIds, type GraphEdge, type GraphMode, type GraphNode } from "@/lib/neural-nexus";
import { NODE_RADIUS } from "../nexus-theme";
import { DecisionCore } from "./decision-core";
import { NexusEdge } from "./nexus-edge";
import { NexusNode } from "./nexus-node";

const AMBIENT_PARTICLES = 200;
/** Cámara baja y lejana: es lo que achata los anillos en una elipse, como el mockup. */
const CAMERA_HOME: [number, number, number] = [0, 2.9, 15.5];

/** Anillos orbitales planos alrededor del núcleo. Decorativos y muy lentos: no
 * mueven los nodos, así que la memoria espacial se conserva (especificación §12.4). */
function OrbitRings({ animate }: { animate: boolean }) {
  const group = useRef<THREE.Group>(null);
  const radii = useMemo(
    () => [LAYOUT.domainRadius * 0.62, LAYOUT.domainRadius, LAYOUT.domainRadius * 1.42, LAYOUT.agentRadius, LAYOUT.agentRadius * 1.18],
    [],
  );
  useFrame(({ clock }) => {
    if (animate && group.current) group.current.rotation.y = clock.elapsedTime * 0.02;
  });
  return (
    <group ref={group} rotation={[-Math.PI / 2, 0, 0]}>
      {radii.map((radius, index) => (
        <mesh key={radius}>
          <ringGeometry args={[radius - 0.006, radius + 0.006, 128]} />
          <meshBasicMaterial
            color={index === 1 || index === 3 ? "#15f0b2" : "#22c997"}
            transparent
            opacity={index === 1 || index === 3 ? 0.3 : 0.13}
            side={THREE.DoubleSide}
            depthWrite={false}
          />
        </mesh>
      ))}
    </group>
  );
}

/** Radios que salen del núcleo hacia cada dominio, desvaneciéndose hacia fuera:
 * el «sol» de líneas del mockup. */
function RadialSpokes({ nodes }: { nodes: GraphNode[] }) {
  const geometry = useMemo(() => {
    const positions: number[] = [];
    const colors: number[] = [];
    const inner = new THREE.Color("#15f0b2");
    const outer = new THREE.Color("#04231d");
    for (const node of nodes) {
      if (node.type !== "domain") continue;
      const [x, y, z] = node.position;
      const length = Math.hypot(x, z) || 1;
      positions.push(0, 0, 0, (x / length) * LAYOUT.agentRadius * 1.25, y, (z / length) * LAYOUT.agentRadius * 1.25);
      colors.push(inner.r, inner.g, inner.b, outer.r, outer.g, outer.b);
    }
    return { positions: new Float32Array(positions), colors: new Float32Array(colors) };
  }, [nodes]);

  if (geometry.positions.length === 0) return null;
  return (
    <lineSegments>
      <bufferGeometry>
        <bufferAttribute attach="attributes-position" args={[geometry.positions, 3]} />
        <bufferAttribute attach="attributes-color" args={[geometry.colors, 3]} />
      </bufferGeometry>
      <lineBasicMaterial vertexColors transparent opacity={0.45} blending={THREE.AdditiveBlending} />
    </lineSegments>
  );
}

/** Polvo ambiental: pocas partículas, muy tenues, solo para dar profundidad. */
function AmbientParticles({ animate }: { animate: boolean }) {
  const points = useRef<THREE.Points>(null);
  const positions = useMemo(() => {
    const array = new Float32Array(AMBIENT_PARTICLES * 3);
    for (let i = 0; i < AMBIENT_PARTICLES; i++) {
      const phi = Math.acos(1 - (2 * (i + 0.5)) / AMBIENT_PARTICLES);
      const theta = Math.PI * (1 + Math.sqrt(5)) * i;
      const r = 9 + (i % 6) * 1.5;
      array[i * 3] = r * Math.sin(phi) * Math.cos(theta);
      array[i * 3 + 1] = r * Math.cos(phi) * 0.4;
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
      <pointsMaterial color="#22c997" size={0.035} transparent opacity={0.35} sizeAttenuation />
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
    const progress = (clock.elapsedTime % 11) / 3.6;
    mesh.current.visible = progress <= 1;
    if (progress <= 1) {
      mesh.current.scale.setScalar(0.4 + progress * 8.5);
      (mesh.current.material as THREE.MeshBasicMaterial).opacity = 0.2 * (1 - progress);
    }
  });
  return (
    <mesh ref={mesh} rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.05, 0]}>
      <ringGeometry args={[0.94, 1, 128]} />
      <meshBasicMaterial color="#15f0b2" transparent opacity={0.2} side={THREE.DoubleSide} depthWrite={false} blending={THREE.AdditiveBlending} />
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
      camera={{ position: CAMERA_HOME, fov: 38 }}
      dpr={[1, 1.75]}
      onPointerMissed={() => onSelect(null)}
      gl={{ antialias: true }}
    >
      <color attach="background" args={["#030606"]} />
      <fog attach="fog" args={["#030606", 18, 38]} />
      <ambientLight intensity={0.6} />

      <AmbientParticles animate={animate} />
      <OrbitRings animate={animate} />
      <RadialSpokes nodes={nodes} />
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

      {/* El bloom es lo que da el aspecto del mockup: todo lo que pasa del umbral
          de luminancia sangra luz. Los rótulos van en DOM y no se ven afectados,
          así que el texto sigue nítido. */}
      <EffectComposer enableNormalPass={false}>
        <Bloom intensity={1.15} luminanceThreshold={0.22} luminanceSmoothing={0.45} mipmapBlur radius={0.72} />
      </EffectComposer>

      <CameraRig resetToken={resetToken} controls={controls} />
      <OrbitControls
        ref={controls}
        enableDamping
        dampingFactor={0.08}
        enablePan={false}
        minDistance={8}
        maxDistance={26}
        // Ni cenital ni por debajo del horizonte: la escena no se invierte ni se aplana.
        minPolarAngle={Math.PI * 0.22}
        maxPolarAngle={Math.PI * 0.49}
        autoRotate={false}
      />
    </Canvas>
  );
}
