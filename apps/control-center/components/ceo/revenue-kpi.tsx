import { Inbox, ReceiptText, TriangleAlert } from "lucide-react";
import { RevenueBreakdown } from "@/components/ceo/revenue-breakdown";
import { DataProvenanceBadge } from "@/components/data-provenance-badge";
import { OriginBadge } from "@/components/origin-badge";
import { PeriodSelect } from "@/components/period-select";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { api } from "@/lib/api-server";
import {
  hasSecondary,
  INGRESOS_NOT_SETTLED_NOTE,
  linesCountText,
  readIngresos,
  secondarySummary,
  type IngresosLine,
  type IngresosView,
} from "@/lib/ceo-kpis";
import { originMeaning, summarizeOrigins } from "@/lib/provenance";
import { READ_UNAVAILABLE_VALUE } from "@/lib/read-state";
import type { RevenueWindow } from "@/lib/revenue-query";
import { cn } from "@/lib/utils";

/** La tarjeta de Ingresos del Director ejecutivo (M47, Commit 3A). Es una tarjeta propia, no un `KpiCard`: un `KpiCard` tiene UNA cifra, y
 * aquí hay una por origen × moneda. La única lectura (`GET /api/revenue/summary?from=&to=`) la hace este componente de servidor, y el
 * selector 7 / 14 / 30 días vive aquí dentro y solo gobierna esta tarjeta: ningún otro bloque depende de él.
 *
 *  · Es COMPACTA: no rompe la altura de la fila de KPI. Una línea ⇒ cifra grande. Varias ⇒ filas compactas de la misma jerarquía
 *    (ninguna se elige como principal) en un área con scroll de alto fijo, con el recuento de líneas a la vista.
 *  · Lo que queda fuera de la cifra (en revisión, pendiente, monedas sin conversión) es un resumen de una línea con recuentos reales;
 *    el detalle completo, y todas las líneas con sus importes, están en «Ver desglose» (se abre con el teclado).
 *  · `empty` ⇒ «Sin datos»; `error` ⇒ «No disponible» + el motivo. Nunca un cero. */

const LEDGER_TOOLTIP = `Hechos de pago verificados y registrados por el backend (ADR 0030): no es un modelo ni una estimación. Cada cifra lleva el origen que el backend guardó en el hecho. Periodo en días naturales UTC. ${INGRESOS_NOT_SETTLED_NOTE}`;

const plural = (count: number, one: string, many: string) => (count === 1 ? one : many);

function countsOf(line: IngresosLine): string {
  return `${line.captures} ${plural(line.captures, "cobro", "cobros")}${
    line.refundCount > 0 ? ` · ${line.refundCount} ${plural(line.refundCount, "reembolso", "reembolsos")}` : ""
  }`;
}

function Line({ line, big }: { line: IngresosLine; big: boolean }) {
  const origin = summarizeOrigins([line.providerKind]);
  // Una sola línea: la cifra grande, con el origen como etiqueta y el resumen de ingresos / reembolsos / neto.
  if (big) {
    return (
      <li data-line={line.key} className="min-w-0 space-y-0.5">
        <div className="flex flex-wrap items-center gap-1.5 text-xs">
          <span className="font-semibold">{line.currency}</span>
          <OriginBadge summary={origin} />
        </div>
        <p className="text-2xl leading-tight font-semibold tabular-nums">{line.revenue}</p>
        <p className="text-[11px] leading-snug text-muted-foreground">
          Reembolsos {line.refunds} · Neto {line.net} · {countsOf(line)}
        </p>
      </li>
    );
  }
  // Varias: filas compactas, todas con la misma jerarquía (moneda, procedencia, ingresos; reembolsos y neto en la segunda línea).
  return (
    <li data-line={line.key} title={countsOf(line)} className="min-w-0 space-y-0.5 border-b pb-1.5 last:border-b-0 last:pb-0">
      <div className="flex flex-wrap items-baseline justify-between gap-x-2">
        <span className="text-[11px] text-muted-foreground" title={originMeaning(origin)}>
          <span className="font-semibold text-foreground">{line.currency}</span> · {line.origin}
        </span>
        <span className="text-sm leading-tight font-semibold tabular-nums">{line.revenue}</span>
      </div>
      <p className="text-[11px] leading-snug text-muted-foreground">
        Reembolsos {line.refunds} · Neto {line.net}
      </p>
    </li>
  );
}

