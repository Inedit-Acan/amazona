"use client";

import { useMemo, useState } from "react";
import type { Decision } from "@/lib/api";
import { deriveGraphState } from "./graph-state";
import { useGraphFallback } from "./use-graph-fallback";
import { Scene3D } from "./scene3d";
import { AgentGraph2DFallback } from "./agent-graph-2d-fallback";
import { StatusChip } from "@/components/status-chip";

const STATUS_TO_CHIP: Record<string, string> = {
  idle: "PENDING",
  waiting: "WAITING",
  active: "COMPLETED",
  blocked: "REVIEW",
  error: "NO_GO",
};

/** The only real 3D component in the whole app (docs/design/
 * AMAZONA_sistema_de_diseno_visual.md §2, §8) — shows the CEOOrchestrator
 * flow (Objective -> CEO -> specialist agents -> Decision Engine ->
 * Approve/Reject) live as `decision` becomes available, with a 2D
 * reactflow fallback for no-WebGL / prefers-reduced-motion. */
export function AgentGraph3D({ decision }: { decision: Decision | null }) {
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const useFallback = useGraphFallback();
  const { nodes, edges } = useMemo(() => deriveGraphState(decision), [decision]);
  const selectedNode = nodes.find((n) => n.id === selectedNodeId) ?? null;

  return (
    <div className="space-y-3">
      {useFallback ? (
        <AgentGraph2DFallback nodes={nodes} edges={edges} onSelectNode={setSelectedNodeId} />
      ) : (
        <div className="h-[420px] w-full overflow-hidden rounded-xl border">
          <Scene3D nodes={nodes} edges={edges} selectedNodeId={selectedNodeId} onSelectNode={setSelectedNodeId} />
        </div>
      )}

      {selectedNode ? (
        <div className="flex items-center justify-between gap-3 rounded-lg border bg-card px-4 py-3">
          <div>
            <p className="text-sm font-medium">{selectedNode.label}</p>
            <p className="text-xs text-muted-foreground">{selectedNode.role}</p>
          </div>
          <StatusChip status={STATUS_TO_CHIP[selectedNode.status] ?? "PENDING"} />
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">
          {useFallback
            ? "Haz clic en un nodo para ver su detalle."
            : "Arrastra para orbitar, rueda para hacer zoom, clic en un nodo para ver su detalle."}
        </p>
      )}
    </div>
  );
}
