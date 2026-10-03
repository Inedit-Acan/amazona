"use client";

import { useMemo, useRef, useState, useTransition } from "react";
import { usePathname, useRouter } from "next/navigation";
import { AlertTriangle, Loader2, ReceiptText } from "lucide-react";
import { api, ApiError, type RevenueEntriesPage, type RevenueSeries, type RevenueSummary } from "@/lib/api";
import { parseUtc } from "@/lib/dates";
import { formatInteger } from "@/lib/format";
import { REVENUE_ENTRIES_PAGE_SIZE, REVENUE_PERIODS, type RevenueWindow } from "@/lib/revenue-query";
import {
  appendEntries,
  dayLabel,
  entriesFromPage,
  entriesSummaryText,
  entryRow,
  periodLabel,
  REVENUE_SCOPE_NOTE,
  revenueErrorText,
  seriesView,
  summaryView,
  type EntriesLoaded,
  type Settled,
} from "@/lib/revenue-view";
import { DataProvenanceBadge } from "@/components/data-provenance-badge";
import { EmptyState } from "@/components/empty-state";
import { LevelChip } from "@/components/level-chip";
import { RevenueBars } from "@/components/revenue-bars";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

const DAY_MS = 86_400_000;

/** Qué demuestra el backend detrás de estas cifras, y qué NO demuestra. */
const LEDGER_TOOLTIP =
  "Hechos de pago verificados y registrados por el backend (ADR 0030): no es un modelo ni una estimación. No dice si la operación fue simulada — el registro todavía no guarda esa procedencia.";

/** Un error de lectura se enseña como error. Nunca se sustituye por datos de demostración. */
export function RevenueUnavailable({ what, message }: { what: string; message: string }) {
  return (
    <Alert variant="destructive">
      <AlertTriangle className="size-4" />
      <AlertTitle>No se pudo leer {what}</AlertTitle>
      <AlertDescription>
        {message} No se ha sustituido por datos de demostración: la cifra no se conoce hasta que la lectura funcione.
      </AlertDescription>
    </Alert>
  );
}

// --- Periodo (lectura: solo cambia la URL, el servidor vuelve a leer) --------------------------------------------

export function PeriodSelect({ days }: { days: number }) {
  const router = useRouter();
  const pathname = usePathname();
  const [pending, startTransition] = useTransition();
  return (
    <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
      {pending ? <Loader2 className="size-3.5 animate-spin" aria-hidden /> : null}
      <span className="sr-only">Periodo de los ingresos</span>
      <select
        value={days}
        aria-label="Periodo de los ingresos"
        onChange={(event) => {
          const next = Number(event.target.value);
          startTransition(() => router.replace(`${pathname}?dias=${next}`, { scroll: false }));
        }}
        className="rounded-md border bg-background px-2 py-1 text-xs text-foreground"
      >
        {REVENUE_PERIODS.map((value) => (
          <option key={value} value={value}>
            Ingresos: {periodLabel(value)}
          </option>
        ))}
      </select>
    </label>
  );
}

// --- Ingresos por día ---------------------------------------------------------------------------------------------

