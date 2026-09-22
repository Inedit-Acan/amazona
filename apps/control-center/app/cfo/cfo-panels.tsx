"use client";

import { useState } from "react";
import Link from "next/link";
import {
  ArrowRight,
  Bot,
  CircleAlert,
  Info,
  Landmark,
  PiggyBank,
  Scale,
  Send,
  TrendingUp,
  Wallet,
} from "lucide-react";
import {
  DEMO_COPILOT_QUESTIONS,
  DEMO_FUNDING,
  DEMO_WORKING_CAPITAL,
  MONTH_LABELS,
} from "@/lib/demo/cfo";
import { formatEuro, formatInteger, formatPercent } from "@/lib/format";
import type {
  BudgetView,
  Deviation,
  DimensionKey,
  DimensionRow,
  FinancialAlert,
  ForecastKey,
  ForecastPoint,
  PayableRow,
  Pnl,
  ReceivableRow,
  TaxView,
  TreasuryView,
  UpcomingLine,
  WorkingCapitalView,
} from "@/lib/cfo-view";
import { DataProvenanceBadge } from "@/components/data-provenance-badge";
import { LevelChip, type LevelTone } from "@/components/level-chip";
import { LineChart } from "@/components/line-chart";
import { RankedBars } from "@/components/ranked-bars";
import { RingGauge } from "@/components/ring-gauge";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";

function signedPercent(fraction: number, digits = 0): string {
  return `${fraction >= 0 ? "+" : "−"}${formatPercent(Math.abs(fraction), digits)}`;
}

// --- Cuenta de resultados ---------------------------------------------------------

