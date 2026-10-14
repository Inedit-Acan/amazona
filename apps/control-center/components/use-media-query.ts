"use client";

import { useSyncExternalStore } from "react";

/** ¿Se cumple esta consulta de medios? Sin servidor ni medios disponibles es `false` (el servidor renderiza el diseño estrecho y
 * el navegador lo corrige al hidratar, sin desajuste: `useSyncExternalStore` distingue el snapshot de servidor). */
export function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    (onChange) => {
      const media = window.matchMedia(query);
      media.addEventListener("change", onChange);
      return () => media.removeEventListener("change", onChange);
    },
    () => window.matchMedia(query).matches,
    () => false,
  );
}