export function RevenueSeriesCard({
  series,
  window,
  days,
}: {
  series: Settled<RevenueSeries>;
  window: RevenueWindow;
  days: number;
}) {
  const [chosen, setChosen] = useState<string | null>(null);
  const view = useMemo(
    () => (series.ok ? seriesView(series.data, window.from, window.to) : null),
    [series, window.from, window.to],
  );
  const currency = view && (chosen && view.currencies.includes(chosen) ? chosen : view.currencies[0]);
  const current = view && currency ? view.byCurrency[currency] : null;
  const fromMs = Date.parse(window.from);

  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2">
          Ingresos verificados por día · {periodLabel(days)}
          <DataProvenanceBadge status="ledger" compact tooltip={LEDGER_TOOLTIP} />
        </CardTitle>
        {view && view.currencies.length > 1 ? (
          <CardAction>
            <select
              value={currency ?? ""}
              onChange={(event) => setChosen(event.target.value)}
              aria-label="Moneda de la serie"
              className="rounded-md border bg-background px-2 py-1 text-xs"
            >
              {view.currencies.map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </select>
          </CardAction>
        ) : null}
      </CardHeader>
      <CardContent className="space-y-2.5">
        {!series.ok ? (
          <RevenueUnavailable what="la serie de ingresos" message={series.message} />
        ) : !current || !view ? (
          <EmptyState
            icon={ReceiptText}
            title="Sin ingresos registrados"
            description="No hay ninguna entrada en el registro dentro de este periodo. No es un cero: es ausencia de datos."
          />
        ) : (
          <>
            <RevenueBars
              days={view.windowDays}
              bars={current.columns.map((column) => ({
                x: column.x,
                value: column.plot,
                text: column.revenueText,
                label: column.label,
              }))}
              formatY={(value) => formatInteger(value)}
              formatX={(x) => dayLabel(fromMs + x * DAY_MS)}
              ariaLabel={`Ingresos verificados por día en ${current.currency}, ${periodLabel(days)}`}
            />
            <p className="text-[11px] text-muted-foreground">
              Serie en {current.currency}. Los días sin barra no tienen ninguna entrada: sin datos, no cero. Las monedas no se
              suman ni se convierten.
            </p>
            <div className="max-h-56 overflow-auto">
              <Table className="[&_td]:px-2 [&_td]:py-1.5">
                <TableHeader>
                  <TableRow className="hover:bg-transparent">
                    <TableHead>Día (UTC)</TableHead>
                    <TableHead className="text-right">Ingresos</TableHead>
                    <TableHead className="text-right">Reembolsos</TableHead>
                    <TableHead className="text-right">Neto</TableHead>
                    <TableHead className="text-right" title="Todas las entradas del día, también las que están en revisión">
                      Entradas (todas)
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {current.rows.map((row) => (
                    <TableRow key={row.bucket}>
                      <TableCell className="whitespace-nowrap">{row.bucket}</TableCell>
                      <TableCell className="text-right tabular-nums">{row.revenue}</TableCell>
                      <TableCell className="text-right tabular-nums">{row.refunds}</TableCell>
                      <TableCell className="text-right tabular-nums">{row.net}</TableCell>
                      <TableCell className="text-right tabular-nums">{row.entries}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}

// --- Verificado por moneda ----------------------------------------------------------------------------------------

export function RevenueBreakdownCard({ summary, days }: { summary: Settled<RevenueSummary>; days: number }) {
  const view = useMemo(() => (summary.ok ? summaryView(summary.data) : null), [summary]);
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2">
          Verificado por moneda · {periodLabel(days)}
          <DataProvenanceBadge status="ledger" compact tooltip={LEDGER_TOOLTIP} />
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2.5">
        {!summary.ok ? (
          <RevenueUnavailable what="el resumen de ingresos" message={summary.message} />
        ) : view && view.verified.length === 0 ? (
          <EmptyState
            icon={ReceiptText}
            title="Sin ingresos verificados"
            description="No hay cobros verificados en este periodo. El registro solo recoge cobros confirmados: no se muestra un cero inventado."
          />
        ) : (
          <div className="overflow-x-auto">
            <Table className="[&_td]:px-2 [&_td]:py-2">
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <TableHead>Moneda</TableHead>
                  <TableHead className="text-right">Ingresos</TableHead>
                  <TableHead className="text-right">Reembolsos</TableHead>
                  <TableHead className="text-right">Neto</TableHead>
                  <TableHead className="text-right">Cobros</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {view?.verified.map((row) => (
                  <TableRow key={row.currency}>
                    <TableCell className="font-medium">{row.currency}</TableCell>
                    <TableCell className="text-right tabular-nums">{row.revenue}</TableCell>
                    <TableCell className="text-right tabular-nums">{row.refunds}</TableCell>
                    <TableCell className="text-right tabular-nums">{row.net}</TableCell>
                    <TableCell className="text-right tabular-nums">
                      {row.captures} · {row.refundCount} reemb.
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
        {view && view.otherCurrencies.length > 0 ? (
          <p className="text-[11px] text-muted-foreground">
            {view.otherCurrencies.join(", ")}: monedas distintas de EUR. Cada una va en su línea y no se suma ni se convierte a
            ninguna otra.
          </p>
        ) : null}
        <p className="text-[11px] text-muted-foreground">{REVENUE_SCOPE_NOTE}</p>
      </CardContent>
    </Card>
  );
}

// --- Lo que NO es ingreso verificado ------------------------------------------------------------------------------

export function OutsideVerifiedCard({ summary, days }: { summary: Settled<RevenueSummary>; days: number }) {
  const view = useMemo(() => (summary.ok ? summaryView(summary.data) : null), [summary]);
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2">
          Fuera de lo verificado · {periodLabel(days)}
          <DataProvenanceBadge status="ledger" compact tooltip={LEDGER_TOOLTIP} />
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {!summary.ok || !view ? (
          <RevenueUnavailable what="el dinero en revisión y la evidencia pendiente" message={summary.ok ? "" : summary.message} />
        ) : (
          <>
            <section aria-label="Dinero en revisión" className="space-y-1.5">
              <h3 className="text-sm font-medium">Dinero en revisión</h3>
              {view.underReview.length === 0 ? (
                <p className="text-xs text-muted-foreground">Ningún cobro duplicado ni con discrepancia en este periodo.</p>
              ) : (
                <div className="overflow-x-auto">
                  <Table className="[&_td]:px-2 [&_td]:py-1.5">
                    <TableHeader>
                      <TableRow className="hover:bg-transparent">
                        <TableHead>Clase</TableHead>
                        <TableHead className="text-right">Recibido</TableHead>
                        <TableHead className="text-right">Devuelto</TableHead>
                        <TableHead className="text-right">Pendiente</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {view.underReview.map((row) => (
                        <TableRow key={`${row.currency}-${row.classification}`}>
                          <TableCell className="whitespace-normal">
                            <LevelChip tone="warn">{row.label}</LevelChip>
                          </TableCell>
                          <TableCell className="text-right tabular-nums">{row.received}</TableCell>
                          <TableCell className="text-right tabular-nums">{row.refunded}</TableCell>
                          <TableCell className="text-right tabular-nums">{row.outstanding}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              )}
              <p className="text-[11px] text-muted-foreground">
                Un duplicado o una discrepancia es dinero recibido que aún no se ha resuelto: nunca suma a lo verificado ni se
                compensa con ello.
              </p>
            </section>

            <section aria-label="Evidencia pendiente" className="space-y-1.5">
              <h3 className="text-sm font-medium">Evidencia pendiente</h3>
              {view.pendingEvidence.count === 0 ? (
                <p className="text-xs text-muted-foreground">Ningún evento de pago sin asentar.</p>
              ) : (
                <ul className="divide-y text-xs">
                  {view.pendingEvidence.lines.map((line) => (
                    <li key={`${line.currency}-${line.label}`} className="flex items-center justify-between gap-3 py-1.5">
                      <span>
                        {line.label} · {line.count}
                      </span>
                      <span className="tabular-nums">{line.amount}</span>
                    </li>
                  ))}
                </ul>
              )}
              <p className="text-[11px] text-muted-foreground">
                Eventos de pago que no se pudieron asentar. No son ingreso ni reembolso y no entran en ningún total.
              </p>
            </section>
          </>
        )}
      </CardContent>
    </Card>
  );
}

// --- Entradas que explican las cifras, por cursor -----------------------------------------------------------------

function formatMoment(value: string): string {
  return `${new Date(parseUtc(value)).toLocaleString("es-ES", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "UTC",
  })} UTC`;
}

export function RevenueEntriesCard({
  initial,
  window,
  days,
}: {
  initial: Settled<RevenueEntriesPage>;
  window: RevenueWindow;
  days: number;
}) {
  const [loaded, setLoaded] = useState<EntriesLoaded | null>(() => (initial.ok ? entriesFromPage(initial.data) : null));
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const inFlight = useRef(false);

  async function loadMore() {
    if (!loaded || inFlight.current || !loaded.hasMore || loaded.nextCursor === null) return;
    inFlight.current = true;
    setLoading(true);
    setLoadError(null);
    try {
      const page = await api.revenueEntries({ window, cursor: loaded.nextCursor, limit: REVENUE_ENTRIES_PAGE_SIZE });
      setLoaded((current) => (current ? appendEntries(current, page) : entriesFromPage(page)));
    } catch (err) {
      setLoadError(
        err instanceof ApiError
          ? revenueErrorText(err.status, err.detail)
          : revenueErrorText(undefined, err instanceof Error ? err.message : "error desconocido"),
      );
    } finally {
      inFlight.current = false;
      setLoading(false);
    }
  }

  const rows = useMemo(() => (loaded ? loaded.items.map(entryRow) : []), [loaded]);

  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2">
          Entradas del registro · {periodLabel(days)}
          <DataProvenanceBadge status="ledger" compact tooltip={LEDGER_TOOLTIP} />
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2.5">
        {!initial.ok || !loaded ? (
          <RevenueUnavailable what="las entradas del registro" message={initial.ok ? "" : initial.message} />
        ) : rows.length === 0 ? (
          <EmptyState
            icon={ReceiptText}
            title="Sin entradas"
            description="No hay ninguna entrada en el registro de ingresos dentro de este periodo."
          />
        ) : (
          <div className="overflow-x-auto">
            <Table className="[&_td]:px-2 [&_td]:py-1.5">
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <TableHead>Fecha</TableHead>
                  <TableHead>Tipo</TableHead>
                  <TableHead>Clase</TableHead>
                  <TableHead className="text-right">Importe</TableHead>
                  <TableHead>Pedido</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((row) => (
                  <TableRow key={row.id}>
                    <TableCell className="whitespace-nowrap">{formatMoment(row.occurredAt)}</TableCell>
                    <TableCell>{row.kindLabel}</TableCell>
                    <TableCell>
                      <LevelChip tone={row.verified ? "ok" : "warn"}>{row.classificationLabel}</LevelChip>
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{row.amount}</TableCell>
                    <TableCell className="whitespace-nowrap" title={row.orderId}>
                      #{row.orderId.slice(0, 8)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
        {loaded ? (
          <div className="flex flex-wrap items-center justify-between gap-3 text-xs text-muted-foreground">
            <p data-testid="revenue-entries-summary">{entriesSummaryText(loaded)}</p>
            {loaded.hasMore ? (
              <Button variant="outline" size="sm" onClick={loadMore} disabled={loading}>
                {loading ? <Loader2 className="size-4 animate-spin" aria-hidden /> : null}
                {loading ? "Cargando…" : "Cargar entradas más antiguas"}
              </Button>
            ) : null}
          </div>
        ) : null}
        {loadError ? (
          <Alert variant="destructive">
            <AlertTriangle className="size-4" />
            <AlertTitle>No se pudo cargar la página siguiente</AlertTitle>
            <AlertDescription>{loadError}</AlertDescription>
          </Alert>
        ) : null}
        <p className="text-[11px] text-muted-foreground">
          Las entradas explican cualquier cifra de arriba: de la más reciente a la más antigua, sin repetir ni saltar ninguna.
        </p>
      </CardContent>
    </Card>
  );
}
