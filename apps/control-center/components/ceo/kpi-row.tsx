import Link from "next/link";
import { Suspense } from "react";
import { Ban } from "lucide-react";
import { RevenueKpi, RevenueKpiSkeleton } from "@/components/ceo/revenue-kpi";
import { KpiCard } from "@/components/kpi-card";
import { blockNotice } from "@/lib/ceo-blocks";
import { UNAVAILABLE_KPIS } from "@/lib/ceo-kpis";
import type { RevenueWindow } from "@/lib/revenue-query";

/** Las cuatro posiciones de la fila de KPI del mockup (M47, Commit 3A).
 *
 *  · Ingresos: se lee del registro de ingresos verificados (`GET /api/revenue/summary`), por origen × moneda, con el selector
 *    7 / 14 / 30 días dentro de la propia tarjeta. Es el ÚNICO bloque que depende del periodo.
 *  · Beneficio, Margen neto y Cash disponible: hoy NO existe una fuente que los respalde → «No disponible», sin cifra y sin derivarlos
 *    de Ingresos (`lib/ceo-kpis.ts` guarda el motivo de cada uno). El enlace de Beneficio a Finanzas no dice que la cifra exista.
 * El icono de la esquina de las tarjetas «no disponible» es un círculo prohibido; la de Ingresos pinta el suyo según su estado. */
export function KpiRow({ window, days }: { window: RevenueWindow; days: number }) {
  return (
    <section aria-label="Indicadores financieros" className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4 items-start">
      <Suspense fallback={<RevenueKpiSkeleton />}>
        <RevenueKpi window={window} days={days} />
      </Suspense>
      {UNAVAILABLE_KPIS.map(({ key, label, state, caption, link }) => {
        const notice = blockNotice(state)!;
        return (
          <div key={key} data-block-state={notice.kind} data-kpi={key} className="contents">
            <KpiCard
              label={label}
              value={notice.label}
              caption={caption}
              icon={Ban}
              compact
              footer={
                link ? (
                  <Link
                    href={link.href}
                    className="inline-block rounded-sm text-xs text-muted-foreground underline-offset-2 transition-colors hover:text-foreground hover:underline focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
                  >
                    {link.label}
                  </Link>
                ) : undefined
              }
            />
          </div>
        );
      })}
    </section>
  );
}
