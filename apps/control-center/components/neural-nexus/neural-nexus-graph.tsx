"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import dynamic from "next/dynamic";
import { api, type Agent, type AgentExecution, type Decision } from "@/lib/api";
import {
  applyMode,
  buildGraph,
  hudMetrics,
  type GraphMode,
  type NodeStatus,
} from "@/lib/neural-nexus";
import { useGraphFallback } from "./use-nexus-fallback";
import { Nexus2D } from "./nexus-2d";
import { NexusDetails } from "./nexus-details";
import { NexusHud } from "./nexus-hud";
import { NexusLegend } from "./nexus-legend";
import { NexusToolbar } from "./nexus-toolbar";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

// three.js se queda fuera del bundle principal. Sin `ssr: false`: esa opción deja
// suspendida para siempre la pantalla que monta el grafo. No hace falta, porque
// en el servidor `useGraphFallback` devuelve true y se dibuja la vista 2D; la
// escena solo se pide cuando el cliente ya ha decidido que puede con ella.
const NexusScene = dynamic(() => import("./scene/nexus-scene").then((mod) => mod.NexusScene), {
  loading: () => <Skeleton className="size-full rounded-none" />,
});

const EMPTY_COUNTS: Record<NodeStatus, number> = {
  running: 0,
  available: 0,
  waiting: 0,
  blocked: 0,
  error: 0,
  inactive: 0,
};

/** Grafo de agentes del Director ejecutivo. Cuatro niveles —CEO → Decision
 * Engine → 8 dominios → 13 agentes—, tres modos (Arquitectura, Ejecución e
 * Incidencias) y vista 3D con alternativa 2D sobre el mismo dataset
 * (docs/design/KOVA_Neural_Nexus_especificacion_Claude_Code.md).
 *
 * Real: los agentes del registro con su estado, su log de ejecuciones y la
 * decisión del CEO con sus evidencias, que es lo que pone a un agente a
 * ejecutar, a esperar o bloqueado. Demo: la tarea en curso, el progreso, los
 * handoffs entre dominios y las métricas del núcleo; el panel de cada nodo lo
 * declara. */
