"use client";

import { useMemo } from "react";
import type { CFOReport, EconomicAnalysis, Product, RevenueSummary } from "@/lib/api";
import { marginSummary } from "@/lib/cfo-margin";
import { planView } from "@/lib/cfo-plan";
import { verdictView } from "@/lib/cfo-verdict";
import { periodLabel, type Settled } from "@/lib/revenue-view";
import { PeriodSelect } from "@/components/period-select";
import { PageHeader } from "@/components/page-header";
import type { EntriesRead, OrdersRead } from "./page";
import { CFO_DESCRIPTION, CFO_TITLE } from "./copy";
import {
  CannotComputeCard,
  CoverageCard,
  DeclaredMarginFigures,
  OutsideVerifiedCard,
  PlanCard,
  ReadFailed,
  VerdictCard,
  VerifiedByCurrencyCard,
  VerifiedFigures,
  ZoneHeading,
} from "./cfo-panels";

/** Finanzas y control (M45, Commit 10).
 *
 * Tres zonas, en este orden y sin aritmética entre ellas:
 *
 *   1. REGISTRO VERIFICADO    hechos de pago que el backend registró (ADR 0030)
 *   2. COSTE Y MARGEN DECLARADOS  coste que alguien declaró, con su fuente, y el margen que sale de restarlo
 *   3. PROYECCIÓN (PLAN)      lo que el modelo económico espera, y que no ha ocurrido
 *
 * No hay zona de demostración: las tarjetas que se sostenían sobre constantes (caja, runway, impuestos, tesorería,
 * cuentas a pagar y cobrar, cash flow, desviaciones, alertas) se retiraron en lugar de disfrazarse de dato. Lo que la
 * pantalla no puede calcular lo dice en voz alta una vez, al final. */
export function CfoWorkspace({
  days,
  summary,
  entries,
  orders,
  products,
  analyses,
  planUnread,
  report,
  verdictUnread,
}: {
  days: number;
  summary: Settled<RevenueSummary>;
  entries: Settled<EntriesRead>;
  orders: Settled<OrdersRead>;
  products: Product[];
  analyses: [string, EconomicAnalysis][];
  planUnread: number;
  verdictUnread: boolean;
  report?: CFOReport;
}) {
  // El margen necesita las dos lecturas: las entradas del registro y los pedidos. Si falta cualquiera, no hay margen y
  // la pantalla dice cuál falló — nunca se rellena con otra cosa.
  const margin = useMemo(() => {
    if (!entries.ok || !orders.ok) return null;
    return marginSummary(entries.data.entries, orders.data.orders, {
      entriesComplete: entries.data.complete && orders.data.complete,
    });
  }, [entries, orders]);

  const plan = useMemo(() => planView(products, new Map(analyses), planUnread), [products, analyses, planUnread]);
  const verdict = useMemo(() => (report === undefined ? null : verdictView(report)), [report]);
  const period = periodLabel(days);

  return (
    <div className="space-y-4">
      <PageHeader
        title={CFO_TITLE}
        description={CFO_DESCRIPTION}
        actions={<PeriodSelect days={days} label="Periodo de las finanzas" />}
      />

      <section className="space-y-3" aria-label="Registro verificado">
        <ZoneHeading step={1} title={`Registro verificado · ${period}`} provenance="verified">
          Hechos de pago verificados y registrados por el backend. No dicen si la operación fue simulada: el registro
          todavía no guarda esa procedencia.
        </ZoneHeading>
        <VerifiedFigures summary={summary} />
        <div className="grid gap-3 lg:grid-cols-2">
          <VerifiedByCurrencyCard summary={summary} />
          <OutsideVerifiedCard summary={summary} />
        </div>
      </section>

      <section className="space-y-3" aria-label="Coste y margen declarados">
        <ZoneHeading step={2} title={`Coste y margen declarados · ${period}`} provenance="declared">
          El coste de cada línea de pedido, tal como lo declaró una cotización o una persona, y el margen de contribución
          que sale de restarlo del neto verificado. Sólo existe con cobertura del 100 %: una línea sin coste no vale cero.
        </ZoneHeading>
        {margin === null ? (
          <ReadFailed
            what="el coste declarado de los pedidos"
            message={!entries.ok ? entries.message : !orders.ok ? orders.message : "Error desconocido"}
          />
        ) : (
          <>
            <DeclaredMarginFigures margin={margin} />
            <CoverageCard margin={margin} />
          </>
        )}
      </section>

      <section className="space-y-3" aria-label="Proyección">
        <ZoneHeading step={3} title="Proyección (PLAN)" provenance="planned">
          Lo que el modelo económico espera si sus supuestos se cumplen. No ha ocurrido y no se suma con nada de las zonas
          anteriores.
        </ZoneHeading>
        <PlanCard plan={plan} />
      </section>

      <section className="space-y-3" aria-label="Evaluación del agente CFO">
        <div className="border-t pt-4">
          <h2 className="text-sm font-semibold tracking-tight">Evaluación del agente</h2>
          <p className="mt-1 max-w-3xl text-[11px] text-muted-foreground">
            Un veredicto sobre los análisis del catálogo, no una magnitud financiera. Va aparte a propósito.
          </p>
        </div>
        <VerdictCard verdict={verdict} unread={verdictUnread} />
        <CannotComputeCard />
      </section>
    </div>
  );
}
