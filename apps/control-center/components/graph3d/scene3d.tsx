"use client";

import { useMemo, useRef } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import { Html, Line, OrbitControls } from "@react-three/drei";
import type * as THREE from "three";
import type { AgentGraphEdge, AgentGraphNode } from "./graph-state";
import { NODE_STATUS_COLOR } from "./node-colors";

function nodeSize(node: AgentGraphNode): number {
  if (node.kind === "decision") return 0.55;
  if (node.kind === "ceo") return 0.5;
  if (node.kind === "output") return 0.35;
  return 0.4;
}

function baseEmissive(node: AgentGraphNode): number {
  switch (node.status) {
    case "active":
      return 1.1;
    case "blocked":
      return 0.85;
    case "error":
      return 1;
    case "waiting":
      return 0.45;
    default:
      return 0.25;
  }
}

function Node3D({
  node,
  selected,
  onSelect,
}: {
  node: AgentGraphNode;
  selected: boolean;
  onSelect: (id: string) => void;
}) {
  const materialRef = useRef<THREE.MeshStandardMaterial>(null);
  const size = nodeSize(node);
  const color = NODE_STATUS_COLOR[node.status];
  const pulsing = node.status === "active" || node.kind === "ceo";

  useFrame(({ clock }) => {
    if (!materialRef.current) return;
    materialRef.current.emissiveIntensity = pulsing
      ? baseEmissive(node) + Math.sin(clock.elapsedTime * 2) * 0.25
      : baseEmissive(node);
  });

  return (
    <group position={node.position}>
      <mesh
        onClick={(e) => {
          e.stopPropagation();
          onSelect(node.id);
        }}
      >
        <sphereGeometry args={[size, 32, 32]} />
        <meshStandardMaterial
          ref={materialRef}
          color={color}
          emissive={color}
          emissiveIntensity={baseEmissive(node)}
          roughness={0.35}
          metalness={0.15}
        />
      </mesh>
      {selected ? (
        <mesh>
          <sphereGeometry args={[size * 1.35, 24, 24]} />
          <meshBasicMaterial color={color} transparent opacity={0.15} />
        </mesh>
      ) : null}
      <Html position={[0, -(size + 0.35), 0]} center distanceFactor={10} style={{ pointerEvents: "none" }}>
        <div
          style={{
            color: "#f5f7f7",
            fontSize: 11,
            fontWeight: 500,
            textShadow: "0 1px 3px rgba(0,0,0,0.85)",
            whiteSpace: "nowrap",
          }}
        >
          {node.label}
        </div>
      </Html>
    </group>
  );
}

function Edge3D({ edge, nodesById }: { edge: AgentGraphEdge; nodesById: Map<string, AgentGraphNode> }) {
  const source = nodesById.get(edge.source);
  const target = nodesById.get(edge.target);
  if (!source || !target) return null;
  return (
    <Line
      points={[source.position, target.position]}
      color={edge.active ? NODE_STATUS_COLOR.active : "#22c997"}
      lineWidth={edge.active ? 2 : 1}
      transparent
      opacity={edge.active ? 0.85 : 0.18}
    />
  );
}

export function Scene3D({
  nodes,
  edges,
  selectedNodeId,
  onSelectNode,
}: {
  nodes: AgentGraphNode[];
  edges: AgentGraphEdge[];
  selectedNodeId: string | null;
  onSelectNode: (id: string | null) => void;
}) {
  const nodesById = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes]);

  return (
    <Canvas camera={{ position: [9, 6, 9], fov: 45 }} onPointerMissed={() => onSelectNode(null)}>
      <color attach="background" args={["#050808"]} />
      <ambientLight intensity={0.5} />
      <pointLight position={[10, 10, 10]} intensity={0.8} color="#15f0b2" />
      <pointLight position={[-10, -6, -10]} intensity={0.35} color="#28e5d0" />
      {edges.map((edge) => (
        <Edge3D key={edge.id} edge={edge} nodesById={nodesById} />
      ))}
      {nodes.map((node) => (
        <Node3D key={node.id} node={node} selected={node.id === selectedNodeId} onSelect={onSelectNode} />
      ))}
      <OrbitControls
        enableDamping
        dampingFactor={0.1}
        minDistance={6}
        maxDistance={20}
        maxPolarAngle={Math.PI * 0.85}
        enablePan={false}
      />
    </Canvas>
  );
}