export function NeuralNexusGraph({ decision }: { decision: Decision | null }) {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [executions, setExecutions] = useState<AgentExecution[]>([]);
  const [loading, setLoading] = useState(true);
  const [mode, setMode] = useState<GraphMode>("architecture");
  const [manualView, setManualView] = useState<"3d" | "2d" | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [fullscreen, setFullscreen] = useState(false);
  const [resetToken, setResetToken] = useState(0);
  // El instante se fija al montar y no vuelve a cambiar: el grafo no se mueve
  // solo entre repintados. (Date.now() en el render lo rechaza eslint.)
  const [now] = useState(() => new Date().getTime());
  const container = useRef<HTMLDivElement>(null);

  const autoFallback = useGraphFallback();
  const view = autoFallback || manualView === "2d" ? "2d" : "3d";
  // Con "reducir movimiento" la escena se queda quieta pero sigue informando.
  const animate = view === "3d" && !autoFallback;

  useEffect(() => {
    let cancelled = false;
    Promise.all([api.listAgents().catch((): Agent[] => []), api.listAgentExecutions().catch((): AgentExecution[] => [])])
      .then(([registry, runs]) => {
        if (cancelled) return;
        setAgents(registry);
        setExecutions(runs);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // El <Canvas> de R3F mide su contenedor al montar y aquí esa primera medida
  // vuelve 0: el lienzo se queda en los 300 × 150 por defecto (contenedor real:
  // ~1200 × 544). Un `resize` le hace medir otra vez y ya acierta, así que se le
  // manda uno en cuanto la escena aparece; se repite porque el montaje no siempre
  // ha terminado en el primer frame.
  useEffect(() => {
    if (loading || view !== "3d") return;
    const timers = [50, 250, 800].map((delay) => window.setTimeout(() => window.dispatchEvent(new Event("resize")), delay));
    return () => timers.forEach((timer) => window.clearTimeout(timer));
  }, [loading, view]);

  useEffect(() => {
    function onChange() {
      setFullscreen(Boolean(document.fullscreenElement));
    }
    document.addEventListener("fullscreenchange", onChange);
    return () => document.removeEventListener("fullscreenchange", onChange);
  }, []);

  const toggleFullscreen = useCallback(async () => {
    if (!container.current) return;
    try {
      if (!document.fullscreenElement) await container.current.requestFullscreen?.();
      else await document.exitFullscreen?.();
    } catch {
      // La API de pantalla completa puede estar bloqueada; no es crítico.
    }
  }, []);

  const { nodes, edges } = useMemo(
    () => buildGraph({ agents, executions, decision, now }),
    [agents, executions, decision, now],
  );
  const view3d = useMemo(() => applyMode(nodes, edges, mode), [nodes, edges, mode]);
  const metrics = useMemo(() => hudMetrics(nodes, executions, decision), [nodes, executions, decision]);
  const counts = useMemo(() => {
    const totals = { ...EMPTY_COUNTS };
    for (const node of nodes) if (node.type === "agent") totals[node.status] += 1;
    return totals;
  }, [nodes]);
  const selected = nodes.find((node) => node.id === selectedId) ?? null;

  return (
    <div className="space-y-3">
      <NexusToolbar
        mode={mode}
        onModeChange={setMode}
        view={view}
        onViewChange={setManualView}
        view3dDisabled={autoFallback}
        view3dDisabledReason="Tu dispositivo no soporta bien WebGL, o pediste reducir el movimiento."
        fullscreen={fullscreen}
        onToggleFullscreen={toggleFullscreen}
        onResetCamera={() => setResetToken((token) => token + 1)}
      />

      <div
        ref={container}
        className={cn(
          "relative overflow-hidden rounded-xl border bg-[#030606]",
          fullscreen ? "h-screen w-screen" : "h-[34rem] w-full",
        )}
      >
        {loading ? (
          <Skeleton className="size-full rounded-none" />
        ) : view === "3d" ? (
          <NexusScene
            nodes={nodes}
            edges={view3d.edges}
            mode={mode}
            dimmed={view3d.dimmed}
            selectedId={selectedId}
            hoveredId={hoveredId}
            animate={animate}
            resetToken={resetToken}
            onSelect={setSelectedId}
            onHover={setHoveredId}
          />
        ) : (
          <Nexus2D
            nodes={nodes}
            edges={view3d.edges}
            dimmed={view3d.dimmed}
            selectedId={selectedId}
            hoveredId={hoveredId}
            onSelect={setSelectedId}
            onHover={setHoveredId}
          />
        )}

        {/* Capa HUD: no intercepta el ratón salvo en el panel de detalle. */}
        <div className="pointer-events-none absolute inset-0 flex items-start justify-between p-3">
          <NexusHud metrics={metrics} />
          <div className="flex flex-col items-end gap-2">
            <NexusLegend counts={counts} />
            {selected ? (
              <NexusDetails node={selected} nodes={nodes} edges={edges} now={now} onClose={() => setSelectedId(null)} />
            ) : null}
          </div>
        </div>
      </div>

      <p className="text-[11px] text-muted-foreground">
        {view === "3d"
          ? "Arrastra para orbitar, rueda para hacer zoom y haz clic en un nodo para ver su detalle."
          : "Haz clic en un nodo para ver su detalle. La vista 2D usa los mismos datos que la 3D."}{" "}
        Real: los {counts.running + counts.available + counts.waiting + counts.blocked + counts.error + counts.inactive} agentes del
        registro con su estado, sus ejecuciones y la decisión del CEO. De demostración: la tarea en curso de cada agente, su
        progreso, los handoffs entre dominios y las métricas del Decision Engine.
      </p>
    </div>
  );
}
