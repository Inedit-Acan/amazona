import { BlockCard } from "@/components/ceo/block-card";
import { NOT_CONNECTED_YET, unavailableState } from "@/lib/ceo-blocks";

/** La franja inferior del mockup (M47, Commit 2): estructura y estados de lectura, sin porcentajes ni hitos.
 *
 *  · Actividad reciente y Rendimiento por área: existe una fuente (el log de ejecuciones de los agentes) y estos bloques aún no
 *    la han leído → `unread` (Commit 6). El «rendimiento» solo podrá ser, con ese nombre, la tasa de éxito de ejecuciones por
 *    dominio: el backend no tiene una puntuación de área.
 *  · Próximos hitos: hoy NO existe una entidad de hitos → «No disponible». */
export function BottomRow() {
  return (
    <section aria-label="Actividad, rendimiento e hitos" className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
      <BlockCard
        title="Actividad reciente"
        state={NOT_CONNECTED_YET}
        seeAll={{ href: "/agents", label: "Ver todas" }}
        className="md:col-span-2 xl:col-span-1"
      />
      <BlockCard title="Rendimiento por área" state={NOT_CONNECTED_YET} />
      <BlockCard title="Próximos hitos" state={unavailableState("El backend no tiene una entidad de hitos: no hay fechas ni estados que enseñar.")} />
    </section>
  );
}
