"use client";

import { useCallback, useEffect, useImperativeHandle, useMemo, useReducer, useRef, useState, type Ref } from "react";
import dynamic from "next/dynamic";
import { AlertTriangle, Network, RefreshCw } from "lucide-react";
import { api } from "@/lib/api";
import {
  applyMode,
  buildGraph,
  meanLatencyMs,
  type GraphMode,
  type NodeStatus,
} from "@/lib/neural-nexus";
import {
  engineHud,
  engineView,
  initialEngineState,
  persistedMissionOf,
  reduceEngine,
  tasksOfView,
  type MissionEvent,
} from "@/lib/nexus-engine-state";
import { readNexus, type NexusReads } from "@/lib/nexus-reads";
import { listOf } from "@/lib/read-state";
import { useGraphFallback } from "./use-nexus-fallback";
import { Nexus2D } from "./nexus-2d";
import { NexusDetails } from "./nexus-details";
import { NexusHud } from "./nexus-hud";
import { NexusLegend } from "./nexus-legend";
import { NexusToolbar } from "./nexus-toolbar";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { useMediaQuery } from "@/components/use-media-query";
import { CEO_NARROW_QUERY } from "@/lib/ceo-layout";
import { cn } from "@/lib/utils";

// three.js se queda fuera del bundle principal. Sin `ssr: false`: esa opción deja
// suspendida para siempre la pantalla que monta el grafo. No hace falta, porque
// en el servidor `useGraphFallback` devuelve true y se dibuja la vista 2D; la
// escena solo se pide cuando el cliente ya ha decidido que puede con ella.
const NexusScene = dynamic(() => import("./scene/nexus-scene").then((mod) => mod.NexusScene), {
  loading: () => <Skeleton className="size-full rounded-none" />,
});

/** Lo que el Director ejecutivo puede pedirle al grafo desde fuera (M47, Commit 2): la pantalla completa. Es la ÚNICA vía:
 * la cabecera y la tarjeta del Decision Engine llaman a lo mismo, y el botón del propio grafo también. */
export interface NexusGraphHandle {
  toggleFullscreen(): Promise<void>;
}

const EMPTY_COUNTS: Record<NodeStatus, number> = {
  running: 0,
  available: 0,
  waiting: 0,
  blocked: 0,
  degraded: 0,
  error: 0,
  inactive: 0,
  unknown: 0,
};

/** Grafo de agentes del Director ejecutivo. Cuatro niveles —CEO → Decision
 * Engine → 8 dominios → los agentes del registro—, tres modos (Arquitectura,
 * Ejecución e Incidencias) y vista 3D con alternativa 2D sobre el mismo dataset
 * (docs/design/KOVA_Neural_Nexus_especificacion_Claude_Code.md).
 *
 * Real: los agentes del registro con su estado, su log de ejecuciones y la última misión registrada (proyecto, decisión y tareas).
 * Nada es de demostración (M47 · Commit 4). El HUD sale de la máquina de estados de `lib/nexus-engine-state.ts`, que concilia lo que
 * dice el backend con la misión recién creada en esta sesión; cada dato del HUD lleva su procedencia.
 *
 * M47 · Commit 1: las lecturas son `ReadState` (lib/nexus-reads.ts) y NINGUNA se
 * traga. Sin una lectura válida del registro no hay grafo: hay un aviso. Un
 * registro vacío tampoco se rellena con agentes de demostración. Si solo falla el
 * log de ejecuciones, el grafo se dibuja con los agentes reales y lo que depende
 * de las ejecuciones dice «No disponible». */
