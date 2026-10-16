import { Suspense } from "react";
import { ActivityCard } from "@/components/ceo/activity-block";
import { AreaExecutionsCard } from "@/components/ceo/area-executions-block";
import { BlockCard } from "@/components/ceo/block-card";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { api } from "@/lib/api-server";
import { ACTIVITY_BLOCK } from "@/lib/ceo-activity";
import { readActivityNow } from "@/lib/ceo-activity-reads";
import { AREA_BLOCK } from "@/lib/ceo-area-executions";
import { unavailableState } from "@/lib/ceo-blocks";

/** La franja inferior del mockup (M47, Commit 5): «Actividad registrada», «Ejecuciones por área» y «Próximos hitos».
 *
 *  · Actividad registrada y Ejecuciones por área leen su fuente (el registro de auditoría; el log de ejecuciones de los agentes y el
 *    registro de agentes) UNA vez, en el servidor, y cada tarjeta recibe SU vista: un fallo de una no apaga la otra. No dependen del
 *    periodo: el selector 7 / 14 / 30 días gobierna solo Ingresos. Ninguna lleva «Ver todas» (no existe una pantalla de detalle propia).
 *  · Próximos hitos: hoy NO existe una entidad de hitos → «No disponible». No se conecta a nada. */
const COLUMNS = "md:col-span-2 xl:col-span-1";

/** Mientras el servidor lee: ninguna cifra, ningún cero, ningún «Sin leer». */
function SkeletonCard({ title, className }: { title: string; className?: string }) {
  return (
    <Card data-block={title} data-block-state="reading" className={className}>
      <CardHeader>
        <CardTitle className="text-sm font-semibold">{title}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        <p className="text-sm text-muted-foreground">Leyendo…</p>
        <div aria-hidden className="h-6 w-2/3 animate-pulse rounded bg-muted" />
      </CardContent>
    </Card>
  );
}

async function ActivityAndAreas() {
  const views = await readActivityNow(api);
  return (
    <>
      <ActivityCard view={views.activity} className={COLUMNS} />
      <AreaExecutionsCard view={views.areas} />
    </>
  );
}

export function BottomRow() {
  return (
    <section aria-label="Actividad, ejecuciones e hitos" className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
      <Suspense
        fallback={
          <>
            <SkeletonCard title={ACTIVITY_BLOCK.title} className={COLUMNS} />
            <SkeletonCard title={AREA_BLOCK.title} />
          </>
        }
      >
        <ActivityAndAreas />
      </Suspense>
      <BlockCard title="Próximos hitos" state={unavailableState("El backend no tiene una entidad de hitos: no hay fechas ni estados que enseñar.")} />
    </section>
  );
}