export function PnlCard({ pnl, monthLabel }: { pnl: Pnl; monthLabel: string }) {
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Cuenta de resultados (P&L)</CardTitle>
        <CardAction>
          <span className="rounded-md border px-2 py-1 text-xs text-muted-foreground">{monthLabel}</span>
        </CardAction>
      </CardHeader>
      <CardContent>
        <table className="w-full text-sm">
          <tbody>
            {pnl.rows.map((row) => {
              const total = row.kind === "total";
              const share = pnl.revenue > 0 ? Math.abs(row.amount) / pnl.revenue : 0;
              return (
                <tr key={row.key} className={cn("border-b last:border-0", total && "bg-primary/5")}>
                  <td className={cn("py-1.5 pl-2", total && "font-semibold text-primary")}>{row.label}</td>
                  <td className={cn("py-1.5 text-right tabular-nums", total && "font-semibold text-primary", row.amount < 0 && !total && "text-muted-foreground")}>
                    {formatEuro(row.amount, 0)}
                  </td>
                  <td className="w-16 py-1.5 pr-2 text-right text-xs tabular-nums">
                    {total ? (
                      <span className="text-primary">{formatPercent(share, 1)}</span>
                    ) : row.delta !== null ? (
                      <span className={row.delta >= 0 ? "text-primary" : "text-warning"}>{signedPercent(row.delta)}</span>
                    ) : null}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <p className="mt-2 text-[11px] text-muted-foreground">
          Calculada con los supuestos de Economía de cada producto: mismos precios, costes y CAC.
        </p>
      </CardContent>
    </Card>
  );
}

// --- Presupuesto ------------------------------------------------------------------

export function BudgetCard({ budget, year, onRequest }: { budget: BudgetView; year: number; onRequest: () => void }) {
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Presupuesto {year}</CardTitle>
        <CardAction>
          <DataProvenanceBadge
            status={budget.isReal ? "verified" : "demo"}
            compact
            tooltip={
              budget.isReal
                ? "Límite y reservas del BudgetEngine (informe del agente CFO)."
                : "El BudgetEngine no tiene límite registrado: el presupuesto anual y su reparto son de demostración."
            }
          />
        </CardAction>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex flex-wrap items-end justify-between gap-2">
          <div>
            <p className="text-2xl font-semibold">{formatEuro(budget.spent, 0)}</p>
            <p className="text-xs text-muted-foreground">gastado de {formatEuro(budget.annual, 0)}</p>
          </div>
          <p className={cn("text-xl font-semibold", budget.usage > 0.9 ? "text-destructive" : "text-primary")}>{formatPercent(budget.usage, 1)}</p>
        </div>
        <div className="h-2 rounded-full bg-muted">
          <div
            className={cn("h-full rounded-full", budget.usage > 0.9 ? "bg-destructive" : "bg-primary")}
            style={{ width: `${Math.min(100, Math.round(budget.usage * 100))}%` }}
          />
        </div>
        <ul className="space-y-1.5 text-xs">
          {budget.lines.map((line) => (
            <li key={line.key} className="grid grid-cols-[auto_minmax(0,1fr)_auto_2.6rem] items-center gap-2">
              <span className="size-2.5 rounded-full" style={{ background: line.color }} aria-hidden />
              <span className="truncate">{line.label}</span>
              <span className="tabular-nums text-muted-foreground">
                {formatEuro(line.spent, 0)} / {formatEuro(line.limit, 0)}
              </span>
              <span className={cn("text-right tabular-nums", line.usage > 1 ? "text-destructive" : line.usage > 0.9 ? "text-warning" : "")}>
                {formatPercent(line.usage, 0)}
              </span>
            </li>
          ))}
        </ul>
        <Button variant="outline" className="w-full" onClick={onRequest}>
          Solicitar nuevo presupuesto <ArrowRight />
        </Button>
      </CardContent>
    </Card>
  );
}

// --- Tesorería --------------------------------------------------------------------

export function TreasuryCard({ treasury, week }: { treasury: TreasuryView; week: { lines: UpcomingLine[]; net: number } }) {
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Landmark className="size-4 text-primary" /> Tesorería
        </CardTitle>
        <CardAction>
          <DataProvenanceBadge status="demo" compact tooltip="No hay banco ni pasarela conectados: los saldos son de demostración; lo pendiente de cobro sale de los pedidos." />
        </CardAction>
      </CardHeader>
      <CardContent className="grid gap-4 sm:grid-cols-2">
        <dl className="space-y-1.5 text-sm">
          {[
            ["Cuenta operativa", treasury.operating],
            ["Reserva", treasury.reserve],
            ["Stripe (pendiente)", treasury.stripe],
            ["PayPal (pendiente)", treasury.paypal],
          ].map(([label, amount]) => (
            <div key={label as string} className="flex items-center justify-between gap-2">
              <dt className="text-muted-foreground">{label as string}</dt>
              <dd className="tabular-nums">{formatEuro(amount as number, 0)}</dd>
            </div>
          ))}
          <div className="flex items-center justify-between gap-2 rounded-lg border border-primary/40 bg-primary/5 px-2 py-1.5">
            <dt className="font-medium text-primary">Liquidez total</dt>
            <dd className="font-semibold text-primary tabular-nums">{formatEuro(treasury.total, 0)}</dd>
          </div>
        </dl>
        <div className="min-w-0">
          <p className="mb-1.5 text-xs font-medium text-muted-foreground">Próximos 7 días</p>
          <dl className="space-y-1.5 text-sm">
            {week.lines.map((line) => (
              <div key={line.key} className="flex items-center justify-between gap-2">
                <dt className="text-xs leading-tight text-muted-foreground">{line.label}</dt>
                <dd className={cn("shrink-0 tabular-nums", line.amount >= 0 ? "text-primary" : "text-destructive")}>
                  {line.amount >= 0 ? "+" : "−"}
                  {formatEuro(Math.abs(line.amount), 0)}
                </dd>
              </div>
            ))}
            <div className="flex items-center justify-between gap-2 border-t pt-1.5">
              <dt className="text-muted-foreground">Variación esperada</dt>
              <dd className={cn("font-medium tabular-nums", week.net >= 0 ? "text-primary" : "text-destructive")}>
                {week.net >= 0 ? "+" : "−"}
                {formatEuro(Math.abs(week.net), 0)}
              </dd>
            </div>
          </dl>
        </div>
      </CardContent>
    </Card>
  );
}

// --- Cuentas a pagar y cobrar --------------------------------------------------------

export function PayablesCard({ rows, formatDueDay }: { rows: PayableRow[]; formatDueDay: (days: number) => string }) {
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Cuentas a pagar</CardTitle>
        <CardAction>
          <Button size="xs" variant="outline" className="text-primary" nativeButton={false} render={<Link href="/operations" />}>
            Ver todas
          </Button>
        </CardAction>
      </CardHeader>
      <CardContent>
        <table className="w-full text-xs">
          <thead className="text-muted-foreground">
            <tr>
              <th className="pb-2 text-left font-normal">Proveedor</th>
              <th className="pb-2 text-right font-normal">Importe</th>
              <th className="pb-2 text-right font-normal">Vencimiento</th>
              <th className="pb-2 text-right font-normal">Estado</th>
            </tr>
          </thead>
          <tbody>
            {rows.slice(0, 6).map((row) => (
              <tr key={row.key} className="border-t">
                <td className="py-1.5 leading-tight">{row.label}</td>
                <td className="text-right tabular-nums">{formatEuro(row.amount, 0)}</td>
                <td className="text-right whitespace-nowrap text-muted-foreground tabular-nums">{formatDueDay(row.dueInDays)}</td>
                <td className="py-1.5 text-right">
                  <LevelChip tone={row.status === "Programado" ? "ok" : "warn"}>{row.status}</LevelChip>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="mt-2 text-[11px] text-muted-foreground">
          Proveedores: coste de los pedidos abiertos de Operaciones. Publicidad: el plan de Marketing.
        </p>
      </CardContent>
    </Card>
  );
}

export function ReceivablesCard({ rows, total, averageDays }: { rows: ReceivableRow[]; total: number; averageDays: number }) {
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Cuentas a cobrar</CardTitle>
        <CardAction>
          <Button size="xs" variant="outline" className="text-primary" nativeButton={false} render={<Link href="/operations" />}>
            Ver todas
          </Button>
        </CardAction>
      </CardHeader>
      <CardContent className="space-y-2">
        <table className="w-full text-xs">
          <thead className="text-muted-foreground">
            <tr>
              <th className="pb-2 text-left font-normal">Canal</th>
              <th className="pb-2 text-right font-normal">Importe</th>
              <th className="pb-2 text-right font-normal">Estado</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.key} className="border-t">
                <td className="py-1.5">{row.label}</td>
                <td className="text-right tabular-nums">{formatEuro(row.amount, 0)}</td>
                <td className="py-1.5 text-right">
                  <LevelChip tone={row.status === "En tránsito" ? "neutral" : "warn"}>{row.status}</LevelChip>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <dl className="grid gap-1 border-t pt-2 text-xs">
          <div className="flex items-center justify-between">
            <dt className="text-muted-foreground">Total pendiente</dt>
            <dd className="font-semibold tabular-nums">{formatEuro(total, 0)}</dd>
          </div>
          <div className="flex items-center justify-between">
            <dt className="text-muted-foreground">Tiempo medio hasta cobro</dt>
            <dd className="tabular-nums">{averageDays.toLocaleString("es-ES", { maximumFractionDigits: 1 })} días</dd>
          </div>
        </dl>
      </CardContent>
    </Card>
  );
}

export function WorkingCapitalCard({ view }: { view: WorkingCapitalView }) {
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          Working Capital <span className="text-xs font-normal text-muted-foreground">(sin stock)</span>
        </CardTitle>
        <CardAction>
          <DataProvenanceBadge status="demo" compact tooltip="Modelo de envío directo: el capital adelantado sale de las cuentas a pagar y la cobertura, de lo pendiente de cobro." />
        </CardAction>
      </CardHeader>
      <CardContent className="space-y-2 text-sm">
        <div className="flex items-center justify-between gap-2">
          <span className="text-muted-foreground">Cobros cliente antes de compra</span>
          <span className="font-medium text-primary tabular-nums">{formatPercent(view.prepaidShare)}</span>
        </div>
        <div className="flex items-center justify-between gap-2">
          <span className="text-muted-foreground">Capital adelantado AMAZONA</span>
          <span className="tabular-nums">{formatEuro(view.advanced, 0)}</span>
        </div>
        <div className="flex items-center justify-between gap-2">
          <span className="text-muted-foreground">Capital cubierto</span>
          <span className="tabular-nums">{formatEuro(view.covered, 0)}</span>
        </div>
        <div className="flex items-center justify-between gap-2">
          <span className="text-muted-foreground">Capital sin cobertura</span>
          <span className={cn("tabular-nums", view.uncovered > 0 && "text-warning")}>{formatEuro(view.uncovered, 0)}</span>
        </div>
        <div className="flex items-center justify-between gap-2 rounded-lg border border-primary/40 bg-primary/5 px-2 py-1.5">
          <span className="font-medium text-primary">Cobertura global</span>
          <span className="font-semibold text-primary tabular-nums">{formatPercent(view.coverage)}</span>
        </div>
        <dl className="grid gap-1 text-xs">
          <div className="flex items-center justify-between">
            <dt className="text-muted-foreground">Objetivo</dt>
            <dd>
              {formatPercent(DEMO_WORKING_CAPITAL.targetMin, 0)} – {formatPercent(DEMO_WORKING_CAPITAL.targetMax, 0)}
            </dd>
          </div>
          <div className="flex items-center justify-between">
            <dt className="text-muted-foreground">Estado</dt>
            <dd className={view.inRange ? "text-primary" : "text-warning"}>{view.inRange ? "En rango ✓" : "Fuera de rango"}</dd>
          </div>
        </dl>
      </CardContent>
    </Card>
  );
}

