"use client";

import { useMemo } from "react";
import ReactFlow, { Background, Handle, Position, type Edge, type Node, type NodeProps } from "reactflow";
import "reactflow/dist/style.css";
import type { AgentGraphNode, AgentGraphEdge } from "./graph-state";
import { NODE_STATUS_COLOR, NODE_STATUS_OPACITY } from "./node-colors";

const COLUMN_X: Record<string, number> = {
  ceo: 320,
  product_hunter: 0,
  market_analyst: 110,
  supplier_finder: 220,
  cfo_finance: 330,
  legal: 440,
  marketing: 550,
  ecommerce: 660,
  decision_engine: 320,
  approve: 220,
  reject: 420,
};

const ROW_Y: Record<string, number> = {
  ceo: 0,
  product_hunter: 110,
  market_analyst: 110,
  supplier_finder: 110,
  cfo_finance: 110,
  legal: 110,
  marketing: 110,
  ecommerce: 110,
  decision_engine: 230,
  approve: 340,
  reject: 340,
};

function GraphNode({ data }: NodeProps<{ label: string; role: string; status: keyof typeof NODE_STATUS_COLOR }>) {
  const color = NODE_STATUS_COLOR[data.status];
  return (
    <div
      className="rounded-lg border px-3 py-2 text-center text-xs shadow-sm"
      style={{
        borderColor: color,
        background: "var(--panel)",
        color: "var(--text-primary)",
        opacity: NODE_STATUS_OPACITY[data.status],
        minWidth: 96,
      }}
      title={data.role}
    >
      <Handle type="target" position={Position.Top} style={{ opacity: 0 }} />
      <p className="font-medium">{data.label}</p>
      <Handle type="source" position={Position.Bottom} style={{ opacity: 0 }} />
    </div>
  );
}

const nodeTypes = { agentNode: GraphNode };

export function AgentGraph2DFallback({
  nodes: agentNodes,
  edges: agentEdges,
  onSelectNode,
}: {
  nodes: AgentGraphNode[];
  edges: AgentGraphEdge[];
  onSelectNode: (id: string) => void;
}) {
  const nodes: Node[] = useMemo(
    () =>
      agentNodes.map((n) => ({
        id: n.id,
        type: "agentNode",
        position: { x: COLUMN_X[n.id] ?? 0, y: ROW_Y[n.id] ?? 0 },
        data: { label: n.label, role: n.role, status: n.status },
        draggable: false,
      })),
    [agentNodes],
  );

  const edges: Edge[] = useMemo(
    () =>
      agentEdges.map((e) => ({
        id: e.id,
        source: e.source,
        target: e.target,
        animated: e.active,
        style: { stroke: e.active ? NODE_STATUS_COLOR.active : "var(--border)", opacity: e.active ? 0.9 : 0.3 },
      })),
    [agentEdges],
  );

  return (
    <div className="h-[420px] w-full overflow-hidden rounded-xl border">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodeClick={(_, node) => onSelectNode(node.id)}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        proOptions={{ hideAttribution: true }}
        nodesConnectable={false}
        elementsSelectable
        panOnDrag
        zoomOnScroll
      >
        <Background color="var(--border)" gap={24} />
      </ReactFlow>
    </div>
  );
}