export function NeuralNexusGraph({
  missionEvent = null,
  ref,
  onDrawnChange,
}: {
  /** La misión que se acaba de crear en esta sesión: adelanta lo que se enseña hasta que la relectura la confirma. */
  missionEvent?: MissionEvent | null;
  ref?: Ref<NexusGraphHandle>;
  /** Avisa de si el grafo está dibujado (hay registro leído): sin él no hay nada que ver a pantalla completa. */
  onDrawnChange?: (drawn: boolean) => void;
}) {
  // `null` = leyendo. Después, el `ReadState` de cada lectura.
  const [reads, setReads] = useState<NexusReads | null>(null);
  const [attempt, setAttempt] = useState(0);
  // La última misión registrada y la de esta sesión, conciliadas por una máquina de estados (lib/nexus-engine-state.ts). Cada lectura lleva
  // un sello: una respuesta vieja que llega tarde no pisa a la nueva.
  const [engine, dispatch] = useReducer(reduceEngine, undefined, initialEngineState);
  const readSeq = useRef(0);
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
  // En pantallas estrechas el grafo se abre en 2D (se puede pasar a 3D a mano): no hay sitio para orbitar con un dedo.
  const narrow = useMediaQuery(CEO_NARROW_QUERY);
  const view = autoFallback || manualView === "2d" || (manualView === null && narrow) ? "2d" : "3d";
  // Con "reducir movimiento" la escena se queda quieta pero sigue informando.
  const animate = view === "3d" && !autoFallback;

  // Una misión nueva se anota ANTES de la relectura que dispara (mismo orden de efectos).
  useEffect(() => {
    if (missionEvent !== null) dispatch({ type: "mission_created", session: missionEvent.session });
  }, [missionEvent]);

  // Se lee al montar, al reintentar y tras cada «Crear misión»: registro, ejecuciones y última misión (proyecto → decisión + tareas).
  useEffect(() => {
    let cancelled = false;
    readSeq.current += 1;
    const seq = readSeq.current;
    dispatch({ type: "read_requested" });
    readNexus(api).then((result) => {
      if (cancelled) return;
      setReads(result);
      dispatch({ type: "read_result", seq, mission: persistedMissionOf(result.mission) });
    });
    return () => {
      cancelled = true;
    };
  }, [attempt, missionEvent]);

  function retry() {
    setReads(null);
    setAttempt((count) => count + 1);
  }

  // Las listas válidas: `null` si esa lectura no existe (error o sin leer), `[]` solo si el backend dijo «vacío».
  const lists = useMemo(
    () => (reads ? { agents: listOf(reads.agents), executions: listOf(reads.executions) } : null),
    [reads],
  );
  const drawGraph = lists !== null && lists.agents !== null && lists.agents.length > 0;

  useEffect(() => {
    onDrawnChange?.(drawGraph);
  }, [drawGraph, onDrawnChange]);

  // El <Canvas> de R3F mide su contenedor al montar y aquí esa primera medida
  // vuelve 0: el lienzo se queda en los 300 × 150 por defecto (contenedor real:
  // ~1200 × 544). Un `resize` le hace medir otra vez y ya acierta, así que se le
  // manda uno en cuanto la escena aparece; se repite porque el montaje no siempre
  // ha terminado en el primer frame.
  useEffect(() => {
    if (!drawGraph || view !== "3d") return;
    const timers = [50, 250, 800].map((delay) => window.setTimeout(() => window.dispatchEvent(new Event("resize")), delay));
    return () => timers.forEach((timer) => window.clearTimeout(timer));
  }, [drawGraph, view]);

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

  useImperativeHandle(ref, () => ({ toggleFullscreen }), [toggleFullscreen]);

  const missionView = useMemo(() => engineView(engine), [engine]);
  const missionTasks = useMemo(() => tasksOfView(missionView), [missionView]);
  const { nodes, edges } = useMemo(
    () =>
      drawGraph && lists?.agents
        ? buildGraph({ agents: lists.agents, executions: lists.executions, tasks: missionTasks, now })
        : { nodes: [], edges: [] },
    [drawGraph, lists, missionTasks, now],
  );
  const view3d = useMemo(() => applyMode(nodes, edges, mode), [nodes, edges, mode]);
  const hud = useMemo(() => {
    const agentNodes = nodes.filter((node) => node.type === "agent");
    return engineHud({
      view: missionView,
      agents: { running: agentNodes.filter((node) => node.status === "running").length, total: agentNodes.length },
      latencyMs: meanLatencyMs(lists?.executions ?? null),
      now,
    });
  }, [nodes, missionView, lists, now]);
  const counts = useMemo(() => {
    const totals = { ...EMPTY_COUNTS };
    for (const node of nodes) if (node.type === "agent") totals[node.status] += 1;
    return totals;
  }, [nodes]);
  const selected = nodes.find((node) => node.id === selectedId) ?? null;

  // --- Estados que no son un grafo ---------------------------------------------------------------------------------

  if (reads === null) {
    return (
      <div className="space-y-3">
        <div
          role="status"
          aria-label="Leyendo el registro de agentes"
          className="relative h-[34rem] w-full overflow-hidden rounded-xl border bg-[#030606]"
        >
          <Skeleton className="size-full rounded-none" />
        </div>
      </div>
    );
  }

  if (reads.agents.kind === "error" || reads.agents.kind === "unread") {
    return (
      <Alert variant="destructive">
        <AlertTriangle className="size-4" />
        <AlertTitle>No se pudo leer el registro de agentes</AlertTitle>
        <AlertDescription>
          <p>{reads.agents.kind === "error" ? reads.agents.message : reads.agents.reason}</p>
          <p>No se dibuja el grafo: sin esa lectura no se sabe qué agentes hay ni en qué estado están.</p>
          <div className="mt-2">
            <Button type="button" size="sm" variant="outline" onClick={retry}>
              <RefreshCw /> Reintentar
            </Button>
          </div>
        </AlertDescription>
      </Alert>
    );
  }

  if (reads.agents.kind === "empty") {
    return (
      <div className="rounded-xl border">
        <EmptyState
          icon={Network}
          title="El registro no tiene agentes"
          description="El backend respondió y no hay ningún agente registrado. No se dibuja ningún grafo de relleno."
          action={
            <Button type="button" size="sm" variant="outline" onClick={retry}>
              <RefreshCw /> Volver a leer
            </Button>
          }
        />
      </div>
    );
  }

  const total = Object.values(counts).reduce((sum, count) => sum + count, 0);

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

      {reads.executions.kind === "error" || reads.executions.kind === "unread" ? (
        <Alert variant="destructive">
          <AlertTriangle className="size-4" />
          <AlertTitle>No se pudo leer el log de ejecuciones</AlertTitle>
          <AlertDescription>
            <p>
              {reads.executions.kind === "error" ? reads.executions.message : reads.executions.reason} El grafo enseña los agentes
              del registro, pero las ejecuciones, la latencia y el coste de cada agente salen como «No disponible».
            </p>
            <div className="mt-2">
              <Button type="button" size="sm" variant="outline" onClick={retry}>
                <RefreshCw /> Reintentar
              </Button>
            </div>
          </AlertDescription>
        </Alert>
      ) : null}

      {/* Desde `xl` el HUD, la leyenda y el detalle se superponen al lienzo (como el mockup); por debajo FLUYEN bajo él, para no
          taparlo en un ancho en el que no hay sitio (y a pantalla completa vuelven a superponerse). */}
      <div
        ref={container}
        className={cn(
          "relative overflow-hidden rounded-xl border bg-[#030606]",
          fullscreen ? "h-screen w-screen" : "w-full xl:h-[24rem]",
        )}
      >
        <div className={cn(fullscreen ? "absolute inset-0" : "h-[20rem] md:h-[22rem] xl:absolute xl:inset-0 xl:h-auto")}>
        {view === "3d" ? (
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
        </div>

        {/* Capa HUD: no intercepta el ratón salvo en el panel de detalle. */}
        <div
          className={cn(
            "flex flex-wrap items-start gap-2 p-3",
            fullscreen
              ? "pointer-events-none absolute inset-0 justify-between"
              : "xl:pointer-events-none xl:absolute xl:inset-0 xl:justify-between",
          )}
        >
          <NexusHud hud={hud} />
          <div className="flex flex-col items-start gap-2 xl:items-end">
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
        Del backend: los {total} agentes del registro con su estado, su log de ejecuciones y la última misión registrada (proyecto, decisión y
        tareas). Cada tarea se enseña con su agente asignado y el que la ejecutó, tal como lo registra el backend.
      </p>
    </div>
  );
}
