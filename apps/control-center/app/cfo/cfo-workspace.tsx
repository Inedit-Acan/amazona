"use client";

import { useMemo, useState } from "react";
import {
  AlertTriangle,
  Banknote,
  Bot,
  CalendarClock,
  FileSpreadsheet,
  Gauge,
  Landmark,
  LineChart,
  Loader2,
  Megaphone,
  PiggyBank,
  Receipt,
  ShieldCheck,
  Target,
  TrendingUp,
  Wallet,
  Boxes,
  Scale,
  Wallet2,
} from "lucide-react";
import { ApiError, api, type CFOReport, type EconomicAnalysis, type Product } from "@/lib/api";
import { CFO_RULES, FINANCIAL_VERDICT, budgetBreakdown, portfolioRows } from "@/lib/finance";
import { formatAmount, formatInteger, formatPercent } from "@/lib/format";
import { DataProvenanceBadge } from "@/components/data-provenance-badge";
import { DataTable, type DataTableColumn } from "@/components/data-table";
import { EmptyState } from "@/components/empty-state";
import { KpiCard, type KpiTone } from "@/components/kpi-card";
import { PendingFeatures, type PendingFeature } from "@/components/pending-features";
import { RankedBars } from "@/components/ranked-bars";
import { RiskList } from "@/components/risk-list";
import { SectionNav } from "@/components/section-nav";
import { StackedBar } from "@/components/stacked-bar";
import { StatusChip } from "@/components/status-chip";
import { VerdictBanner } from "@/components/verdict-banner";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

const VERDICT_KPI_TONE: Record<"ok" | "warn" | "bad", KpiTone> = { ok: "success", warn: "warning", bad: "danger" };

/** Lo que el mockup y la spec (parte 2 §4) enseñan y no existe: no hay contabilidad,
 * bancos, pasarelas de cobro, facturación ni impuestos en el backend. */
const PENDING_FINANCE: PendingFeature[] = [
  {
    icon: Wallet2,
    title: "Caja, ingresos, beneficio neto y runway",
    description: "Caja disponible, ingresos y gasto del mes, margen neto y meses de runway.",
  },
  {
    icon: LineChart,
    title: "Cash flow y forecast",
    description: "Entradas, salidas y saldo, con escenarios Base / Conservador / Expansión a 3, 6 y 12 meses.",
  },
  {
    icon: FileSpreadsheet,
    title: "P&L consolidado y drill-down",
    description: "Ingresos, coste de mercancía, marketing, software, logística, EBITDA e impuestos hasta el resultado neto.",
  },
  {
    icon: Target,
    title: "Budget vs Real vs Forecast por áreas",
    description: "Presupuesto y gasto por área (marketing, software, logística, legal, operaciones) y análisis de desviaciones.",
  },
  {
    icon: Landmark,
    title: "Tesorería, cuentas a pagar y a cobrar",
    description: "Cuenta operativa, reserva, pendiente de Stripe/PayPal/Amazon, vencimientos y liquidaciones.",
  },
  {
    icon: PiggyBank,
    title: "Working Capital (sin stock)",
    description: "Cobros antes de compra, capital adelantado, cubierto y sin cobertura frente al objetivo 75–90 %.",
  },
  {
    icon: Receipt,
    title: "Fiscalidad, contabilidad y capital",
    description: "IVA e impuestos estimados, obligaciones, conciliación, subvenciones y necesidad de capital.",
  },
  {
    icon: Bot,
    title: "CFO Copilot y Financial Health",
    description: "Preguntas con fuente, periodo y cálculo, y un score explicable de liquidez, rentabilidad y cobertura.",
  },
];

const PENDING_NAV = [
  { label: "Cash flow", icon: LineChart },
  { label: "P&L", icon: FileSpreadsheet },
  { label: "Tesorería", icon: Landmark },
  { label: "Forecast", icon: TrendingUp },
];

function DlRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-3 py-1.5">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="text-right font-medium">{children}</dd>
    </div>
  );
}

