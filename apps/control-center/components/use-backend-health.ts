"use client";

import { useSyncExternalStore } from "react";
import { api } from "@/lib/api";
import { checkBackend, HealthMonitor, type BackendHealthState } from "@/lib/backend-health";
import { createHealthStore } from "@/lib/backend-health-store";

/** El almacén único de la pestaña: la cabecera del shell y la del Director ejecutivo comparten el mismo monitor
 * (`lib/backend-health-store.ts`). El monitor comprueba al montar, al volver la pestaña a visible, al recuperar el foco y cada
 * 60 s solo con la pestaña visible (`lib/backend-health.ts`). El estado inicial es «comprobando», nunca «operativo». */
const store = createHealthStore({
  attach(publish) {
    const monitor = new HealthMonitor({
      check: () => checkBackend((signal) => api.getReadiness(signal)),
      now: () => Date.now(),
      onChange: publish,
    });
    const onVisibility = () => monitor.setVisible(document.visibilityState === "visible");
    const onFocus = () => monitor.focus();
    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener("focus", onFocus);
    monitor.start(document.visibilityState === "visible");
    return () => {
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("focus", onFocus);
      monitor.dispose();
    };
  },
});

export function useBackendHealth(): BackendHealthState {
  return useSyncExternalStore(store.subscribe, store.getSnapshot, store.getServerSnapshot);
}
