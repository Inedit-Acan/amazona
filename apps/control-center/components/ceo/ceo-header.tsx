"use client";

import { Brain, Plus } from "lucide-react";
import { BackendStatus } from "@/components/backend-status";
import { useCeo } from "@/components/ceo/ceo-context";
import { FullscreenButton } from "@/components/ceo/fullscreen-button";
import { Button } from "@/components/ui/button";
import { FULLSCREEN_LABEL } from "@/lib/ceo-fullscreen";

/** La cabecera del Director ejecutivo (M47, Commit 2): título, etiqueta «CEO IA», subtítulo y controles.
 *
 *  · «Crear misión» abre el drawer con el formulario (el flujo actual, con su clave de intención).
 *  · «Vista completa» es la pantalla completa del grafo (la misma acción que «Abrir vista completa» de su tarjeta).
 *  · «CEO IA» solo existe bajo 1440 px, donde el panel es un drawer.
 *  · El estado del backend lo enseña el shell desde `md`; bajo `md` el shell no lo enseña y lo enseña esta cabecera (mismo
 *    monitor, una sola petición por disparo).
 *  · El selector temporal 7/14/30 días NO está aquí todavía: aparecerá cuando cambie datos de verdad (Commit 3). */
export function CeoHeader() {
  const { openMission, openAssistant } = useCeo();
  return (
    <div className="mb-4 flex flex-wrap items-start justify-between gap-x-4 gap-y-3">
      <div className="min-w-0 flex-1 basis-96">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-2xl font-semibold tracking-tight">Director ejecutivo</h1>
          <span className="inline-flex items-center rounded-md border border-primary/40 bg-primary/10 px-2 py-0.5 text-xs font-semibold tracking-wide text-primary">
            CEO IA
          </span>
        </div>
        <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
          Centro de mando: el orquestador reparte las misiones entre los agentes. Cada bloque dice si su dato se ha leído, está vacío o
          no está disponible.
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <BackendStatus showLabel className="md:hidden" />
        <Button type="button" onClick={openMission}>
          <Plus aria-hidden /> Crear misión
        </Button>
        <FullscreenButton label={FULLSCREEN_LABEL} />
        <Button type="button" variant="outline" className="min-[1440px]:hidden" onClick={openAssistant} aria-haspopup="dialog">
          <Brain aria-hidden /> CEO IA
        </Button>
      </div>
    </div>
  );
}
