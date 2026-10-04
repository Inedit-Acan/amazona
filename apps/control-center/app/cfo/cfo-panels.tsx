"use client";

import type { ReactNode } from "react";
import { AlertTriangle, Coins, Database, FileSignature, FlaskConical, LineChart, ReceiptText } from "lucide-react";
import type { RevenueSummary } from "@/lib/api";
import { amountText, coverageText, BLOCKED_TEXT, type MarginSummary, type OrderMargin } from "@/lib/cfo-margin";
import { PLAN_BLOCKED_TEXT, PLAN_NOTE, type PlanView } from "@/lib/cfo-plan";
import { NO_VERDICT_TEXT, UNREAD_VERDICT_TEXT, type VerdictView } from "@/lib/cfo-verdict";
import { PROVENANCE_MEANING, type Provenance } from "@/lib/provenance";
import { formatMoney, NO_DATA, summaryView, UNREAD, type Settled } from "@/lib/revenue-view";
import { DataProvenanceBadge, type DataProvenance } from "@/components/data-provenance-badge";
import { EmptyState } from "@/components/empty-state";
import { LevelChip, type LevelTone } from "@/components/level-chip";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { cn } from "@/lib/utils";

/** El vocabulario de procedencia de `lib/provenance.ts`, con la etiqueta que lo pinta. */
const BADGE: Record<Provenance, DataProvenance> = {
  verified: "ledger",
  declared: "declared",
  planned: "planned",
  demo: "demo",
};

const ZONE_ICON: Record<Provenance, typeof Database> = {
  verified: Database,
  declared: FileSignature,
  planned: LineChart,
  demo: FlaskConical,
};

/** Cada zona se abre con su procedencia, para que nadie tenga que adivinar qué está mirando. */
export function ZoneHeading({
  step,
  title,
  provenance,
  children,
}: {
  step: number;
  title: string;
  provenance: Provenance;
  children?: ReactNode;
}) {
  const Icon = ZONE_ICON[provenance];
  return (
    <div className="flex flex-wrap items-start justify-between gap-2 border-t pt-4">
      <div className="min-w-0">
        <h2 className="flex items-center gap-2 text-sm font-semibold tracking-tight">
          <Icon className="size-4 shrink-0 text-primary" />
          <span className="text-muted-foreground tabular-nums">{step}</span>
          {title}
        </h2>
        {children ? <p className="mt-1 max-w-3xl text-[11px] text-muted-foreground">{children}</p> : null}
      </div>
      <DataProvenanceBadge status={BADGE[provenance]} tooltip={PROVENANCE_MEANING[provenance]} />
    </div>
  );
}

/** Un error de lectura se enseña como error. Nunca se sustituye por datos de demostración ni por un cero. */
export function ReadFailed({ what, message }: { what: string; message: string }) {
  return (
    <Alert variant="destructive">
      <AlertTriangle className="size-4" />
      <AlertTitle>No se pudo leer {what}</AlertTitle>
      <AlertDescription>
        {message} No se ha sustituido por datos de demostración ni por un cero: la cifra no se conoce hasta que la lectura
        funcione.
      </AlertDescription>
    </Alert>
  );
}

/** Una cifra grande con su procedencia. «Sin datos» se enseña sin acento de número, y la etiqueta nunca desaparece. */
function Figure({
  label,
  value,
  provenance,
  caption,
  accent = false,
}: {
  label: string;
  value: string;
  provenance: Provenance;
  caption?: string;
  accent?: boolean;
}) {
  const noData = value === NO_DATA;
  return (
    <Card className="min-w-0">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">{label}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-1.5">
        <p
          className={cn(
            "text-2xl leading-tight font-semibold break-words",
            !noData && accent && "text-primary",
            noData && "text-base text-muted-foreground",
          )}
        >
          {value}
        </p>
        {caption ? <p className="text-xs text-muted-foreground">{caption}</p> : null}
        <DataProvenanceBadge status={BADGE[provenance]} compact tooltip={PROVENANCE_MEANING[provenance]} />
      </CardContent>
    </Card>
  );
}

// --- Zona 1: registro verificado ----------------------------------------------------------------------------------

