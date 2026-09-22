"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowDown, ArrowUp, BarChart3, Coins, Hourglass, PieChart, Percent, Wallet } from "lucide-react";
import { DEMO_SALE } from "@/lib/demo/economics";
import {
  CASH_FLOW_RANGES,
  DEMO_CASH,
  DEMO_TAX_DOCS_READY,
  ENTITIES,
  MONTH_LABELS,
  SCENARIO_VIEWS,
} from "@/lib/demo/cfo";
import { demoQuotes } from "@/lib/demo/sourcing";
import { demoSku } from "@/lib/demo/storefront";
import {
  budgetView,
  buildPnl,
  cashFlowSeries,
  cashWarning,
  deviations,
  dimensionRows,
  financialAlerts,
  financialHealth,
  forecast,
  monthFactor,
  payables,
  receivables,
  runwayMonths,
  scalePnl,
  taxView,
  treasury,
  upcomingWeek,
  withDeltas,
  workingCapital,
  type DimensionKey,
  type ForecastKey,
  type ProductFinance,
} from "@/lib/cfo-view";
import { downloadCsv, toCsv } from "@/lib/csv";
import { dedupeQuotesBySupplier } from "@/lib/economics";
import { buildBaseline } from "@/lib/economics-baseline";
import { FINANCIAL_VERDICT } from "@/lib/finance";
import { formatEuro, formatInteger, formatPercent } from "@/lib/format";
import { marketLabel } from "@/lib/markets";
import { buildOrders, ordersInPeriod, startOfDay, type ProductInput, type SupplierInput } from "@/lib/operations-view";
import { rankSuppliers } from "@/lib/sourcing-view";
import { CashFlowChart } from "@/components/cash-flow-chart";
import { DataProvenanceBadge } from "@/components/data-provenance-badge";
import { EmptyState } from "@/components/empty-state";
import { KpiCard } from "@/components/kpi-card";
import { PageHeader } from "@/components/page-header";
import { Sparkline } from "@/components/sparkline";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import type { CFOReport, SupplierQuote } from "@/lib/api";
import type { ProductFinanceData } from "./page";
import { CFO_DESCRIPTION, CFO_TITLE } from "./copy";
import {
  AlertsCard,
  BudgetCard,
  CopilotCard,
  DeviationsCard,
  DimensionCard,
  FinancialHealthCard,
  ForecastCard,
  FundingCard,
  PayablesCard,
  PnlCard,
  ReceivablesCard,
  TaxCard,
  TreasuryCard,
  WorkingCapitalCard,
} from "./cfo-panels";

const DEMO_TOOLTIP =
  "Incluye datos de demostración: AMAZONA no tiene contabilidad, banco ni facturación, así que la caja, el cash flow, la tesorería, la fiscalidad, las subvenciones y el copiloto son simulados, y el presupuesto anual lo es mientras el BudgetEngine no tenga límite. Real: los análisis económicos de cada producto (de ahí salen ingresos, costes y margen, con los mismos supuestos que Economía), las cotizaciones de proveedor y el informe del agente CFO (veredicto de salud financiera y reservas).";

/** Meses que se pueden mirar hacia atrás en el selector de periodo. */
const PERIOD_OFFSETS = [0, -1, -2, -3];

function quoteToSupplier(quote: SupplierQuote, isDemo: boolean): SupplierInput {
  return {
    id: quote.supplier_id,
    name: quote.data?.name ?? quote.supplier_id,
    region: quote.data?.region ?? "eu",
    leadTimeDays: quote.lead_time_days,
    reliability: quote.reliability_score,
    verified: quote.verified,
    isDemo,
  };
}

function Delta({ value, unit = "%" }: { value: number; unit?: "%" | "pp" }) {
  const Icon = value >= 0 ? ArrowUp : ArrowDown;
  const text = unit === "pp" ? `${Math.abs(value * 100).toLocaleString("es-ES", { maximumFractionDigits: 1 })} pp` : formatPercent(Math.abs(value), 0);
  return (
    <p className={cn("flex items-center gap-1 text-xs", value >= 0 ? "text-primary" : "text-warning")}>
      <Icon className="size-3 shrink-0" />
      {value >= 0 ? "+" : "−"}
      {text} vs. mes anterior
    </p>
  );
}

