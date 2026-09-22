"use client";

import { useMemo, useRef, useState, useSyncExternalStore } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Menu } from "@base-ui/react/menu";
import {
  AlertTriangle,
  ArrowRight,
  Boxes,
  Brain,
  Calculator,
  ChevronDown,
  CircleCheck,
  CircleDollarSign,
  CreditCard,
  Ellipsis,
  FileSearch,
  Gauge,
  Landmark,
  Loader2,
  Megaphone,
  Package,
  PackageSearch,
  Pencil,
  Plus,
  Rocket,
  Save,
  Scale,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Tag,
  Target,
  TrendingDown,
  TrendingUp,
  Truck,
  Undo2,
  Warehouse,
  Activity,
  type LucideIcon,
} from "lucide-react";
import { ApiError, api, type EconomicAnalysis, type Product, type SupplierQuote } from "@/lib/api";
import { DEMO_PRODUCT_META } from "@/lib/demo/economics";
import { buildBaseline } from "@/lib/economics-baseline";
import { dedupeQuotesBySupplier } from "@/lib/economics";
import {
  costLines,
  economicRisk,
  evaluate,
  profitCurve,
  scenarios as buildScenarios,
  sensitivity,
  verdict,
  viabilityItems,
  type CostKey,
  type EconomicsInputs,
  type ScenarioKey,
} from "@/lib/economics-model";
import { formatEuro, formatInteger, formatPercent } from "@/lib/format";
import { regionLabel } from "@/lib/regions";
import { DataProvenanceBadge } from "@/components/data-provenance-badge";
import { EmptyState } from "@/components/empty-state";
import { Flag, regionFlag } from "@/components/flag";
import { KpiCard } from "@/components/kpi-card";
import { LineChart } from "@/components/line-chart";
import { NextStepBar } from "@/components/next-step-bar";
import { PageHeader } from "@/components/page-header";
import { ScenarioCard } from "@/components/scenario-card";
import { SectionNav } from "@/components/section-nav";
import { SensitivityBars } from "@/components/sensitivity-bars";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { ECONOMICS_DESCRIPTION, ECONOMICS_TITLE } from "./copy";

const PRODUCT_STATUS_LABEL: Record<string, string> = { CANDIDATE: "Candidato" };

const COST_ICON: Record<CostKey, LucideIcon> = {
  supplier: Package,
  transport: Truck,
  tariff: Landmark,
  fulfillment: Warehouse,
  payment: CreditCard,
  returns: Undo2,
  cac: Megaphone,
  other: Ellipsis,
};

const SCENARIO_ICON: Record<ScenarioKey, LucideIcon> = {
  conservative: Scale,
  base: Target,
  optimistic: TrendingUp,
};

const SCENARIO_COLOR: Record<ScenarioKey, string> = {
  conservative: "#8fa3ad",
  base: "var(--emerald)",
  optimistic: "#5aa9e6",
};

const SECTIONS = [
  { id: "escenarios", label: "Escenarios", icon: Target },
  { id: "desglose", label: "Desglose de costes", icon: Boxes },
  { id: "simulacion", label: "Simulación", icon: SlidersHorizontal },
  { id: "sensibilidad", label: "Sensibilidad", icon: Activity },
  { id: "equilibrio", label: "Punto de equilibrio", icon: Gauge },
  { id: "riesgo", label: "Riesgo y capital", icon: ShieldCheck },
  { id: "resumen", label: "Resumen y decisión", icon: CircleCheck },
] as const;

const TONE_TEXT = { ok: "text-primary", warn: "text-warning", bad: "text-destructive" } as const;

/** Minuto actual; en el servidor null, para no desajustar la hidratación. */
function useMinute(): number | null {
  return useSyncExternalStore(
    (onChange) => {
      const id = window.setInterval(onChange, 15_000);
      return () => window.clearInterval(id);
    },
    () => Math.floor(Date.now() / 60_000),
    () => null,
  );
}

function niceCeil(value: number): number {
  if (value <= 0) return 1;
  const magnitude = 10 ** Math.floor(Math.log10(value));
  return [1, 2, 2.5, 5, 10].map((m) => m * magnitude).find((v) => v >= value) ?? value;
}

function compactEuro(value: number): string {
  return formatEuro(value, 0);
}

