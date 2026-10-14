"use client";

import { createContext, useCallback, useContext, useMemo, useRef, useState, useSyncExternalStore, type ReactNode, type RefObject } from "react";
import type { NexusGraphHandle } from "@/components/neural-nexus/neural-nexus-graph";
import { fullscreenBlocker, fullscreenSupported } from "@/lib/ceo-fullscreen";
import type { DecisionState } from "@/lib/ceo-mission-view";

/** Lo que el Director ejecutivo comparte entre su cabecera, su tarjeta del Decision Engine y sus drawers (M47, Commit 2):
 * la decisión de la última misión, y las asas con las que se abren los drawers y la pantalla completa del grafo. */
export interface DrawerHandle {
  open(): void;
}

interface CeoContextValue {
  decision: DecisionState;
  setDecision: (decision: DecisionState) => void;
  graphRef: RefObject<NexusGraphHandle | null>;
  missionRef: RefObject<DrawerHandle | null>;
  assistantRef: RefObject<DrawerHandle | null>;
  /** El grafo está dibujado (hay registro de agentes leído). */
  graphDrawn: boolean;
  setGraphDrawn: (drawn: boolean) => void;
  /** La ÚNICA acción de «Vista completa»: la cabecera y la tarjeta del Decision Engine llaman a esto. */
  openGraphFullscreen: () => void;
  /** Por qué «Vista completa» está deshabilitada; `null` si puede usarse. */
  fullscreenBlocker: string | null;
  openMission: () => void;
  openAssistant: () => void;
}

const CeoContext = createContext<CeoContextValue | null>(null);

const noopSubscribe = () => () => {};

/** ¿El navegador admite la Fullscreen API? El servidor no lo sabe: se asume que sí y el navegador lo corrige al hidratar. */
function useFullscreenSupported(): boolean {
  return useSyncExternalStore(noopSubscribe, () => fullscreenSupported(document), () => true);
}

export function CeoProvider({ children }: { children: ReactNode }) {
  const [decision, setDecision] = useState<DecisionState>({ kind: "none" });
  const [graphDrawn, setGraphDrawn] = useState(false);
  const graphRef = useRef<NexusGraphHandle>(null);
  const missionRef = useRef<DrawerHandle>(null);
  const assistantRef = useRef<DrawerHandle>(null);
  const supported = useFullscreenSupported();

  const openGraphFullscreen = useCallback(() => {
    void graphRef.current?.toggleFullscreen();
  }, []);
  const openMission = useCallback(() => missionRef.current?.open(), []);
  const openAssistant = useCallback(() => assistantRef.current?.open(), []);

  const value = useMemo<CeoContextValue>(
    () => ({
      decision,
      setDecision,
      graphRef,
      missionRef,
      assistantRef,
      graphDrawn,
      setGraphDrawn,
      openGraphFullscreen,
      fullscreenBlocker: fullscreenBlocker({ supported, graphDrawn }),
      openMission,
      openAssistant,
    }),
    [decision, graphDrawn, supported, openGraphFullscreen, openMission, openAssistant],
  );

  return <CeoContext.Provider value={value}>{children}</CeoContext.Provider>;
}

export function useCeo(): CeoContextValue {
  const value = useContext(CeoContext);
  if (value === null) throw new Error("useCeo debe usarse dentro de <CeoProvider>");
  return value;
}