export function CfoWorkspace({
  data,
  report,
  totalProducts,
  today,
}: {
  data: ProductFinanceData[];
  report?: CFOReport;
  totalProducts: number;
  today: string;
}) {
  const router = useRouter();
  const [offset, setOffset] = useState(0);
  const [entity, setEntity] = useState("all");
  const [scenarioView, setScenarioView] = useState(SCENARIO_VIEWS[0].value);
  const [cashRange, setCashRange] = useState(CASH_FLOW_RANGES[0].value);
  const [forecastScenario, setForecastScenario] = useState<ForecastKey>("base");
  const [dimension, setDimension] = useState<DimensionKey>("products");

  const date = new Date(`${today}T00:00:00Z`);
  const monthIndex = date.getUTCMonth();
  const year = date.getUTCFullYear();
  const shownMonth = (((monthIndex + offset) % 12) + 12) % 12;
  const monthsElapsed = monthIndex + 1 + offset;

  // Mismos supuestos que Economía: cotización real (o la de demostración que
  // recomienda Proveedores) y último análisis económico de cada producto.
  const finances = useMemo<ProductFinance[]>(
    () =>
      data.map(({ product, economics, quotes }) => {
        const analysis = economics[0];
        const options = dedupeQuotesBySupplier(quotes, analysis?.supplier_quote_id);
        const quote = options.find((q) => q.id === analysis?.supplier_quote_id) ?? options[0];
        return {
          id: product.id,
          name: product.name,
          category: product.category,
          inputs: buildBaseline(quote, analysis).inputs,
          analysis,
          isDemo: !analysis,
        };
      }),
    [data],
  );

  const orderProducts = useMemo<ProductInput[]>(
    () =>
      data.map(({ product, economics, quotes }) => {
        const real = quotes.length > 0;
        const ranked = rankSuppliers(real ? dedupeQuotesBySupplier(quotes) : demoQuotes(product.id));
        return {
          id: product.id,
          name: product.name,
          sku: demoSku(product.category, product.id),
          price: economics[0]?.sale_price ?? DEMO_SALE.salePrice,
          suppliers: ranked.slice(0, 3).map((r) => quoteToSupplier(r.quote, !real)),
        };
      }),
    [data],
  );

  const allOrders = useMemo(() => buildOrders(orderProducts, today), [orderProducts, today]);
  const entityMarkets = ENTITIES.find((e) => e.value === entity)!.markets;
  const monthOrders = useMemo(() => ordersInPeriod(allOrders, today, 30).filter((o) => entityMarkets.includes(o.market)), [allOrders, today, entityMarkets]);

  const basePnl = useMemo(() => buildPnl(finances), [finances]);
  // Reparto por entidad: la parte de los pedidos del periodo que va a sus mercados.
  const entityShare = useMemo(() => {
    const all = ordersInPeriod(allOrders, today, 30);
    const total = all.reduce((sum, o) => sum + o.amount, 0);
    if (total === 0 || entity === "all") return 1;
    return monthOrders.reduce((sum, o) => sum + o.amount, 0) / total;
  }, [allOrders, monthOrders, today, entity]);

  const previousPnl = useMemo(
    () => scalePnl(basePnl, monthFactor(offset - 1, "revenue") * entityShare, monthFactor(offset - 1, "costs") * entityShare),
    [basePnl, offset, entityShare],
  );
  const pnl = useMemo(
    () => withDeltas(scalePnl(basePnl, monthFactor(offset, "revenue") * entityShare, monthFactor(offset, "costs") * entityShare), previousPnl),
    [basePnl, offset, entityShare, previousPnl],
  );

  if (data.length === 0) {
    return (
      <div>
        <PageHeader title={CFO_TITLE} description={CFO_DESCRIPTION} />
        <Card>
          <CardContent>
            <EmptyState
              icon={Wallet}
              title="Aún no hay catálogo que consolidar"
              description="Las finanzas parten de los productos investigados y de sus análisis económicos."
            />
          </CardContent>
        </Card>
      </div>
    );
  }

  const now = startOfDay(today);
  const receivablesView = receivables(monthOrders, now);
  const treasuryView = treasury(receivablesView.total);
  const cash = treasuryView.total;
  const payableRows = payables(monthOrders, pnl, now);
  const payableTotal = payableRows.reduce((sum, row) => sum + row.amount, 0);
  const working = workingCapital(payableTotal, receivablesView.total);
  const months = CASH_FLOW_RANGES.find((r) => r.value === cashRange)!.months;
  const fullSeries = cashFlowSeries(pnl, cash, months, shownMonth);
  const series = scenarioView === "actual" ? fullSeries.filter((m) => !m.forecast) : scenarioView === "forecast" ? fullSeries.filter((m) => m.forecast) : fullSeries;
  const warning = cashWarning(fullSeries, pnl.spend);
  const budget = budgetView(pnl, Math.max(1, monthsElapsed), report);
  const deviationRows = deviations(pnl, budget);
  const tax = taxView(pnl, shownMonth, DEMO_TAX_DOCS_READY);
  const health = financialHealth({ pnl, cash, budget, working, cashSeries: fullSeries, taxProvision: pnl.tax });
  const alerts = financialAlerts({ deviations: deviationRows, budget, receivables: receivablesView, pnl, monthsElapsed: Math.max(1, monthsElapsed), agentRisks: report?.data?.risks });
  const forecastPoints = forecast(finances, forecastScenario, 6, shownMonth);
  const hasRealScenarios = finances.some((f) => f.analysis?.data?.scenarios);
  const runway = runwayMonths(cash, pnl);
  const verdict = report ? FINANCIAL_VERDICT[report.financial_health_status] : undefined;
  const balances = fullSeries.map((m) => m.balance);
  const currentIndex = fullSeries.findIndex((m) => m.offset === 0);
  const cashDelta = currentIndex > 0 && fullSeries[currentIndex - 1].balance !== 0 ? balances[currentIndex] / fullSeries[currentIndex - 1].balance - 1 : 0;
  const inflows = fullSeries.map((m) => m.inflow);
  const outflows = fullSeries.map((m) => m.outflow);

  function exportReport() {
    const csv = toCsv(
      ["Concepto", "Importe", "Variación"],
      pnl.rows.map((row) => [row.label, row.amount, row.delta === null ? "" : formatPercent(row.delta, 1)]),
    );
    downloadCsv(`finanzas-${MONTH_LABELS[shownMonth].toLowerCase()}-${year}.csv`, csv);
  }

  function requestBudget() {
    const params = new URLSearchParams({
      title: `Ampliar el presupuesto anual de ${formatEuro(budget.annual, 0)}`,
      spend_amount: String(Math.round(budget.annual * 0.1)),
    });
    router.push(`/ceo?${params.toString()}`);
  }

  return (
    <div className="space-y-5">
      <PageHeader
        title={CFO_TITLE}
        description={CFO_DESCRIPTION}
        actions={
          <>
            <DataProvenanceBadge status="demo" tooltip={DEMO_TOOLTIP} />
            <label className="flex w-40 flex-col rounded-lg border bg-card px-3 py-2 text-xs text-muted-foreground">
              Periodo
              <select value={offset} onChange={(e) => setOffset(Number(e.target.value))} className="mt-0.5 bg-transparent text-sm font-medium text-primary outline-none">
                {PERIOD_OFFSETS.map((value) => {
                  const index = (((monthIndex + value) % 12) + 12) % 12;
                  return (
                    <option key={value} value={value} className="bg-popover text-foreground">
                      {MONTH_LABELS[index]} {index > monthIndex ? year - 1 : year}
                    </option>
                  );
                })}
              </select>
            </label>
            <label className="flex w-48 flex-col rounded-lg border bg-card px-3 py-2 text-xs text-muted-foreground">
              Entidad
              <select value={entity} onChange={(e) => setEntity(e.target.value)} className="mt-0.5 bg-transparent text-sm font-medium text-primary outline-none">
                {ENTITIES.map((item) => (
                  <option key={item.value} value={item.value} className="bg-popover text-foreground">
                    {item.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex w-44 flex-col rounded-lg border bg-card px-3 py-2 text-xs text-muted-foreground">
              Escenario
              <select value={scenarioView} onChange={(e) => setScenarioView(e.target.value)} className="mt-0.5 bg-transparent text-sm font-medium text-primary outline-none">
                {SCENARIO_VIEWS.map((item) => (
                  <option key={item.value} value={item.value} className="bg-popover text-foreground">
                    {item.label}
                  </option>
                ))}
              </select>
            </label>
            <Button variant="outline" onClick={exportReport}>
              Exportar informe
            </Button>
          </>
        }
      />

      {/* KPIs */}
      <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6" aria-label="Indicadores financieros">
        <KpiCard
          label="Caja disponible"
          leading={<Coins className="size-8 shrink-0 text-primary" />}
          value={formatEuro(cash, 0)}
          footer={
            <>
              <Delta value={cashDelta} />
              <Sparkline values={balances} />
            </>
          }
        />
        <KpiCard
          label="Ingresos del mes"
          leading={<BarChart3 className="size-8 shrink-0 text-primary" />}
          value={formatEuro(pnl.revenue, 0)}
          accent
          footer={
            <>
              <Delta value={pnl.rows[0].delta ?? 0} />
              <Sparkline values={inflows} />
            </>
          }
        />
        <KpiCard
          label="Beneficio neto"
          leading={<PieChart className="size-8 shrink-0 text-primary" />}
          value={formatEuro(pnl.net, 0)}
          tone={pnl.net >= 0 ? "success" : "danger"}
          footer={<Sparkline values={fullSeries.map((m) => m.inflow - m.outflow)} />}
        />
        <KpiCard
          label="Margen neto"
          leading={<Percent className="size-8 shrink-0 text-primary" />}
          value={formatPercent(pnl.netMarginPct)}
          footer={<Delta value={pnl.netMarginPct - previousPnl.netMarginPct} unit="pp" />}
        />
        <KpiCard
          label="Gasto del mes"
          leading={<Wallet className="size-8 shrink-0 text-primary" />}
          value={formatEuro(pnl.spend, 0)}
          footer={
            <>
              <Delta value={previousPnl.spend > 0 ? pnl.spend / previousPnl.spend - 1 : 0} />
              <Sparkline values={outflows} color="var(--danger)" />
            </>
          }
        />
        <KpiCard
          label="Runway"
          leading={<Hourglass className="size-8 shrink-0 text-primary" />}
          value={pnl.net >= 0 ? "Sin riesgo" : `${runway.toLocaleString("es-ES", { maximumFractionDigits: 1 })} meses`}
          tone={pnl.net >= 0 ? "success" : runway < 3 ? "danger" : "warning"}
          caption={
            pnl.net >= 0
              ? `Mes en positivo · la caja cubre ${runway.toLocaleString("es-ES", { maximumFractionDigits: 1 })} meses de gastos`
              : "Con el ritmo de gasto actual"
          }
        />
      </section>

      {/* Cash flow · P&L · Presupuesto */}
      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)_minmax(0,0.9fr)]">
        <Card className="min-w-0">
          <CardHeader>
            <CardTitle>Cash Flow</CardTitle>
            <CardAction>
              <select
                value={cashRange}
                onChange={(e) => setCashRange(e.target.value)}
                aria-label="Meses del cash flow"
                className="rounded-md border bg-background px-2 py-1 text-xs"
              >
                {CASH_FLOW_RANGES.map((range) => (
                  <option key={range.value} value={range.value}>
                    {range.label}
                  </option>
                ))}
              </select>
            </CardAction>
          </CardHeader>
          <CardContent>
            <CashFlowChart
              ariaLabel="Entradas, salidas y saldo por mes"
              points={series}
              formatValue={(v) => formatEuro(v, 0)}
              warning={
                warning
                  ? {
                      index: series.findIndex((m) => m.offset === warning.offset),
                      lines: ["Posible tensión de caja", `prevista en ${warning.label}`],
                    }
                  : undefined
              }
            />
            <p className="mt-2 text-[11px] text-muted-foreground">
              Entradas y salidas del mes proyectadas con el crecimiento previsto; el saldo parte de la liquidez actual.
            </p>
          </CardContent>
        </Card>

        <PnlCard pnl={pnl} monthLabel={`${MONTH_LABELS[shownMonth]} ${year}`} />
        <BudgetCard budget={budget} year={year} onRequest={requestBudget} />
      </section>

      {/* Tesorería · Pagos · Cobros · Working capital */}
      <section className="grid gap-4 md:grid-cols-2 2xl:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)_minmax(0,1fr)_minmax(0,0.9fr)]">
        <TreasuryCard treasury={treasuryView} week={upcomingWeek(pnl, receivablesView.total)} />
        <PayablesCard rows={payableRows} formatDueDay={(days) => `${((date.getUTCDate() + days - 1) % 30) + 1} ${MONTH_LABELS[(shownMonth + (date.getUTCDate() + days > 30 ? 1 : 0)) % 12]}`} />
        <ReceivablesCard rows={receivablesView.rows} total={receivablesView.total} averageDays={receivablesView.averageDays} />
        <WorkingCapitalCard view={working} />
      </section>

      {/* Forecast · Dimensiones · Desviaciones · Salud */}
      <section className="grid gap-4 md:grid-cols-2 2xl:grid-cols-4">
        <ForecastCard scenario={forecastScenario} onScenarioChange={setForecastScenario} points={forecastPoints} hasReal={hasRealScenarios} />
        <DimensionCard dimension={dimension} onDimensionChange={setDimension} rows={dimensionRows(monthOrders, dimension, marketLabel)} />
        <DeviationsCard rows={deviationRows} />
        <FinancialHealthCard health={health} agentVerdict={verdict} />
      </section>

      {/* Fiscalidad · Capital · Alertas · Copiloto */}
      <section className="grid gap-4 md:grid-cols-2 2xl:grid-cols-4">
        <TaxCard tax={tax} year={year} />
        <FundingCard reserve={DEMO_CASH.reserve} capitalNeed={Math.max(0, pnl.spend - pnl.revenue)} />
        <AlertsCard alerts={alerts} />
        <CopilotCard />
      </section>

      <p className="text-[11px] text-muted-foreground">
        Catálogo consolidado: {formatInteger(data.length)} de {formatInteger(totalProducts)} productos
        {report ? ` · informe del agente CFO con ${formatInteger(report.data?.total_products_analyzed ?? 0)} análisis` : " · sin informe del agente CFO"}.
      </p>
    </div>
  );
}