export function CfoWorkspace({
  initialReports,
  products,
  totalProducts,
  analysesByProduct,
}: {
  initialReports: CFOReport[];
  products: Product[];
  totalProducts: number;
  analysesByProduct: Record<string, EconomicAnalysis[]>;
}) {
  const [reports, setReports] = useState(initialReports);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const report = reports[0];
  const data = report?.data ?? null;
  const verdict = report ? FINANCIAL_VERDICT[report.financial_health_status] : undefined;
  const budget = data ? budgetBreakdown(data) : undefined;
  const portfolio = useMemo(() => portfolioRows(products, analysesByProduct), [products, analysesByProduct]);
  const risks = data?.risks ?? [];
  const evidence = data?.evidence ?? [];

  async function handleGenerate() {
    setError(null);
    setSubmitting(true);
    try {
      await api.createCFORun();
      setReports(await api.listCFORuns());
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "La generación del informe falló.");
    } finally {
      setSubmitting(false);
    }
  }

  const historyColumns: DataTableColumn<CFOReport>[] = [
    {
      key: "report",
      header: "Informe",
      cell: (row) => (
        <span className="font-mono text-xs">
          {row.correlation_id.slice(0, 8)}
          {row.correlation_id === report?.correlation_id ? (
            <span className="ml-2 rounded bg-primary px-1.5 py-0.5 font-sans text-[10px] font-medium text-primary-foreground">
              Actual
            </span>
          ) : null}
        </span>
      ),
    },
    { key: "status", header: "Salud", cell: (row) => <StatusChip status={row.financial_health_status} /> },
    { key: "products", header: "Productos", cell: (row) => (row.data ? formatInteger(row.data.total_products_analyzed) : "—") },
    {
      key: "nogo",
      header: "NO_GO",
      cell: (row) => (row.data?.no_go_ratio != null ? formatPercent(row.data.no_go_ratio, 0) : "—"),
    },
    {
      key: "budget",
      header: "Uso del presupuesto",
      cell: (row) => (row.data?.budget_utilization != null ? formatPercent(row.data.budget_utilization, 0) : "—"),
    },
  ];

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Informe de salud financiera</CardTitle>
          <CardAction>
            <DataProvenanceBadge
              status="estimated"
              tooltip="Agrega las últimas decisiones económicas, las campañas y las reservas del BudgetEngine. No hay contabilidad real."
            />
          </CardAction>
        </CardHeader>
        <CardContent className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <p className="max-w-3xl text-sm text-muted-foreground">
            Cada informe toma la última decisión económica de cada producto, las campañas y las reservas de presupuesto en
            ese momento. {reports.length > 0 ? `Hay ${reports.length} informe${reports.length === 1 ? "" : "s"} guardado${reports.length === 1 ? "" : "s"}; se muestra el más reciente.` : "Todavía no hay ninguno."}
          </p>
          <Button type="button" size="lg" onClick={handleGenerate} disabled={submitting} className="shrink-0">
            {submitting ? <Loader2 className="animate-spin" /> : <ShieldCheck />}
            {submitting ? "Generando…" : report ? "Generar informe nuevo" : "Generar informe de salud financiera"}
          </Button>
        </CardContent>
      </Card>

      {error ? (
        <Alert variant="destructive">
          <AlertTriangle className="size-4" />
          <AlertTitle>La generación del informe falló</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}

      {!report || !data || !verdict || !budget ? (
        <Card>
          <CardContent>
            <EmptyState
              icon={Wallet}
              title="Sin informes financieros todavía"
              description="Genera el primer informe para ver aquí el estado agregado del catálogo, el presupuesto y la cartera de productos."
            />
          </CardContent>
        </Card>
      ) : (
        <>
          <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6" aria-label="Indicadores financieros">
            <KpiCard
              label="Salud financiera"
              value={verdict.title}
              icon={ShieldCheck}
              tone={VERDICT_KPI_TONE[verdict.tone]}
              caption={`Recomendación ${report.recommendation} · confianza ${formatPercent(report.confidence, 0)}`}
              provenance="estimated"
              provenanceTooltip="Estado calculado por el agente CFO con reglas fijas sobre las decisiones y el presupuesto."
            />
            <KpiCard
              label="Productos analizados"
              value={formatInteger(data.total_products_analyzed)}
              icon={Boxes}
              caption={`${data.go_count} GO · ${data.review_count} REVISIÓN · ${data.no_go_count} NO_GO`}
              provenance="estimated"
              provenanceTooltip="Última decisión económica de cada producto; las cifras son estimaciones simuladas."
            />
            <KpiCard
              label="Decisiones NO_GO"
              value={data.no_go_ratio !== null ? formatPercent(data.no_go_ratio, 0) : "—"}
              icon={Scale}
              caption={data.no_go_ratio !== null ? "Sobre los productos analizados" : "Aún no hay análisis económicos"}
              provenance="estimated"
            />
            <KpiCard
              label="Uso del presupuesto"
              value={budget.utilization !== null ? formatPercent(budget.utilization, 0) : "—"}
              icon={Gauge}
              caption={budget.utilization !== null ? "Reservado + comprometido + gastado" : "Sin presupuestos registrados"}
              provenance={budget.utilization !== null ? "verified" : "pending"}
              provenanceTooltip={
                budget.utilization !== null
                  ? "Reservas del BudgetEngine registradas en la base de datos."
                  : "Ningún objetivo ha pedido todavía aprobación de gasto, así que no hay presupuesto registrado."
              }
            />
            <KpiCard
              label="Campañas listas"
              value={`${data.active_campaigns}/${data.total_campaigns}`}
              icon={Megaphone}
              caption="Propuestas en estado READY"
              provenance="estimated"
            />
            <KpiCard
              label="Presupuesto diario"
              value={formatAmount(data.total_daily_budget)}
              icon={Banknote}
              caption="Suma de las campañas listas"
              provenance="estimated"
              provenanceTooltip="Presupuesto diario propuesto en campañas simuladas; no es gasto real."
            />
          </section>

          <SectionNav
            label="Secciones del informe financiero"
            items={[
              { label: "Presupuesto", href: "#presupuesto", icon: Wallet },
              { label: "Salud financiera", href: "#salud", icon: ShieldCheck },
              { label: "Cartera de productos", href: "#cartera", icon: Boxes },
              { label: "Historial", href: "#historial", icon: CalendarClock },
              ...PENDING_NAV.map((item) => ({
                ...item,
                pendingReason: "Pendiente: el backend no tiene contabilidad ni tesorería",
              })),
            ]}
          />

          <section className="grid gap-4 xl:grid-cols-12">
            <Card id="presupuesto" className="scroll-mt-4 xl:col-span-6">
              <CardHeader>
                <CardTitle>Presupuesto global</CardTitle>
                <CardAction>
                  <DataProvenanceBadge
                    status={budget.limit > 0 ? "verified" : "pending"}
                    tooltip={
                      budget.limit > 0
                        ? "Totales de las reservas del BudgetEngine registradas en la base de datos."
                        : "Todavía no hay presupuestos registrados."
                    }
                  />
                </CardAction>
              </CardHeader>
              <CardContent className="space-y-4">
                {budget.limit > 0 ? (
                  <>
                    <div className="flex items-baseline justify-between gap-3">
                      <p className="text-2xl font-semibold">{formatAmount(budget.limit)}</p>
                      <p className="text-xs text-muted-foreground">Límite máximo total</p>
                    </div>
                    <StackedBar
                      ariaLabel="Reparto del límite de presupuesto"
                      total={budget.limit}
                      segments={[
                        { key: "spent", label: "Gastado", value: budget.spent, valueLabel: formatAmount(budget.spent), className: "bg-primary" },
                        { key: "committed", label: "Comprometido", value: budget.committed, valueLabel: formatAmount(budget.committed), className: "bg-sky-500" },
                        { key: "reserved", label: "Reservado", value: budget.reserved, valueLabel: formatAmount(budget.reserved), className: "bg-amber-500" },
                        { key: "available", label: "Disponible", value: budget.available, valueLabel: formatAmount(budget.available), className: "bg-muted-foreground/40" },
                      ]}
                    />
                    {budget.overLimit ? (
                      <p className="text-xs font-medium text-destructive">El uso supera el límite máximo.</p>
                    ) : null}
                  </>
                ) : (
                  <p className="rounded-lg border border-dashed p-3 text-sm text-muted-foreground">
                    No hay presupuestos registrados: ningún objetivo ha pedido todavía una aprobación de gasto, así que
                    el BudgetEngine no ha guardado reservas.
                  </p>
                )}
                <div className="flex flex-wrap items-center gap-2 rounded-lg border border-dashed p-3 text-xs text-muted-foreground">
                  <DataProvenanceBadge
                    status="pending"
                    tooltip="El presupuesto se guarda como un total, sin dividirlo por áreas."
                  />
                  Distribución por áreas (marketing, operaciones, software, legal…) y solicitud de nuevo presupuesto.
                </div>
              </CardContent>
            </Card>

            <Card id="salud" className="scroll-mt-4 xl:col-span-6">
              <CardHeader>
                <CardTitle>Salud financiera</CardTitle>
                <CardAction>
                  <DataProvenanceBadge
                    status="estimated"
                    tooltip="El agente clasifica con reglas fijas, no con un score explicable de siete componentes."
                  />
                </CardAction>
              </CardHeader>
              <CardContent className="space-y-4">
                <VerdictBanner tone={verdict.tone} title={verdict.title} detail={verdict.detail} />
                <RiskList risks={risks} />
                {evidence.length > 0 ? (
                  <div>
                    <p className="text-xs font-medium text-muted-foreground">Evidencias del informe</p>
                    <ul className="mt-1 list-inside list-disc text-sm">
                      {evidence.map((line) => (
                        <li key={line}>{line}</li>
                      ))}
                    </ul>
                  </div>
                ) : null}
                <div>
                  <p className="mb-1.5 text-xs font-medium text-muted-foreground">Reglas que aplica el agente hoy</p>
                  <ul className="divide-y rounded-lg border text-sm">
                    {CFO_RULES.map((item) => (
                      <li key={item.rule} className="flex items-start justify-between gap-3 px-3 py-2">
                        <span>{item.rule}</span>
                        <span
                          className={cn(
                            "shrink-0 text-xs font-medium",
                            item.result === "Crítica" && "text-red-500",
                            item.result === "En riesgo" && "text-amber-500",
                            item.result === "Requiere revisión" && "text-amber-500",
                            item.result === "Saludable" && "text-primary",
                          )}
                        >
                          {item.result}
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
                <p className="text-[11px] text-muted-foreground">Riesgos y evidencias: texto del agente (en inglés).</p>
              </CardContent>
            </Card>
          </section>

          <section className="grid gap-4 xl:grid-cols-12">
            <Card id="cartera" className="scroll-mt-4 xl:col-span-5">
              <CardHeader>
                <CardTitle>Cartera de productos</CardTitle>
                <CardAction>
                  <DataProvenanceBadge
                    status="estimated"
                    tooltip="Recomendaciones de la última decisión económica de cada producto, sobre supuestos simulados."
                  />
                </CardAction>
              </CardHeader>
              <CardContent className="space-y-4">
                <StackedBar
                  ariaLabel="Decisiones económicas por resultado"
                  segments={[
                    { key: "go", label: "GO", value: data.go_count, valueLabel: formatInteger(data.go_count), className: "bg-primary" },
                    { key: "review", label: "Revisión", value: data.review_count, valueLabel: formatInteger(data.review_count), className: "bg-amber-500" },
                    { key: "nogo", label: "NO_GO", value: data.no_go_count, valueLabel: formatInteger(data.no_go_count), className: "bg-red-500" },
                  ]}
                />
                <dl className="divide-y text-sm">
                  <DlRow label="Productos con análisis">{formatInteger(data.total_products_analyzed)}</DlRow>
                  <DlRow label="Productos del catálogo">{formatInteger(totalProducts)}</DlRow>
                </dl>
                <p className="text-[11px] text-muted-foreground">
                  Rentabilidad por canal, país, proveedor, campaña o proyecto: pendiente, no hay datos de ventas
                  reales que agrupar.
                </p>
              </CardContent>
            </Card>

            <Card className="xl:col-span-7">
              <CardHeader>
                <CardTitle>Rentabilidad por producto</CardTitle>
                <CardAction>
                  <DataProvenanceBadge
                    status="estimated"
                    tooltip="Beneficio mensual del escenario base de la última decisión económica: una estimación simulada, no un resultado real."
                  />
                </CardAction>
              </CardHeader>
              <CardContent className="space-y-3">
                {portfolio.length > 0 ? (
                  <RankedBars
                    ariaLabel="Beneficio mensual estimado por producto"
                    items={portfolio.map((row) => ({
                      key: row.productId,
                      label: row.name,
                      sublabel: `${row.category} · margen ${formatPercent(row.marginPercent)} · ${row.recommendation}`,
                      value: row.monthlyProfit,
                      valueLabel: row.monthlyProfit !== null ? formatAmount(row.monthlyProfit) : "Sin escenario",
                    }))}
                  />
                ) : (
                  <p className="text-sm text-muted-foreground">Ningún producto tiene todavía un análisis económico.</p>
                )}
                <p className="text-[11px] text-muted-foreground">
                  Beneficio mensual estimado (escenario base) de la última decisión de cada producto.
                  {totalProducts > products.length
                    ? ` Se leen los ${products.length} primeros de ${totalProducts} productos: no hay un endpoint agregado.`
                    : ""}{" "}
                  Los unit economics se calculan en Economía y rentabilidad; aquí solo se listan.
                </p>
              </CardContent>
            </Card>
          </section>

          <Card id="historial" className="scroll-mt-4">
            <CardHeader>
              <CardTitle>Historial de informes</CardTitle>
            </CardHeader>
            <CardContent>
              <DataTable
                columns={historyColumns}
                rows={reports}
                getRowId={(row) => row.correlation_id}
                emptyMessage="Aún no hay informes."
              />
            </CardContent>
          </Card>

          <PendingFeatures
            title="Finanzas de empresa — pendiente de backend"
            tooltip="Requieren contabilidad, tesorería, pasarelas de cobro, facturación e impuestos que el backend aún no tiene."
            items={PENDING_FINANCE}
            columns={4}
            note="Hoy el agente CFO solo agrega decisiones económicas, campañas y reservas de presupuesto. No existen movimientos de caja, ingresos reales, cuentas a pagar/cobrar, impuestos ni contabilidad, así que no se muestra ningún dato de caja, P&L ni forecast."
          />
        </>
      )}
    </div>
  );
}
