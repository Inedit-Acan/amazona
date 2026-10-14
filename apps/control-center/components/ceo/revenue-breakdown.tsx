"use client";

import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetDescription, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import {
  INGRESOS_NO_SUM_NOTE,
  INGRESOS_NOT_SETTLED_NOTE,
  OUTSIDE_FIGURE_TEXT,
  type IngresosLine,
  type IngresosSecondary,
  type IngresosView,
} from "@/lib/ceo-kpis";

/** «Ver desglose» de la tarjeta de Ingresos (M47, 3A): TODAS las líneas (origen × moneda) y TODO lo que queda fuera de la cifra, con sus
 * importes y recuentos completos. La tarjeta es compacta y sus líneas hacen scroll; aquí no se esconde nada. Se abre con el teclado
 * (Intro o Espacio en el botón), atrapa el foco, se cierra con `Esc` y devuelve el foco al botón. Ninguna cifra se suma ni se convierte. */

const plural = (count: number, one: string, many: string) => (count === 1 ? one : many);

function LineDetail({ line }: { line: IngresosLine }) {
  return (
    <li data-breakdown-line={line.key} className="space-y-1 rounded-lg border p-3">
      <h4 className="text-sm font-semibold">
        {line.currency} · {line.origin}
      </h4>
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs">
        <dt className="text-muted-foreground">Ingresos</dt>
        <dd className="text-right tabular-nums">{line.revenue}</dd>
        <dt className="text-muted-foreground">Reembolsos</dt>
        <dd className="text-right tabular-nums">{line.refunds}</dd>
        <dt className="text-muted-foreground">Neto</dt>
        <dd className="text-right font-semibold tabular-nums">{line.net}</dd>
        <dt className="text-muted-foreground">Cobros</dt>
        <dd className="text-right tabular-nums">{line.captures}</dd>
        <dt className="text-muted-foreground">Reembolsos (nº)</dt>
        <dd className="text-right tabular-nums">{line.refundCount}</dd>
      </dl>
    </li>
  );
}

function OutsideFigure({ secondary }: { secondary: IngresosSecondary }) {
  return (
    <section aria-label={OUTSIDE_FIGURE_TEXT} data-section="fuera-de-la-cifra" className="space-y-2">
      <h3 className="text-sm font-medium">{OUTSIDE_FIGURE_TEXT}</h3>
      <ul className="space-y-1 text-xs text-muted-foreground">
        {secondary.underReview.map((line) => (
          <li key={line.key}>
            {line.label} · {line.currency} · {line.origin}: {line.amount}
          </li>
        ))}
        {secondary.pending.map((line) => (
          <li key={line.key}>
            {line.label} · {line.currency} · {line.origin}: {line.count} {plural(line.count, "evento", "eventos")} · {line.amount}
          </li>
        ))}
        {secondary.pending.length === 0 && secondary.pendingCount > 0 ? (
          <li>
            {secondary.pendingCount} {plural(secondary.pendingCount, "evento de pago sin asentar", "eventos de pago sin asentar")}
          </li>
        ) : null}
        {secondary.notes.map((note) => (
          <li key={note}>{note}</li>
        ))}
      </ul>
    </section>
  );
}

export function RevenueBreakdown({ view }: { view: Exclude<IngresosView, { kind: "error" }> }) {
  return (
    <Sheet>
      <SheetTrigger render={<Button type="button" variant="outline" size="xs" className="h-5 px-1.5 text-[11px]" />}>
        Ver desglose{view.kind === "loaded" && view.lines.length > 1 ? ` (${view.lines.length})` : ""}
      </SheetTrigger>
      <SheetContent side="right" className="gap-0 overflow-y-auto sm:max-w-md">
        <div className="space-y-5 p-4">
          <div className="space-y-1">
            <SheetTitle>Ingresos · desglose</SheetTitle>
            <SheetDescription>
              {view.periodText}. {INGRESOS_NOT_SETTLED_NOTE} {INGRESOS_NO_SUM_NOTE}
            </SheetDescription>
          </div>
          <section aria-label="Ingresos verificados" className="space-y-2">
            <h3 className="text-sm font-medium">Ingresos verificados</h3>
            {view.kind === "loaded" ? (
              <ul className="space-y-2">
                {view.lines.map((line) => (
                  <LineDetail key={line.key} line={line} />
                ))}
              </ul>
            ) : (
              <p className="text-xs text-muted-foreground">Sin datos: ningún ingreso verificado en este periodo.</p>
            )}
          </section>
          <OutsideFigure secondary={view.secondary} />
        </div>
      </SheetContent>
    </Sheet>
  );
}
