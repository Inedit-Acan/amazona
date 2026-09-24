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

function subscribe(onStoreChange: () => void): () => void {
  const media = window.matchMedia("(prefers-reduced-motion: reduce)");
  media.addEventListener("change", onStoreChange);
  // Aviso obligatorio nada más suscribirse: en el servidor la respuesta es
  // siempre «no se puede pintar en 3D» y, sin este empujón, `useSyncExternalStore`
  // se quedaría en esa respuesta para siempre y la vista 3D no llegaría a salir.
  const timer = window.setTimeout(onStoreChange, 0);
  return () => {
    media.removeEventListener("change", onStoreChange);
    window.clearTimeout(timer);
  };
}

function getSnapshot(): boolean {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches || !detectWebgl();
}

function getServerSnapshot(): boolean {
  return true; // En el servidor no hay ni WebGL ni preferencias: se dibuja la vista 2D.
}

/** True cuando la escena 3D no debe dibujarse: el dispositivo no tiene WebGL, o
 * quien mira pidió reducir el movimiento (especificación §32 y
 * docs/design/AMAZONA_sistema_de_diseno_visual.md §6). En ese caso el grafo cae
 * a la vista 2D, que enseña exactamente los mismos datos. */
export function useGraphFallback(): boolean {
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}