export function VerifiedFigures({ summary }: { summary: Settled<RevenueSummary> }) {
  if (!summary.ok) return <ReadFailed what="el registro de ingresos" message={summary.message} />;
  const view = summaryView(summary.data);
  const eur = view.eur;
  const others = view.otherCurrencies.length > 0 ? ` Otras monedas: ${view.otherCurrencies.join(", ")}, aparte.` : "";
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      <Figure
        label="Ingresos verificados"
        value={eur?.revenue ?? NO_DATA}
        provenance="verified"
        accent
        caption={eur ? `Cobros verificados en euros.${others}` : `Ninguna entrada en euros en el periodo.${others}`}
      />
      <Figure
        label="Reembolsos verificados"
        value={eur?.refunds ?? NO_DATA}
        provenance="verified"
        caption={eur ? "Devoluciones confirmadas en euros." : "Ninguna entrada en euros en el periodo."}
      />
      <Figure
        label="Neto verificado"
        value={eur?.net ?? NO_DATA}
        provenance="verified"
        accent
        caption="Ingresos menos reembolsos. Puede ser negativo, y no se oculta."
      />
    </div>
  );
}

export function VerifiedByCurrencyCard({ summary }: { summary: Settled<RevenueSummary> }) {
  if (!summary.ok) return null;
  const view = summaryView(summary.data);
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Por moneda</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2.5">
        {view.verified.length === 0 ? (
          <EmptyState
            icon={ReceiptText}
            title="Sin ingresos verificados"
            description="No hay cobros verificados en este periodo. No es un cero: es ausencia de datos."
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
                </TableRow>
              </TableHeader>
              <TableBody>
                {view.verified.map((row) => (
                  <TableRow key={row.currency}>
                    <TableCell className="font-medium">{row.currency}</TableCell>
                    <TableCell className="text-right tabular-nums">{row.revenue}</TableCell>
                    <TableCell className="text-right tabular-nums">{row.refunds}</TableCell>
                    <TableCell className="text-right tabular-nums">{row.net}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
        <p className="text-[11px] text-muted-foreground">
          Cada moneda va en su línea. Nada se suma ni se convierte entre monedas: sólo el euro se consolida.
        </p>
      </CardContent>
    </Card>
  );
}

export function OutsideVerifiedCard({ summary }: { summary: Settled<RevenueSummary> }) {
  if (!summary.ok) return null;
  const view = summaryView(summary.data);
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Fuera de lo verificado</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-xs">
        <section className="space-y-1.5" aria-label="Dinero en revisión">
          <h3 className="text-sm font-medium">Dinero en revisión</h3>
          {view.underReview.length === 0 ? (
            <p className="text-muted-foreground">Ningún cobro duplicado ni con discrepancia en este periodo.</p>
          ) : (
            <ul className="divide-y">
              {view.underReview.map((row) => (
                <li key={`${row.currency}-${row.classification}`} className="flex items-center justify-between gap-3 py-1.5">
                  <LevelChip tone="warn">{row.label}</LevelChip>
                  <span className="tabular-nums">{row.outstanding}</span>
                </li>
              ))}
            </ul>
          )}
        </section>
        <section className="space-y-1.5" aria-label="Evidencia pendiente">
          <h3 className="text-sm font-medium">Evidencia pendiente</h3>
          {view.pendingEvidence.count === 0 ? (
            <p className="text-muted-foreground">Ningún evento de pago sin asentar.</p>
          ) : (
            <ul className="divide-y">
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
        </section>
        <p className="text-[11px] text-muted-foreground">
          Ninguna de estas dos cifras suma a lo verificado ni entra en el margen: son dinero sin resolver y eventos sin
          asentar.
        </p>
      </CardContent>
    </Card>
  );
}

// --- Zona 2: coste y margen declarados ----------------------------------------------------------------------------

export function DeclaredMarginFigures({ margin }: { margin: MarginSummary }) {
  const reason = margin.blockedBy === null ? null : BLOCKED_TEXT[margin.blockedBy];
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      <Figure
        label="Margen de contribución declarado"
        value={margin.margin === null ? NO_DATA : formatMoney(amountText(margin.margin.value), "EUR")}
        provenance="declared"
        accent
        caption={reason ?? "Neto verificado menos el coste declarado de esos pedidos. No es beneficio."}
      />
      <Figure
        label="Coste declarado"
        value={margin.cost === null ? NO_DATA : formatMoney(amountText(margin.cost.value), "EUR")}
        provenance="declared"
        caption={coverageText(margin.coverage)}
      />
      <Figure
        label="Neto verificado de esos pedidos"
        value={margin.net === null ? NO_DATA : formatMoney(amountText(margin.net.value), "EUR")}
        provenance="verified"
        caption={
          margin.coverage.orders === 0
            ? "Ningún pedido con ingreso verificado en euros."
            : `${margin.coverage.orders} pedido${margin.coverage.orders === 1 ? "" : "s"} con ingreso verificado en euros.`
        }
      />
    </div>
  );
}

export function CoverageCard({ margin }: { margin: MarginSummary }) {
  const rows: OrderMargin[] = margin.orders;
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Cobertura del coste, pedido a pedido</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2.5">
        {rows.length === 0 ? (
          <EmptyState
            icon={FileSignature}
            title="Sin pedidos que medir"
            description="No hay ningún pedido con ingreso verificado en euros dentro de este periodo."
          />
        ) : (
          <div className="max-h-80 overflow-auto">
            <Table className="[&_td]:px-2 [&_td]:py-1.5">
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <TableHead>Pedido</TableHead>
                  <TableHead className="text-right">Neto verificado</TableHead>
                  <TableHead className="text-right">Coste declarado</TableHead>
                  <TableHead className="text-right">Margen</TableHead>
                  <TableHead>Cobertura</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((row) => (
                  <TableRow key={row.orderId}>
                    <TableCell className="whitespace-nowrap" title={row.orderId}>
                      #{row.orderId.slice(0, 8)}
                      {row.isSimulated ? <span className="ml-1 text-[10px] text-muted-foreground">simulado</span> : null}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{formatMoney(amountText(row.net.value), row.currency)}</TableCell>
                    <TableCell className="text-right tabular-nums">
                      {row.cost === null ? (
                        <span className="text-muted-foreground">{NO_DATA}</span>
                      ) : (
                        formatMoney(amountText(row.cost.value), row.currency)
                      )}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {row.margin === null ? (
                        <span className="text-muted-foreground">{NO_DATA}</span>
                      ) : (
                        formatMoney(amountText(row.margin.value), row.currency)
                      )}
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-xs">
                      {row.lines === 0 ? (
                        <LevelChip tone="bad">sin leer</LevelChip>
                      ) : (
                        <span className={row.linesWithCost === row.lines ? "" : "text-warning"}>
                          {row.linesWithCost} / {row.lines} líneas
                          {row.costProvenances.length > 0 ? ` · ${row.costProvenances.join(", ")}` : ""}
                        </span>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
        <p className="text-[11px] text-muted-foreground">
          El coste sale del coste unitario de cada línea, con la fuente que el backend guarda. Una línea sin coste declarado
          no vale cero: deja el pedido sin margen.
          {margin.simulated > 0 ? ` ${margin.simulated} de estos pedidos están marcados como simulados.` : ""}
          {margin.otherCurrencies.length > 0
            ? ` Hay pedidos con ingreso en ${margin.otherCurrencies.join(", ")}: quedan fuera y no se convierten.`
            : ""}
        </p>
      </CardContent>
    </Card>
  );
}

// --- Zona 3: proyección (PLAN) ------------------------------------------------------------------------------------

const RECOMMENDATION_TONE: Record<string, LevelTone> = { GO: "ok", REVIEW: "warn", NO_GO: "bad" };

export function PlanCard({ plan }: { plan: PlanView }) {
  const total = plan.totalPerOrder;
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Margen de contribución proyectado, por producto</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2.5">
        {plan.unread > 0 ? (
          <Alert variant="destructive">
            <AlertTriangle />
            <AlertTitle>{UNREAD} el análisis económico de {plan.unread} producto(s)</AlertTitle>
            <AlertDescription>{PLAN_BLOCKED_TEXT.unread}</AlertDescription>
          </Alert>
        ) : null}
        {plan.rows.length === 0 ? (
          <EmptyState
            icon={LineChart}
            title={plan.unread > 0 ? UNREAD : "Sin análisis económicos"}
            description={
              plan.unread > 0
                ? "El backend no respondió a la lectura: no se sabe si algún producto tiene análisis económico."
                : "Ningún producto del catálogo tiene todavía un análisis económico del que proyectar."
            }
          />
        ) : (
          <>
            <div className="max-h-80 overflow-auto">
              <Table className="[&_td]:px-2 [&_td]:py-1.5">
                <TableHeader>
                  <TableRow className="hover:bg-transparent">
                    <TableHead>Producto</TableHead>
                    <TableHead className="text-right">Por unidad</TableHead>
                    <TableHead className="text-right">Por pedido</TableHead>
                    <TableHead>Decisión</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {plan.rows.map((row) => (
                    <TableRow key={row.productId}>
                      <TableCell className="min-w-40">
                        <span className="block truncate text-sm">{row.name}</span>
                        {row.missing.length > 0 ? (
                          <span className="block text-[11px] text-warning">Falta: {row.missing.join(", ")}</span>
                        ) : null}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {row.perUnit === null ? (
                          <span className="text-muted-foreground">{NO_DATA}</span>
                        ) : (
                          formatMoney(amountText(row.perUnit.value), row.currency ?? "EUR")
                        )}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {row.perOrder === null ? (
                          <span className="text-muted-foreground">{NO_DATA}</span>
                        ) : (
                          formatMoney(amountText(row.perOrder.value), row.currency ?? "EUR")
                        )}
                      </TableCell>
                      <TableCell>
                        <LevelChip tone={RECOMMENDATION_TONE[row.recommendation] ?? "neutral"}>{row.recommendation}</LevelChip>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
            <p className="text-xs">
              Total proyectado por pedido:{" "}
              <span className="font-medium tabular-nums">
                {total === null ? NO_DATA : formatMoney(amountText(total.value), plan.currency ?? "EUR")}
              </span>
              {plan.blockedBy === null ? null : (
                <span className="text-muted-foreground"> · {PLAN_BLOCKED_TEXT[plan.blockedBy]}</span>
              )}
            </p>
          </>
        )}
        <p className="text-[11px] text-muted-foreground">{PLAN_NOTE}</p>
      </CardContent>
    </Card>
  );
}

// --- Evaluación del agente ----------------------------------------------------------------------------------------

const VERDICT_TONE: Record<VerdictView["tone"], LevelTone> = { ok: "ok", warn: "warn", bad: "bad" };

export function VerdictCard({ verdict, unread }: { verdict: VerdictView | null; unread: boolean }) {
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2">
          {verdict === null ? "Evaluación CFO" : verdict.title}
          {verdict === null ? null : <LevelChip tone={VERDICT_TONE[verdict.tone]}>{verdict.status}</LevelChip>}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-xs">
        {verdict === null ? (
          <p className="text-muted-foreground">{unread ? UNREAD_VERDICT_TEXT : NO_VERDICT_TEXT}</p>
        ) : (
          <>
            <p>{verdict.detail}</p>
            <div className="grid gap-3 sm:grid-cols-2">
              <section aria-label="Datos que usó">
                <h3 className="mb-1 text-sm font-medium">Datos que usó</h3>
                <ul className="divide-y">
                  {verdict.inputs.map((input) => (
                    <li key={input.label} className="flex items-center justify-between gap-3 py-1">
                      <span className="text-muted-foreground">{input.label}</span>
                      <span className="tabular-nums">{input.value}</span>
                    </li>
                  ))}
                </ul>
                <p className="mt-1 text-[11px] text-muted-foreground">
                  Confianza declarada por el agente: {Math.round(verdict.confidence * 100)} %.
                </p>
              </section>
              <section aria-label="Datos que le faltan">
                <h3 className="mb-1 text-sm font-medium">Datos que le faltan</h3>
                <ul className="list-inside list-disc space-y-0.5 text-muted-foreground">
                  {verdict.missing.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              </section>
            </div>
          </>
        )}
        <p className="text-[11px] text-muted-foreground">
          {verdict?.source ??
            "Evaluación del agente CFO. No procede del registro financiero: no es contabilidad y no confirma rentabilidad."}
        </p>
      </CardContent>
    </Card>
  );
}

// --- Lo que esta pantalla no puede calcular -----------------------------------------------------------------------

/** Dicho una vez, en voz alta, en lugar de enseñar catorce tarjetas que lo aparenten. */
export const CANNOT_COMPUTE = [
  "IVA y OSS",
  "impuesto de sociedades e IRPF",
  "caja y runway",
  "comisiones de pasarela y coste bancario",
  "conversión de divisas",
  "costes no declarados (logística, publicidad, fijos)",
  "beneficio neto y EBITDA",
  "cuentas por pagar y por cobrar",
];

export function CannotComputeCard() {
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-sm">
          <Coins className="size-4 shrink-0 text-muted-foreground" />
          Lo que esta pantalla todavía no puede calcular
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        <ul className="flex flex-wrap gap-1.5">
          {CANNOT_COMPUTE.map((item) => (
            <li key={item} className="rounded-md border bg-muted/40 px-2 py-0.5 text-[11px] text-muted-foreground">
              {item}
            </li>
          ))}
        </ul>
        <p className="text-[11px] text-muted-foreground">
          No hay fuente para ninguna de estas magnitudes, así que no se estiman ni se rellenan con constantes: sencillamente
          no están. Aparecerán cuando exista un dato que las sostenga.
        </p>
      </CardContent>
    </Card>
  );
}
