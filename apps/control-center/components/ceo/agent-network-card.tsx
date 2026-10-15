"use client";

import { useCeo } from "@/components/ceo/ceo-context";
import { FullscreenButton } from "@/components/ceo/fullscreen-button";
import { NeuralNexusGraph } from "@/components/neural-nexus/neural-nexus-graph";
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { FULLSCREEN_CARD_LABEL } from "@/lib/ceo-fullscreen";

/** La tarjeta «Red de agentes (vista general)» del mockup (M47, Commit 2). Reutiliza el `NeuralNexusGraph` tal cual (sus modos y
 * su motor 3D quedan para el Commit 5): lee el registro de agentes y el log de ejecuciones con `ReadState`, y no tiene datos de
 * demostración como relleno. «Abrir vista completa» es la misma acción que «Vista completa» de la cabecera. */
export function AgentNetworkCard() {
  const { missionEvent, graphRef, setGraphDrawn } = useCeo();
  return (
    <Card className="min-w-0" data-block="Red de agentes">
      <CardHeader>
        <CardTitle className="text-sm font-semibold">Red de agentes (vista general)</CardTitle>
        <CardAction>
          <FullscreenButton label={FULLSCREEN_CARD_LABEL} size="sm" />
        </CardAction>
      </CardHeader>
      <CardContent>
        <NeuralNexusGraph ref={graphRef} missionEvent={missionEvent} onDrawnChange={setGraphDrawn} />
      </CardContent>
    </Card>
  );
}
