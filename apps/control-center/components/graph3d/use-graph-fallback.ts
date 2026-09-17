"use client";

import { useSyncExternalStore } from "react";

function detectWebgl(): boolean {
  try {
    const canvas = document.createElement("canvas");
    return Boolean(canvas.getContext("webgl2") || canvas.getContext("webgl"));
  } catch {
    return false;
  }
}

function subscribe(): () => void {
  // Capability never changes after mount — no external event to listen to.
  return () => {};
}

function getSnapshot(): boolean {
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  return reducedMotion || !detectWebgl();
}

function getServerSnapshot(): boolean {
  return true; // 2D fallback until mounted — neither check is meaningful during SSR.
}

/** True when the real 3D scene should not render — no WebGL support, or
 * the viewer asked for reduced motion (docs/design/
 * AMAZONA_sistema_de_diseno_visual.md §6). */
export function useGraphFallback(): boolean {
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}
