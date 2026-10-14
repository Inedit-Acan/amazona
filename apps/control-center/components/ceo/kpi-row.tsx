import { Ban, CircleDashed } from "lucide-react";
import { KpiCard } from "@/components/kpi-card";
import { blockNotice, NOT_CONNECTED_YET, unavailableState, type BlockState } from "@/lib/ceo-blocks";

/** Las cuatro posiciones de la fila de KPI del mockup (M47, Commit 2). Aquí solo hay estructura y estados de lectura: NO hay
 * lógica financiera ni cifras (Commit 3).
 *
 *  · Ingresos: existe una fuente (el registro de ingresos verificados) y este bloque aún no la ha leído → `unread`.
 *  · Beneficio, Margen neto y Cash disponible: hoy NO existe una fuente que los respalde → «No disponible» (D1). El backend
 *    no registra el coste de ventas, los envíos, las comisiones ni los impuestos, ni tiene cuentas ni conciliación de caja.
 * El icono de la esquina distingue los dos estados sin depender del color: círculo discontinuo = sin leer; prohibido = no disponible. */
interface Kpi {
  key: string;
  label: string;
  state: BlockState<unknown>;
  /** La frase corta que sale en la tarjeta; el motivo completo (`state`) es lo que queda documentado en el estado. */
  caption: string;
}

const KPIS: Kpi[] = [
  { key: "ingresos", label: "Ingresos", state: NOT_CONNECTED_YET, caption: "Este bloque aún no ha leído su fuente." },
  {
    key: "beneficio",
    label: "Beneficio",
    state: unavailableState("Falta una fuente de costes completa: el backend no registra coste de ventas, envíos, comisiones ni impuestos."),
    caption: "Falta una fuente de costes completa.",
  },
  {
    key: "margen",
    label: "Margen neto",
    state: unavailableState("Depende del beneficio, que hoy no puede calcularse."),
    caption: "Depende del beneficio.",
  },
  {
    key: "cash",
    label: "Cash disponible",
    state: unavailableState("No hay fuente de caja: el backend no tiene cuentas ni conciliación."),
    caption: "No hay fuente de caja.",
  },
];

export function KpiRow() {
  return (
    <section aria-label="Indicadores financieros" className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
      {KPIS.map(({ key, label, state, caption }) => {
        const notice = blockNotice(state)!;
        return (
          <div key={key} data-block-state={notice.kind} data-kpi={key} className="contents">
            <KpiCard
              label={label}
              value={notice.label}
              caption={caption}
              icon={notice.kind === "unread" ? CircleDashed : Ban}
              compact
            />
          </div>
        );
      })}
    </section>
  );
}
