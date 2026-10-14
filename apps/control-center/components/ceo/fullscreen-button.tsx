"use client";

import { useId } from "react";
import { Maximize2 } from "lucide-react";
import { useCeo } from "@/components/ceo/ceo-context";
import { Button } from "@/components/ui/button";

/** «Vista completa» / «Abrir vista completa» (M47, Commit 2): los dos controles son ESTE componente, con la misma acción
 * (`openGraphFullscreen`: la pantalla completa del grafo que ya existía) y las mismas condiciones. Sin Fullscreen API no se
 * simula nada: el botón se deshabilita y dice por qué, con texto accesible. No hay ruta nueva. */
export function FullscreenButton({ label, size = "default" }: { label: string; size?: "default" | "sm" }) {
  const { openGraphFullscreen, fullscreenBlocker } = useCeo();
  const noteId = useId();
  const blocked = fullscreenBlocker !== null;
  return (
    <>
      <Button
        type="button"
        variant="outline"
        size={size}
        data-fullscreen-trigger
        disabled={blocked}
        title={fullscreenBlocker ?? undefined}
        aria-describedby={blocked ? noteId : undefined}
        onClick={openGraphFullscreen}
      >
        <Maximize2 aria-hidden /> {label}
      </Button>
      {blocked ? (
        <span id={noteId} className="sr-only">
          {fullscreenBlocker}
        </span>
      ) : null}
    </>
  );
}