// --- Forecast y dimensiones ----------------------------------------------------------

const FORECAST_TABS: { key: ForecastKey; label: string }[] = [
  { key: "base", label: "Base" },
  { key: "conservative", label: "Conservador" },
  { key: "optimistic", label: "Expansión" },
];

export function ForecastCard({
  scenario,
  onScenarioChange,
  points,
  hasReal,
}: {
  scenario: ForecastKey;
  onScenarioChange: (key: ForecastKey) => void;
  points: ForecastPoint[];
  hasReal: boolean;
}) {
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Forecast financiero</CardTitle>
        <CardAction>
          <DataProvenanceBadge
            status={hasReal ? "estimated" : "demo"}
            compact
            tooltip={
              hasReal
                ? "Escenarios del análisis económico del agente, proyectados con el crecimiento previsto de la demostración."
                : "Sin análisis económico: los escenarios salen del modelo de Economía sobre supuestos de demostración."
            }
          />
        </CardAction>
      </CardHeader>
      <CardContent className="space-y-2">
        <Tabs value={scenario} onValueChange={(v) => onScenarioChange(v as ForecastKey)}>
          <TabsList className="flex w-full justify-start group-data-horizontal/tabs:h-auto">
            {FORECAST_TABS.map((tab) => (
              <TabsTrigger key={tab.key} value={tab.key} className="min-w-0 flex-1 basis-0 px-2 text-xs">
                {tab.label}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
        <LineChart
          ariaLabel={`Forecast de ingresos, costes y resultado (${FORECAST_TABS.find((t) => t.key === scenario)!.label})`}
          series={[
            { key: "revenue", label: "Ingresos", color: "var(--emerald-bright)", points: points.map((p) => ({ x: p.offset, y: p.revenue })) },
            { key: "costs", label: "Costes", color: "var(--danger)", points: points.map((p) => ({ x: p.offset, y: p.costs })) },
            { key: "profit", label: "Resultado", color: "#4f8df7", points: points.map((p) => ({ x: p.offset, y: p.profit })) },
          ]}
          formatY={(v) => formatEuro(v, 0)}
          formatX={(x) => points.find((p) => p.offset === x)?.label ?? String(x)}
          hoverTitle={(x) => points.find((p) => p.offset === x)?.label ?? String(x)}
          height={210}
        />
      </CardContent>
    </Card>
  );
}

const DIMENSION_TABS: { key: DimensionKey; label: string }[] = [
  { key: "products", label: "Productos" },
  { key: "channels", label: "Canales" },
  { key: "markets", label: "Países" },
  { key: "suppliers", label: "Proveedores" },
];

export function DimensionCard({
  dimension,
  onDimensionChange,
  rows,
}: {
  dimension: DimensionKey;
  onDimensionChange: (key: DimensionKey) => void;
  rows: DimensionRow[];
}) {
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Rendimiento por dimensión</CardTitle>
        <CardDescription>Ingresos de los pedidos del periodo.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <Tabs value={dimension} onValueChange={(v) => onDimensionChange(v as DimensionKey)}>
          <TabsList className="flex w-full flex-wrap justify-start group-data-horizontal/tabs:h-auto">
            {DIMENSION_TABS.map((tab) => (
              <TabsTrigger key={tab.key} value={tab.key} className="flex-none px-2 text-xs">
                {tab.label}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
        <RankedBars
          ariaLabel="Ingresos por dimensión"
          items={rows.slice(0, 5).map((row) => ({ key: row.key, label: row.label, value: row.value, valueLabel: formatEuro(row.value, 0) }))}
        />
      </CardContent>
    </Card>
  );
}

// --- Desviaciones, salud, fiscalidad, financiación y alertas ----------------------------

const DEVIATION_TONE: Record<Deviation["tone"], { chip: LevelTone; label: string }> = {
  bad: { chip: "bad", label: "ALTA" },
  warn: { chip: "warn", label: "MEDIA" },
  ok: { chip: "ok", label: "POSITIVA" },
};

export function DeviationsCard({ rows }: { rows: Deviation[] }) {
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Desviaciones del mes</CardTitle>
        <CardAction>
          <DataProvenanceBadge status="estimated" compact tooltip="Gasto real del mes frente a la doceava parte del presupuesto anual." />
        </CardAction>
      </CardHeader>
      <CardContent>
        <ul className="space-y-2.5">
          {rows.map((row) => {
            const tone = DEVIATION_TONE[row.tone];
            return (
              <li key={row.key} className="grid grid-cols-[minmax(0,1fr)_auto] items-start gap-2">
                <span className="min-w-0">
                  <span className="flex flex-wrap items-baseline gap-2">
                    <span className="text-sm font-medium">{row.label}</span>
                    <span className={cn("text-sm tabular-nums", row.deviation > 0 ? "text-warning" : "text-primary")}>{signedPercent(row.deviation, 1)}</span>
                  </span>
                  <span className="block text-xs text-muted-foreground">{row.detail}</span>
                </span>
                <LevelChip tone={tone.chip}>{tone.label}</LevelChip>
              </li>
            );
          })}
        </ul>
      </CardContent>
    </Card>
  );
}

export function FinancialHealthCard({
  health,
  agentVerdict,
}: {
  health: { score: number; label: string; axes: { label: string; value: number }[] };
  agentVerdict?: { title: string; tone: "ok" | "warn" | "bad" };
}) {
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Financial Health</CardTitle>
        {agentVerdict ? (
          <CardAction>
            <LevelChip tone={agentVerdict.tone === "ok" ? "ok" : agentVerdict.tone === "warn" ? "warn" : "bad"}>Agente: {agentVerdict.title}</LevelChip>
          </CardAction>
        ) : null}
      </CardHeader>
      <CardContent className="flex items-center gap-4">
        <RingGauge value={health.score / 100} size={104} centerLabel={`${health.score}/100`} caption={health.label} />
        <ul className="min-w-0 flex-1 space-y-1.5 text-xs">
          {health.axes.map((axis) => (
            <li key={axis.label} className="grid grid-cols-[minmax(0,6.5rem)_1fr_1.75rem] items-center gap-2">
              <span className="truncate text-muted-foreground">{axis.label}</span>
              <span className="h-1.5 rounded-full bg-muted">
                <span className="block h-full rounded-full bg-primary" style={{ width: `${axis.value}%` }} />
              </span>
              <span className="text-right tabular-nums">{axis.value}</span>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

export function TaxCard({ tax, year }: { tax: TaxView; year: number }) {
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Scale className="size-4 text-primary" /> Fiscalidad
        </CardTitle>
        <CardAction>
          <DataProvenanceBadge status="demo" compact tooltip="AMAZONA no emite facturas ni lleva contabilidad: los impuestos son una estimación sobre el margen y el EBITDA." />
        </CardAction>
      </CardHeader>
      <CardContent className="space-y-2 text-sm">
        <div className="flex items-center justify-between gap-2">
          <span className="text-muted-foreground">IVA estimado pendiente</span>
          <span className="tabular-nums">{formatEuro(tax.vat, 0)}</span>
        </div>
        <div className="flex items-center justify-between gap-2">
          <span className="text-muted-foreground">Impuesto sociedades (est.)</span>
          <span className="tabular-nums">{formatEuro(tax.corporate, 0)}</span>
        </div>
        <div className="flex items-center justify-between gap-2">
          <span className="text-muted-foreground">Próxima obligación</span>
          <span className="tabular-nums">
            20 {MONTH_LABELS[tax.nextDueMonth % 12]} {tax.nextDueMonth >= 12 ? year + 1 : year}
          </span>
        </div>
        <div className="space-y-1">
          <div className="flex items-center justify-between gap-2">
            <span className="text-muted-foreground">Documentación</span>
            <span className="tabular-nums">{formatPercent(tax.docsReady, 0)}</span>
          </div>
          <div className="h-1.5 rounded-full bg-muted">
            <div className="h-full rounded-full bg-primary" style={{ width: `${Math.round(tax.docsReady * 100)}%` }} />
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

export function FundingCard({ reserve, capitalNeed }: { reserve: number; capitalNeed: number }) {
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <PiggyBank className="size-4 text-primary" /> Capital y financiación
        </CardTitle>
        <CardAction>
          <DataProvenanceBadge status="demo" compact tooltip="No hay buscador de ayudas ni plan de financiación en el backend." />
        </CardAction>
      </CardHeader>
      <CardContent className="space-y-2 text-sm">
        {[
          ["Subvenciones detectadas", formatInteger(DEMO_FUNDING.detected)],
          ["Aplicables", formatInteger(DEMO_FUNDING.eligible)],
          ["En preparación", formatInteger(DEMO_FUNDING.inProgress)],
          ["Necesidad prevista de capital", formatEuro(capitalNeed, 0)],
          ["Reserva disponible", formatEuro(reserve, 0)],
        ].map(([label, value]) => (
          <div key={label} className="flex items-center justify-between gap-2">
            <span className="text-muted-foreground">{label}</span>
            <span className="tabular-nums">{value}</span>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

const ALERT_TONE: Record<FinancialAlert["level"], LevelTone> = { Alta: "bad", Media: "warn", Info: "neutral" };

export function AlertsCard({ alerts }: { alerts: FinancialAlert[] }) {
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <CircleAlert className="size-4 text-primary" /> Alertas financieras
        </CardTitle>
        <CardAction>
          <Button size="xs" variant="outline" className="text-primary" nativeButton={false} render={<Link href="/approvals" />}>
            Ver todas
          </Button>
        </CardAction>
      </CardHeader>
      <CardContent>
        <ul className="space-y-2">
          {alerts.map((alert) => (
            <li key={alert.message} className="grid grid-cols-[3.5rem_minmax(0,1fr)] items-start gap-2 text-xs">
              <LevelChip tone={ALERT_TONE[alert.level]} className="uppercase">
                {alert.level}
              </LevelChip>
              <span className="min-w-0 leading-tight">
                {alert.message}
                {alert.fromAgent ? (
                  <DataProvenanceBadge status="verified" compact className="ml-1.5 align-middle" tooltip="Riesgo del informe del agente CFO (texto suyo, en inglés)." />
                ) : null}
              </span>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

export function CopilotCard() {
  const [question, setQuestion] = useState("");
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Bot className="size-4 text-primary" /> CFO Copilot
          <span className="rounded-md border px-1.5 py-0.5 text-[10px] text-muted-foreground">Beta</span>
        </CardTitle>
        <CardAction>
          <DataProvenanceBadge status="pending" compact tooltip="No existe un endpoint conversacional del agente CFO: el copiloto todavía no responde." />
        </CardAction>
      </CardHeader>
      <CardContent className="space-y-2">
        <div className="flex gap-2">
          <input
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="Pregunta al Director de Finanzas…"
            aria-label="Pregunta al copiloto financiero"
            className="min-w-0 flex-1 rounded-md border bg-background px-2.5 py-1.5 text-sm"
          />
          <Button size="icon" disabled title="Pendiente: el copiloto no tiene backend conversacional">
            <Send />
          </Button>
        </div>
        <ul className="flex flex-wrap gap-1.5">
          {DEMO_COPILOT_QUESTIONS.map((text) => (
            <li key={text}>
              <button
                type="button"
                onClick={() => setQuestion(text)}
                className="rounded-md border px-2 py-1 text-[11px] text-muted-foreground transition hover:border-primary/50 hover:text-foreground"
              >
                {text}
              </button>
            </li>
          ))}
        </ul>
        <p className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
          <Info className="size-3.5 shrink-0" /> Las preguntas se guardan en el formulario; enviar requiere backend.
        </p>
      </CardContent>
    </Card>
  );
}

export const CFO_ICONS = { Wallet, TrendingUp };