function InfoTile({ label, icon: Icon, children }: { label: string; icon?: LucideIcon; children: React.ReactNode }) {
  return (
    <div className="min-w-0 rounded-lg border bg-background/40 p-3">
      <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
        {Icon ? <Icon className="size-3.5 shrink-0" /> : null}
        {label}
      </p>
      <div className="mt-1.5">{children}</div>
    </div>
  );
}

interface SliderField {
  key: "salePrice" | "supplierCost" | "cac" | "returnsPct" | "conversionPct" | "monthlyOrders";
  label: string;
  min: number;
  max: number;
  step: number;
  suffix: string;
}

export function EconomicsWorkspace({
  products,
  productId,
  quotes,
  latestAnalysis,
  requestedQuoteId,
}: {
  products: Product[];
  productId?: string;
  quotes: SupplierQuote[];
  latestAnalysis?: EconomicAnalysis;
  requestedQuoteId?: string;
}) {
  const router = useRouter();
  const minute = useMinute();
  const priceInputRef = useRef<HTMLInputElement>(null);
  const simulatorRef = useRef<HTMLDivElement>(null);

  const product = products.find((p) => p.id === productId);
  const keepId = requestedQuoteId ?? latestAnalysis?.supplier_quote_id;
  const quoteOptions = useMemo(() => dedupeQuotesBySupplier(quotes, keepId), [quotes, keepId]);
  const [quoteId, setQuoteId] = useState(
    () => (quoteOptions.find((q) => q.id === keepId) ?? quoteOptions[0])?.id,
  );
  const quote = quoteOptions.find((q) => q.id === quoteId);
  const baseline = useMemo(() => buildBaseline(quote, latestAnalysis), [quote, latestAnalysis]);

  const [inputs, setInputs] = useState<EconomicsInputs>(baseline.inputs);
  const [section, setSection] = useState<string>("escenarios");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (products.length === 0 || !product) {
    return (
      <div>
        <PageHeader title={ECONOMICS_TITLE} description={ECONOMICS_DESCRIPTION} />
        <Card>
          <CardContent>
            <EmptyState
              icon={PackageSearch}
              title="Aún no hay productos que analizar"
              description="El análisis económico parte de un producto investigado y de una cotización de proveedor."
              action={
                <Button size="sm" variant="outline" nativeButton={false} render={<Link href="/research" />}>
                  Ir a Investigación
                </Button>
              }
            />
          </CardContent>
        </Card>
      </div>
    );
  }

  const result = evaluate(inputs);
  const scenarioResults = buildScenarios(inputs);
  const lines = costLines(inputs);
  const risk = economicRisk(inputs);
  const decision = verdict(inputs);
  const viability = viabilityItems(inputs);
  const sensitivityItems = sensitivity(inputs);
  const maxImpact = Math.max(...sensitivityItems.map((s) => s.impact), 0.0001);
  const estimatedCount = lines.filter((l) => baseline.costSources[l.key] === "estimated").length;
  const demoFields = [
    ...baseline.demoFields,
    "score de investigación, mercado objetivo, modelo logístico y descripción del producto",
  ];

  // Coste frente a la media de cotizaciones reales (solo si hay con qué comparar).
  const avgLanded =
    quoteOptions.length > 1
      ? quoteOptions.reduce((sum, q) => sum + q.total_landed_cost_per_unit, 0) / quoteOptions.length
      : undefined;
  const vsAverage = quote && avgLanded ? quote.total_landed_cost_per_unit / avgLanded - 1 : undefined;

  // Evolución del beneficio por escenario según los pedidos al mes.
  const optimisticOrders = scenarioResults[2].inputs.monthlyOrders;
  const evolutionStep = niceCeil(Math.max(optimisticOrders, 60) / 6);
  const evolutionXs = Array.from({ length: 7 }, (_, k) => evolutionStep * k);
  const evolutionSeries = scenarioResults.map((s) => ({
    key: s.key,
    label: s.label,
    color: SCENARIO_COLOR[s.key],
    points: profitCurve(s.inputs, evolutionXs),
  }));

  // Punto de equilibrio: beneficio del caso base según las unidades vendidas.
  const breakEven = result.breakEvenUnits;
  const breakEvenStep = niceCeil(Math.max((breakEven ?? inputs.monthlyOrders) * 2.2, 20) / 4);
  const breakEvenXs = Array.from({ length: 5 }, (_, k) => breakEvenStep * k);

  function update<K extends keyof EconomicsInputs>(key: K, value: number) {
    if (!Number.isFinite(value)) return;
    setSaved(false);
    setInputs((current) => {
      if (key === "conversionPct" && current.conversionPct > 0) {
        // El tráfico se mantiene: los pedidos cambian en proporción a la conversión.
        return { ...current, conversionPct: value, monthlyOrders: Math.round((current.monthlyOrders * value) / current.conversionPct) };
      }
      return { ...current, [key]: value };
    });
  }

  function selectSection(id: string) {
    setSection(id);
  }

  function changeProduct(id: string) {
    router.push(`/economics?${new URLSearchParams({ product_id: id }).toString()}`);
  }

  function changeQuote(id: string) {
    setQuoteId(id);
    const next = quoteOptions.find((q) => q.id === id);
    const nextBaseline = buildBaseline(next, latestAnalysis);
    setInputs((current) => ({
      ...current,
      supplierCost: nextBaseline.inputs.supplierCost,
      transport: nextBaseline.inputs.transport,
      tariff: nextBaseline.inputs.tariff,
      initialInvestment: nextBaseline.inputs.initialInvestment,
    }));
    setSaved(false);
  }

  function focusPrice() {
    simulatorRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
    priceInputRef.current?.focus();
  }

  function goLegal() {
    router.push(`/legal?${new URLSearchParams({ product_id: product!.id }).toString()}`);
  }

  function validateWithCeo() {
    const params = new URLSearchParams({
      title: `Validar economía de ${product!.name}`,
      unit_cost: result.unitCost.toFixed(2),
      sale_price: String(inputs.salePrice),
      monthly_fixed_costs: String(inputs.monthlyFixedCosts),
      monthly_unit_sales: String(inputs.monthlyOrders),
    });
    router.push(`/ceo?${params.toString()}`);
  }

  async function saveAnalysis() {
    if (!quote) return;
    setError(null);
    setSaving(true);
    try {
      await api.createEconomicAnalysisRun({
        product_id: product!.id,
        supplier_quote_id: quote.id,
        sale_price: inputs.salePrice,
        monthly_fixed_costs: inputs.monthlyFixedCosts,
      });
      setSaved(true);
      router.refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "No se pudo guardar el análisis.");
    } finally {
      setSaving(false);
    }
  }

  const sliders: SliderField[] = [
    { key: "salePrice", label: "Precio de venta", min: 0, max: Math.max(60, baseline.inputs.salePrice * 2), step: 0.1, suffix: "€" },
    { key: "supplierCost", label: "Coste proveedor", min: 0, max: Math.max(30, baseline.inputs.supplierCost * 3), step: 0.1, suffix: "€" },
    { key: "cac", label: "CAC (publicidad)", min: 0, max: Math.max(12, baseline.inputs.cac * 3), step: 0.1, suffix: "€" },
    { key: "returnsPct", label: "Tasa de devoluciones", min: 0, max: 25, step: 0.5, suffix: "%" },
    { key: "conversionPct", label: "Conversión estimada", min: 0.2, max: 8, step: 0.1, suffix: "%" },
    { key: "monthlyOrders", label: "Pedidos mensuales", min: 0, max: Math.max(1000, baseline.inputs.monthlyOrders * 3), step: 10, suffix: "" },
  ];

  const flag = regionFlag(baseline.supplier.region);

  return (
    <div className="space-y-5">
      <PageHeader
        title={ECONOMICS_TITLE}
        description={ECONOMICS_DESCRIPTION}
        actions={
          <>
            <DataProvenanceBadge
              status="demo"
              tooltip={`Incluye datos de demostración hasta que el backend los proporcione: ${demoFields.join("; ")}.`}
            />
            <div className="text-sm leading-tight">
              <p className="text-muted-foreground">
                {minute === null ? "—" : new Date(minute * 60_000).toLocaleDateString("es-ES", { day: "numeric", month: "short", year: "numeric" })}
              </p>
              <p className="font-medium tabular-nums">
                {minute === null ? "" : new Date(minute * 60_000).toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit" })}
              </p>
            </div>
            <label className="relative flex w-64 max-w-full flex-col rounded-lg border bg-card px-3 py-2 text-xs text-muted-foreground">
              Producto activo
              <select
                value={product.id}
                onChange={(e) => changeProduct(e.target.value)}
                className="mt-0.5 appearance-none bg-transparent pr-6 text-sm font-medium text-primary outline-none"
              >
                {products.map((p) => (
                  <option key={p.id} value={p.id} className="bg-popover text-foreground">
                    {p.name}
                  </option>
                ))}
              </select>
              <ChevronDown className="pointer-events-none absolute right-3 bottom-2.5 size-4 text-foreground" />
            </label>
          </>
        }
      />

      {/* Producto activo y contexto */}
      <Card>
        <CardContent className="grid gap-3 lg:grid-cols-2 2xl:grid-cols-[minmax(0,1.9fr)_repeat(4,minmax(0,1fr))]">
          <div className="flex min-w-0 gap-4 lg:col-span-2 2xl:col-span-1">
            <div className="flex size-24 shrink-0 items-center justify-center rounded-xl border bg-background/60 text-primary">
              <Package className="size-10" />
            </div>
            <div className="min-w-0 space-y-1.5">
              <p className="truncate text-base font-semibold">{product.name}</p>
              <div className="flex flex-wrap gap-1.5">
                <Badge variant="outline" className="border-primary/40 text-primary">
                  {product.category}
                </Badge>
                <Badge variant="outline">{PRODUCT_STATUS_LABEL[product.status] ?? product.status}</Badge>
              </div>
              <p className="line-clamp-2 text-xs text-muted-foreground">{DEMO_PRODUCT_META.description}</p>
              <Button size="xs" variant="outline" nativeButton={false} render={<Link href="/research" />}>
                Ver detalles del producto <ArrowRight />
              </Button>
            </div>
          </div>
          <InfoTile label="Score investigación" icon={FileSearch}>
            <p className="text-2xl font-semibold text-primary">
              {DEMO_PRODUCT_META.researchScore}
              <span className="text-base">/100</span>
            </p>
          </InfoTile>
          <InfoTile label="Proveedor seleccionado" icon={ShieldCheck}>
            {quoteOptions.length > 1 ? (
              <div className="relative">
                <select
                  value={quote?.id}
                  onChange={(e) => changeQuote(e.target.value)}
                  aria-label="Proveedor seleccionado"
                  className="w-full appearance-none truncate bg-transparent pr-5 text-sm font-medium outline-none"
                >
                  {quoteOptions.map((q) => (
                    <option key={q.id} value={q.id} className="bg-popover text-foreground">
                      {q.data?.name ?? q.supplier_id} · {formatEuro(q.total_landed_cost_per_unit)}
                    </option>
                  ))}
                </select>
                <ChevronDown className="pointer-events-none absolute top-0.5 right-0 size-4" />
              </div>
            ) : (
              <p className="truncate text-sm font-medium">{baseline.supplier.name}</p>
            )}
            <p className="mt-1 flex items-center gap-1.5 text-xs text-muted-foreground">
              {flag ? <Flag code={flag} /> : null}
              {regionLabel(baseline.supplier.region)}
            </p>
          </InfoTile>
          <InfoTile label="Mercado objetivo">
            <p className="flex items-center gap-2 text-lg font-semibold text-primary">
              {DEMO_PRODUCT_META.marketLabel}
              {DEMO_PRODUCT_META.markets.map((m) => (
                <Flag key={m} code={m} />
              ))}
            </p>
          </InfoTile>
          <InfoTile label="Modelo logístico">
            <p className="flex items-center gap-2 text-base font-medium">
              <Truck className="size-5 text-primary" />
              {DEMO_PRODUCT_META.logisticsModel}
            </p>
          </InfoTile>
        </CardContent>
      </Card>

      {/* KPIs */}
      <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-6" aria-label="Indicadores económicos">
        <KpiCard
          label="Precio de venta"
          value={formatEuro(inputs.salePrice)}
          accent
          footer={
            <Button size="xs" variant="outline" onClick={focusPrice}>
              <Pencil /> Editable
            </Button>
          }
        />
        <KpiCard
          label="Coste total por unidad"
          value={formatEuro(result.unitCost)}
          caption={
            vsAverage !== undefined
              ? `${vsAverage <= 0 ? "" : "+"}${formatPercent(vsAverage, 0)} vs. media de cotizaciones`
              : "Producto, logística y comisiones"
          }
        />
        <KpiCard
          label="Margen de contribución"
          value={formatEuro(result.contribution)}
          accent={result.contribution > 0}
          tone={result.contribution > 0 ? "default" : "danger"}
          caption={`${formatPercent(result.contributionMargin)} del precio`}
        />
        <KpiCard
          label="Beneficio estimado (mes)"
          value={formatEuro(result.monthlyProfit, 0)}
          accent={result.monthlyProfit > 0}
          tone={result.monthlyProfit > 0 ? "default" : "danger"}
          caption={`Escenario base · ${formatInteger(inputs.monthlyOrders)} pedidos/mes`}
        />
        <KpiCard
          label="Punto de equilibrio"
          value={breakEven !== null ? `${formatInteger(breakEven)} unidades` : "No se alcanza"}
          tone={breakEven !== null ? "default" : "danger"}
          caption={
            result.paybackMonths !== null
              ? `Recupera la inversión en ${result.paybackMonths.toLocaleString("es-ES", { maximumFractionDigits: 1 })} meses`
              : "Sin beneficio no se recupera la inversión"
          }
        />
        <KpiCard
          label="Riesgo económico"
          value={risk.level}
          accent={risk.level === "Bajo"}
          tone={risk.level === "Medio" ? "warning" : risk.level === "Alto" ? "danger" : "default"}
          footer={
            <div className="flex gap-1" aria-label={`Nivel de riesgo ${risk.score} de 5`}>
              {Array.from({ length: 5 }, (_, k) => (
                <span
                  key={k}
                  className={cn(
                    "h-1.5 flex-1 rounded-full",
                    k < risk.score
                      ? risk.level === "Bajo"
                        ? "bg-primary"
                        : risk.level === "Medio"
                          ? "bg-warning"
                          : "bg-destructive"
                      : "bg-muted",
                  )}
                />
              ))}
            </div>
          }
        />
      </section>

      <SectionNav
        label="Secciones del análisis"
        items={SECTIONS.map((s) => ({
          label: s.label,
          icon: s.icon,
          href: `#${s.id}`,
          active: section === s.id,
          onClick: () => selectSection(s.id),
        }))}
      />

      {error ? (
        <Alert variant="destructive">
          <AlertTriangle className="size-4" />
          <AlertTitle>No se pudo completar la operación</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}

      {/* Escenarios · Desglose · Simulador */}
      <section className="grid gap-4 xl:grid-cols-2 2xl:grid-cols-[minmax(0,1.45fr)_minmax(0,1fr)_minmax(0,1.15fr)]">
        <Card id="escenarios" className="scroll-mt-4 xl:col-span-2 2xl:col-span-1">
          <CardHeader>
            <CardTitle>Comparativa de escenarios</CardTitle>
            <CardDescription>Analiza diferentes escenarios para evaluar la robustez del negocio.</CardDescription>
            <CardAction>
              <Button
                size="xs"
                variant="ghost"
                className="text-primary"
                onClick={() => simulatorRef.current?.scrollIntoView({ behavior: "smooth", block: "center" })}
              >
                <Plus /> Nuevo escenario
              </Button>
            </CardAction>
          </CardHeader>
          <CardContent className="space-y-5">
            <div className="grid gap-3 sm:grid-cols-3">
              {scenarioResults.map((s) => (
                <ScenarioCard
                  key={s.key}
                  title={s.label}
                  icon={SCENARIO_ICON[s.key]}
                  badge={s.key === "base" ? "Actual" : undefined}
                  highlighted={s.key === "base"}
                  headline={{ label: "precio de venta", value: formatEuro(s.inputs.salePrice) }}
                  metrics={[
                    { label: "pedidos/mes", value: formatInteger(s.inputs.monthlyOrders) },
                    { label: "margen", value: formatPercent(s.result.netMargin) },
                    { label: "beneficio", value: formatEuro(s.result.monthlyProfit, 0) },
                  ]}
                />
              ))}
            </div>
            <div>
              <p className="mb-2 text-sm font-medium">Evolución del beneficio estimado</p>
              <LineChart
                ariaLabel="Beneficio mensual estimado por escenario según los pedidos al mes"
                series={evolutionSeries}
                formatY={compactEuro}
                xLabel="Pedidos al mes"
                hoverTitle={(x) => `${formatInteger(x)} pedidos/mes`}
                defaultHoverX={evolutionXs[2]}
              />
            </div>
          </CardContent>
        </Card>

        <Card id="desglose" className="scroll-mt-4">
          <CardHeader>
            <CardTitle>Desglose económico por unidad</CardTitle>
            <CardDescription>Todos los costes, verificados y estimados.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-1.5">
            <div className="flex items-center gap-2 rounded-md bg-background/50 px-2 py-2 text-[13px]">
              <Tag className="size-4 shrink-0 text-muted-foreground" />
              <span className="flex-1">Precio cobrado al cliente</span>
              <span className="font-medium tabular-nums">{formatEuro(inputs.salePrice)}</span>
              <span className="w-[4.25rem] shrink-0" />
            </div>
            {lines.map((line) => {
              const Icon = COST_ICON[line.key];
              return (
                <div key={line.key} className="flex items-center gap-2 rounded-md px-2 py-1.5 text-[13px]">
                  <Icon className="size-4 shrink-0 text-muted-foreground" />
                  <span className="min-w-0 flex-1 truncate text-muted-foreground">{line.label}</span>
                  <span className="shrink-0 text-destructive tabular-nums">{formatEuro(-line.amount)}</span>
                  <DataProvenanceBadge
                    compact
                    status={line.key === "supplier" && baseline.supplier.isDemo ? "third_party" : baseline.costSources[line.key]}
                    className="w-[4.25rem] shrink-0 justify-center px-1 text-[10px]"
                  />
                </div>
              );
            })}
            <div className="mt-2 flex items-center gap-3 rounded-lg border border-primary/40 bg-primary/10 px-3 py-2.5 text-sm font-semibold text-primary">
              <span className="flex-1">Margen de contribución</span>
              <span className="tabular-nums">{formatEuro(result.contribution)}</span>
              <span className="tabular-nums">{formatPercent(result.contributionMargin)}</span>
            </div>
          </CardContent>
        </Card>

        <Card id="simulacion" className="scroll-mt-4" ref={simulatorRef}>
          <CardHeader>
            <CardTitle>Simulador interactivo</CardTitle>
            <CardDescription>Ajusta las variables y observa el impacto en tiempo real.</CardDescription>
            <CardAction>
              <Button size="xs" variant="outline" onClick={() => setInputs(baseline.inputs)}>
                Restablecer
              </Button>
            </CardAction>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-3">
              {sliders.map((field) => (
                <div key={field.key} className="grid grid-cols-[minmax(0,7.75rem)_1fr_5rem] items-center gap-2.5 text-[13px]">
                  <label htmlFor={`sim-${field.key}`} className="truncate text-muted-foreground">
                    {field.label}
                  </label>
                  <input
                    type="range"
                    aria-label={field.label}
                    min={field.min}
                    max={field.max}
                    step={field.step}
                    value={inputs[field.key]}
                    onChange={(e) => update(field.key, Number(e.target.value))}
                    className="h-1.5 w-full cursor-pointer accent-primary"
                  />
                  <div className="flex items-center rounded-md border bg-background/60 px-2 py-1">
                    <input
                      id={`sim-${field.key}`}
                      ref={field.key === "salePrice" ? priceInputRef : undefined}
                      type="number"
                      min={field.min}
                      step={field.step}
                      value={Math.round(inputs[field.key] * 100) / 100}
                      onChange={(e) => update(field.key, Number(e.target.value))}
                      className="w-full min-w-0 bg-transparent text-right text-sm tabular-nums outline-none [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none"
                    />
                    {field.suffix ? <span className="ml-1 text-xs text-muted-foreground">{field.suffix}</span> : null}
                  </div>
                </div>
              ))}
            </div>
            <div>
              <p className="mb-2 text-sm font-medium">Resultados en tiempo real</p>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                {[
                  { label: "Ingresos/mes", value: formatEuro(result.monthlyRevenue, 0) },
                  { label: "Beneficio/mes", value: formatEuro(result.monthlyProfit, 0), bad: result.monthlyProfit <= 0 },
                  { label: "Margen neto", value: formatPercent(result.netMargin), bad: result.netMargin <= 0 },
                  { label: "Break-even", value: breakEven !== null ? `${formatInteger(breakEven)} uds` : "—", bad: breakEven === null },
                ].map((item) => (
                  <div key={item.label} className="min-w-0 rounded-lg border bg-background/40 px-2 py-2">
                    <p className="truncate text-[11px] text-muted-foreground">{item.label}</p>
                    <p className={cn("mt-1 text-sm font-semibold whitespace-nowrap tabular-nums", item.bad && "text-destructive")}>
                      {item.value}
                    </p>
                  </div>
                ))}
              </div>
            </div>
          </CardContent>
        </Card>
      </section>

      {/* Sensibilidad · Punto de equilibrio · Viabilidad */}
      <section className="grid gap-4 xl:grid-cols-2 2xl:grid-cols-[minmax(0,1fr)_minmax(0,1.45fr)_minmax(0,1.05fr)]">
        <Card id="sensibilidad" className="scroll-mt-4">
          <CardHeader>
            <CardTitle>Análisis de sensibilidad</CardTitle>
            <CardDescription>Impacto en el beneficio ante cambios en las variables clave.</CardDescription>
          </CardHeader>
          <CardContent>
            <SensitivityBars
              ariaLabel="Impacto en el beneficio de cada variable"
              items={sensitivityItems.map((s) => ({
                key: s.key,
                label: s.label,
                value: s.impact / maxImpact,
                level: s.level,
                detail: `${formatPercent(-s.impact, 0)} de beneficio mensual`,
              }))}
            />
          </CardContent>
        </Card>

        <Card id="equilibrio" className="scroll-mt-4 xl:col-span-2 xl:row-start-2 2xl:col-span-1 2xl:row-start-auto">
          <CardHeader>
            <CardTitle>Punto de equilibrio</CardTitle>
            <CardDescription>Unidades necesarias para cubrir todos los costes.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <LineChart
              ariaLabel="Beneficio mensual según las unidades vendidas"
              legend={false}
              series={[
                {
                  key: "profit",
                  label: "Beneficio",
                  color: "var(--emerald)",
                  points: profitCurve(inputs, breakEvenXs),
                },
              ]}
              formatY={compactEuro}
              xLabel="Unidades vendidas"
              yLabel="Beneficio (€)"
              hoverTitle={(x) => `${formatInteger(x)} unidades`}
              markers={breakEven !== null ? [{ x: breakEven, y: 0, label: ["Break-even", `${formatInteger(breakEven)} unidades`] }] : []}
              height={200}
            />
            <dl className="grid gap-x-4 rounded-lg border bg-background/40 px-3 py-1 text-[13px] sm:grid-cols-2">
              {[
                ["Break-even (unidades)", breakEven !== null ? formatInteger(breakEven) : "—"],
                ["Break-even (facturación)", result.breakEvenRevenue !== null ? formatEuro(result.breakEvenRevenue, 0) : "—"],
                [
                  "Recuperación de la inversión",
                  result.paybackMonths !== null
                    ? `${result.paybackMonths.toLocaleString("es-ES", { maximumFractionDigits: 1 })} meses`
                    : "—",
                ],
                ["CAC máximo tolerable", formatEuro(Math.max(0, result.maxCac))],
                ["Precio mínimo viable", Number.isFinite(result.minViablePrice) ? formatEuro(result.minViablePrice) : "—"],
              ].map(([label, value]) => (
                <div key={label} className="flex justify-between gap-3 border-b py-1.5 last:border-b-0">
                  <dt className="text-muted-foreground">{label}</dt>
                  <dd className="font-medium whitespace-nowrap tabular-nums">{value}</dd>
                </div>
              ))}
            </dl>
          </CardContent>
        </Card>

        <Card id="resumen" className="scroll-mt-4">
          <CardHeader>
            <CardTitle>Viabilidad económica</CardTitle>
            <CardDescription>Evaluación final del análisis.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div id="riesgo" className="scroll-mt-4 space-y-2 text-sm">
              <ul className="space-y-2">
                {viability.map((item) => (
                  <li key={item.label} className="flex items-center justify-between gap-2">
                    <span className="text-muted-foreground">{item.label}</span>
                    <span className={cn("font-medium", TONE_TEXT[item.tone])}>{item.value}</span>
                  </li>
                ))}
              </ul>
              <ul className="space-y-2 border-t pt-2">
                <li className="flex items-center justify-between gap-2">
                  <span className="flex items-center gap-1.5 text-muted-foreground">
                    <CircleDollarSign className="size-3.5" /> Capital inicial
                  </span>
                  <span className="font-medium whitespace-nowrap tabular-nums">{formatEuro(inputs.initialInvestment, 0)}</span>
                </li>
                <li className="flex items-center justify-between gap-2">
                  <span className="flex items-center gap-1.5 text-muted-foreground">
                    {result.monthlyProfit > 0 ? <TrendingUp className="size-3.5" /> : <TrendingDown className="size-3.5" />}
                    Beneficio anual
                  </span>
                  <span className="font-medium whitespace-nowrap tabular-nums">{formatEuro(result.monthlyProfit * 12, 0)}</span>
                </li>
                <li className="flex items-center gap-1.5 text-warning">
                  <AlertTriangle className="size-3.5 shrink-0" />
                  {estimatedCount} supuestos requieren validación
                </li>
              </ul>
            </div>
            <div
              className={cn(
                "flex items-start gap-3 rounded-lg border p-3 text-sm",
                decision.tone === "ok" && "border-primary/40 bg-primary/10 text-primary",
                decision.tone === "warn" && "border-warning/40 bg-warning/10 text-warning",
                decision.tone === "bad" && "border-destructive/40 bg-destructive/10 text-destructive",
              )}
            >
              {decision.tone === "bad" ? <AlertTriangle className="size-5 shrink-0" /> : <CircleCheck className="size-5 shrink-0" />}
              <p>
                {decision.title} Requiere validación de los supuestos señalados.
              </p>
            </div>
            <Button className="w-full" onClick={goLegal}>
              Enviar a revisión legal <ArrowRight />
            </Button>
          </CardContent>
        </Card>
      </section>

      <NextStepBar
        steps={[
          { label: "Economía validada", icon: Calculator, state: latestAnalysis || saved ? "done" : "current" },
          { label: "Revisión legal", icon: Scale, state: latestAnalysis || saved ? "current" : "todo" },
          { label: "Plan de lanzamiento", icon: Rocket, state: "todo" },
          { label: "Seguimiento de resultados", icon: Activity, state: "todo" },
        ]}
        action={
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              onClick={saveAnalysis}
              disabled={saving || !quote}
              title={quote ? "Guarda el análisis con este precio y estos costes fijos" : "Hace falta una cotización real de proveedor para guardar"}
            >
              {saving ? <Loader2 className="animate-spin" /> : saved ? <CircleCheck /> : <Save />}
              {saved ? "Análisis guardado" : "Guardar análisis"}
            </Button>
            <Menu.Root>
              <Menu.Trigger render={<Button variant="outline" size="icon" aria-label="Más acciones" />}>
                <Ellipsis />
              </Menu.Trigger>
              <Menu.Portal>
                <Menu.Positioner sideOffset={6} align="end" className="z-50">
                  <Menu.Popup className="min-w-56 rounded-lg border bg-popover p-1 text-sm shadow-lg outline-none">
                    <Menu.Item
                      onClick={validateWithCeo}
                      className="flex cursor-default items-center gap-2 rounded-md px-2.5 py-2 outline-none data-highlighted:bg-panel-hover"
                    >
                      <Brain className="size-4" /> Validar con el Director ejecutivo
                    </Menu.Item>
                    <Menu.Item
                      onClick={() => router.push(`/sourcing?product_id=${product.id}`)}
                      className="flex cursor-default items-center gap-2 rounded-md px-2.5 py-2 outline-none data-highlighted:bg-panel-hover"
                    >
                      <Sparkles className="size-4" /> Buscar más proveedores
                    </Menu.Item>
                  </Menu.Popup>
                </Menu.Positioner>
              </Menu.Portal>
            </Menu.Root>
          </div>
        }
      />
    </div>
  );
}
