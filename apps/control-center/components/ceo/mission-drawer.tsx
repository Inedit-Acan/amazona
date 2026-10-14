"use client";

import { useImperativeHandle, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useCeo } from "@/components/ceo/ceo-context";
import { MissionForm, useMission } from "@/components/ceo/mission-form";
import { DataProvenanceBadge } from "@/components/data-provenance-badge";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { buildInitialState, hasHandoff, type MissionInitialState } from "@/lib/ceo-handoff";

/** El drawer de «Crear misión» (M47, Commit 2). Se abre con el botón de la cabecera o, solo, cuando llega una misión precargada
 * desde otra pantalla (`/ceo?title=…`: Investigación, Proveedores, Economía, Legal, Tienda y Marketing). El estado del
 * formulario vive aquí, no en el contenido del drawer: cerrarlo por error no pierde lo escrito. */
function MissionDrawerInner({ initial, startOpen }: { initial: MissionInitialState; startOpen: boolean }) {
  const { missionRef } = useCeo();
  const [open, setOpen] = useState(startOpen);
  const mission = useMission(initial);

  useImperativeHandle(missionRef, () => ({ open: () => setOpen(true) }), []);

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetContent side="right" className="w-full gap-0 overflow-y-auto data-[side=right]:sm:max-w-xl">
        <SheetHeader className="pr-12">
          <div className="flex flex-wrap items-center gap-2">
            <SheetTitle className="text-lg">Crear misión</SheetTitle>
            <DataProvenanceBadge
              status="demo"
              compact
              tooltip="Los agentes que ejecutan la misión son simulados: no mueven dinero, ni hacen pedidos, ni contactan proveedores."
            />
          </div>
          <SheetDescription>
            Un objetivo entra por el CEO, se reparte entre los agentes especializados y el Decision Engine sintetiza la decisión.
            Simulado — sin dinero, pedidos ni proveedores reales.
          </SheetDescription>
        </SheetHeader>
        <div className="px-4 pb-8">
          <MissionForm mission={mission} />
        </div>
      </SheetContent>
    </Sheet>
  );
}

export function MissionDrawer() {
  const searchParams = useSearchParams();
  const initial = useMemo(() => buildInitialState(searchParams), [searchParams]);
  // Una precarga nueva (otra pantalla navega a /ceo con otros parámetros) reinicia el formulario y vuelve a abrir el drawer.
  return <MissionDrawerInner key={searchParams.toString()} initial={initial} startOpen={hasHandoff(searchParams)} />;
}
