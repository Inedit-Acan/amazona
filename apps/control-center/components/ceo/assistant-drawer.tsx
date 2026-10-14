"use client";

import { useImperativeHandle, useState } from "react";
import { CeoAssistantPanel } from "@/components/ceo/ceo-assistant-panel";
import { useCeo } from "@/components/ceo/ceo-context";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import { useMediaQuery } from "@/components/use-media-query";
import { CEO_PANEL_QUERY } from "@/lib/ceo-layout";

/** El panel del CEO IA como drawer, por debajo de 1440 px (M47, Commit 2). Desde 1440 el panel es la columna persistente y este
 * drawer no puede estar abierto: si la ventana se ensancha con él abierto, se cierra. */
export function AssistantDrawer() {
  const { assistantRef } = useCeo();
  const [open, setOpen] = useState(false);
  const wide = useMediaQuery(CEO_PANEL_QUERY);

  useImperativeHandle(assistantRef, () => ({ open: () => setOpen(true) }), []);

  // Ajuste de estado durante el render (el patrón que recomienda React): evita que un drawer abierto reaparezca solo al
  // volver a estrechar la ventana.
  if (wide && open) setOpen(false);

  return (
    <Sheet open={open && !wide} onOpenChange={setOpen}>
      <SheetContent side="right" className="w-full gap-0 p-3 sm:max-w-md">
        <SheetTitle className="sr-only">CEO IA</SheetTitle>
        <SheetDescription className="sr-only">
          Panel del CEO IA: chat, voz y pantalla. Hoy ninguna de las tres capacidades está disponible.
        </SheetDescription>
        <CeoAssistantPanel />
      </SheetContent>
    </Sheet>
  );
}