function Body({ view }: { view: IngresosView }) {
  if (view.kind === "error") {
    return (
      <div className="space-y-1">
        <p className="text-xl leading-tight font-semibold">{READ_UNAVAILABLE_VALUE}</p>
        <p className="text-xs text-destructive">{view.message}</p>
      </div>
    );
  }
  if (view.kind === "empty") {
    return (
      <div className="space-y-1">
        <p className="text-xl leading-tight font-semibold">Sin datos</p>
        <p className="text-xs text-muted-foreground">Ningún ingreso verificado en los {view.periodText}.</p>
      </div>
    );
  }
  if (view.lines.length === 1) {
    return (
      <ul>
        <Line line={view.lines[0]} big />
      </ul>
    );
  }
  return (
    // Área con scroll de alto fijo SOLO para las líneas; foco visible y alcanzable por teclado. «Ver desglose (N)» dice cuántas hay y las
    // muestra todas.
    <ul
      tabIndex={0}
      aria-label={`Ingresos por origen y moneda: ${linesCountText(view.lines.length)}`}
      className="max-h-[6rem] space-y-2 overflow-y-auto rounded-sm pr-1 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
    >
      {view.lines.map((line) => (
        <Line key={line.key} line={line} big={view.lines.length === 1} />
      ))}
    </ul>
  );
}

export function RevenueKpiCard({ view, days }: { view: IngresosView; days: number }) {
  const Icon = view.kind === "error" ? TriangleAlert : view.kind === "empty" ? Inbox : ReceiptText;
  const summary = view.kind === "error" ? null : secondarySummary(view.secondary);
  const multi = view.kind === "loaded" && view.lines.length > 1;
  const showBreakdown = view.kind !== "error" && (multi || hasSecondary(view.secondary));
  return (
    <Card data-kpi="ingresos" data-block-state={view.kind} className="min-w-0">
      <CardHeader className="flex flex-row items-center justify-between gap-2 pb-0">
        <CardTitle className="text-sm font-medium text-muted-foreground">Ingresos</CardTitle>
        <Icon aria-hidden className={cn("size-4 shrink-0", view.kind === "error" ? "text-destructive" : "text-primary")} />
      </CardHeader>
      <CardContent className="space-y-2">
        {/* El selector es el de Panel y Finanzas; su anillo de foco visible se pone aquí, sin tocar el componente compartido. */}
        <div className="[&_select:focus-visible]:ring-2 [&_select:focus-visible]:ring-ring [&_select:focus-visible]:outline-none">
          <PeriodSelect days={days} />
        </div>
        <Body view={view} />
        {summary ? (
          <p data-section="fuera-de-la-cifra" className="text-[11px] leading-snug text-muted-foreground">
            {summary}
          </p>
        ) : null}
        {view.kind !== "error" ? (
          <div className="flex flex-wrap items-center justify-between gap-1.5">
            <div className="flex flex-wrap items-center gap-1.5">
              <DataProvenanceBadge status="ledger" compact tooltip={LEDGER_TOOLTIP} />
              {multi ? null : <span className="text-[11px] text-muted-foreground">{view.periodText}</span>}
            </div>
            {showBreakdown ? <RevenueBreakdown view={view} /> : null}
          </div>
        ) : null}
        {view.kind !== "error" && !multi ? <p className="text-[11px] text-muted-foreground">{INGRESOS_NOT_SETTLED_NOTE}</p> : null}
      </CardContent>
    </Card>
  );
}

/** Mientras el servidor lee: ninguna cifra, ningún cero. */
export function RevenueKpiSkeleton() {
  return (
    <Card data-kpi="ingresos" data-block-state="reading" aria-busy="true" className="min-w-0">
      <CardHeader className="flex flex-row items-center justify-between gap-2 pb-0">
        <CardTitle className="text-sm font-medium text-muted-foreground">Ingresos</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        <p className="text-sm text-muted-foreground">Leyendo ingresos…</p>
        <div aria-hidden className="h-6 w-2/3 animate-pulse rounded bg-muted" />
      </CardContent>
    </Card>
  );
}

export async function RevenueKpi({ window, days }: { window: RevenueWindow; days: number }) {
  const view = await readIngresos(api, window, days);
  return <RevenueKpiCard view={view} days={days} />;
}
