"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  AlertTriangle,
  ArrowRight,
  Boxes,
  Brain,
  Calculator,
  Check,
  Loader2,
  PackageSearch,
  Percent,
  Rocket,
  Scale,
  ShieldAlert,
  SlidersHorizontal,
  Target,
  Tag,
  TrendingUp,
  X,
  Zap,
  Landmark,
  Activity,
  type LucideIcon,
} from "lucide-react";
import { ApiError, api, type EconomicAnalysis, type Product, type SupplierQuote } from "@/lib/api";
import {
  RECOMMENDATION_LABEL,
  dedupeQuotesBySupplier,
  scenarioList,
  unitContribution,
  viabilityStatement,
} from "@/lib/economics";
import { formatAmount, formatInteger, formatPercent } from "@/lib/format";
import { regionLabel } from "@/lib/regions";
import { BarChart } from "@/components/bar-chart";
import { DataProvenanceBadge } from "@/components/data-provenance-badge";
import { EmptyState } from "@/components/empty-state";
import { KpiCard } from "@/components/kpi-card";
import { NextStepBar } from "@/components/next-step-bar";
import { PendingFeatures } from "@/components/pending-features";
import { ProductHeader } from "@/components/product-header";
import { RiskList } from "@/components/risk-list";
import { ScenarioCard } from "@/components/scenario-card";
import { SectionNav } from "@/components/section-nav";
import { VerdictBanner } from "@/components/verdict-banner";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

const INPUT_CLASS = "w-full rounded-md border bg-background px-3 py-2 text-sm";

/** Secciones de la spec (§7.4) que el motor económico del backend no calcula:
 * hoy solo produce 3 escenarios con volúmenes distintos y un margen único. */
const PENDING_ANALYSES: { icon: LucideIcon; title: string; description: string }[] = [
  {
    icon: SlidersHorizontal,
    title: "Simulador interactivo",
    description: "Mover precio, coste, CAC, devoluciones y conversión y recalcular ingresos, beneficio y margen.",
  },
  {
    icon: Zap,
    title: "Análisis de sensibilidad",
    description: "Qué variable puede destruir la oportunidad (CAC, coste proveedor, devoluciones, precio…).",
  },
  {
    icon: Target,
    title: "Punto de equilibrio",
    description: "Unidades, facturación, días hasta break-even, CAC máximo tolerable y precio mínimo viable.",
  },
  {
    icon: Landmark,
    title: "Riesgo y capital",
    description: "Capital comprometido, capital sin cobertura y desfase entre cobro y pago.",
  },
];

function quoteName(quote: SupplierQuote): string {
  return quote.data?.name ?? quote.supplier_id;
}

function Field({ label, htmlFor, children }: { label: string; htmlFor: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0 space-y-1.5">
      <label htmlFor={htmlFor} className="text-xs font-medium text-muted-foreground">
        {label}
      </label>
      {children}
    </div>
  );
}

function BreakdownRow({
  label,
  value,
  tone = "default",
  strong = false,
}: {
  label: string;
  value: string;
  tone?: "default" | "cost" | "result";
  strong?: boolean;
}) {
  return (
    <div
      className={cn(
        "flex items-center justify-between gap-3 rounded-md px-3 py-2 text-sm",
        tone === "result" ? "bg-primary/10 text-primary" : "bg-background/50",
        strong && "font-semibold",
      )}
    >
      <span className={tone === "default" || tone === "cost" ? "text-muted-foreground" : undefined}>{label}</span>
      <span className={cn("shrink-0 tabular-nums", tone === "cost" && "text-foreground")}>{value}</span>
    </div>
  );
}

export function EconomicsWorkspace({
  products,
  initialProductId,
  initialQuotes,
  initialQuoteId,
}: {
  products: Product[];
  initialProductId?: string;
  initialQuotes: SupplierQuote[];
  initialQuoteId?: string;
}) {
  const router = useRouter();

  const [productId, setProductId] = useState(initialProductId ?? "");
  const [quotes, setQuotes] = useState(initialQuotes);
  const [quoteId, setQuoteId] = useState(initialQuoteId ?? "");
  const [changingProduct, setChangingProduct] = useState(false);
  const [loadingQuotes, setLoadingQuotes] = useState(false);
  const [salePrice, setSalePrice] = useState("20");
  const [fixedCosts, setFixedCosts] = useState("500");

  const [analysis, setAnalysis] = useState<EconomicAnalysis | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const product = products.find((p) => p.id === productId);
  const quoteOptions = useMemo(() => dedupeQuotesBySupplier(quotes, quoteId || undefined), [quotes, quoteId]);
  const quote = quoteOptions.find((q) => q.id === quoteId) ?? quoteOptions[0];

  async function changeProduct(id: string) {
    setProductId(id);
    setChangingProduct(false);
    setAnalysis(null);
    setError(null);
    setQuoteId("");
    setLoadingQuotes(true);
    try {
      setQuotes(await api.listProductSuppliers(id));
    } catch (err) {
      setQuotes([]);
      setError(err instanceof ApiError ? err.detail : "No se pudieron cargar las cotizaciones del producto.");
    } finally {
      setLoadingQuotes(false);
    }
  }

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (!product || !quote) return;
    setError(null);
    setSubmitting(true);
    try {
      const result = await api.createEconomicAnalysisRun({
        product_id: product.id,
        supplier_quote_id: quote.id,
        sale_price: Number(salePrice),
        monthly_fixed_costs: Number(fixedCosts),
      });
      setAnalysis(result);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "El análisis económico falló.");
    } finally {
      setSubmitting(false);
    }
  }

  if (products.length === 0 || !product) {
    return (
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
    );
  }

  // --- Resultados (todo sale del análisis devuelto por el backend + la cotización real) ---
  const analysisQuote = analysis ? quotes.find((q) => q.id === analysis.supplier_quote_id) : undefined;
  const scenarios = analysis ? scenarioList(analysis) : [];
  const base = scenarios.find((s) => s.key === "base")?.scenario;
  const landed = analysisQuote?.total_landed_cost_per_unit;
  const contribution = analysis && landed !== undefined ? unitContribution(analysis.sale_price, landed) : undefined;
  const risks = analysis?.data?.risks ?? [];
  const viability = analysis ? viabilityStatement(analysis.recommendation) : undefined;

  function goLegal() {
    if (!analysis) return;
    router.push(`/legal?${new URLSearchParams({ product_id: analysis.product_id }).toString()}`);
  }

  function validateWithCeo() {
    if (!analysis || landed === undefined) return;
    const params = new URLSearchParams({
      title: `Validar economía de ${product?.name ?? analysis.product_id}`,
      unit_cost: landed.toFixed(2),
      sale_price: String(analysis.sale_price),
      monthly_fixed_costs: String(analysis.monthly_fixed_costs),
      monthly_unit_sales: String(Math.round(base?.monthly_unit_sales ?? 0)),
    });
    router.push(`/ceo?${params.toString()}`);
  }

  return (
    <div className="space-y-6">
      <form id="economics-form" onSubmit={handleSubmit} className="grid gap-4 xl:grid-cols-12">
        <Card className="xl:col-span-7">
          <CardHeader>
            <CardTitle>Producto y proveedor</CardTitle>
            <CardAction>
              <Button type="button" variant="ghost" size="xs" onClick={() => setChangingProduct((v) => !v)}>
                Cambiar producto
              </Button>
            </CardAction>
          </CardHeader>
          <CardContent className="space-y-4">
            {changingProduct ? (
              <Field label="Producto" htmlFor="economics-product">
                <select
                  id="economics-product"
                  value={productId}
                  onChange={(e) => void changeProduct(e.target.value)}
                  className={INPUT_CLASS}
                >
                  {products.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name} · {p.category}
                    </option>
                  ))}
                </select>
              </Field>
            ) : null}

            <ProductHeader product={product}>
              <span className="flex items-center gap-1 text-xs text-muted-foreground">
                Investigación:
                <DataProvenanceBadge
                  status="pending"
                  tooltip="El backend no expone el score de investigación de un producto."
                />
              </span>
            </ProductHeader>

            {loadingQuotes ? (
              <p className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="size-4 animate-spin" /> Cargando cotizaciones…
              </p>
            ) : quoteOptions.length === 0 ? (
              <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-dashed p-3 text-sm">
                <span className="text-muted-foreground">
                  Este producto aún no tiene cotizaciones de proveedor. El análisis necesita una.
                </span>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  nativeButton={false}
                  render={<Link href={`/sourcing?product_id=${product.id}`} />}
                >
                  Buscar proveedores
                </Button>
              </div>
            ) : (
              <>
                <Field label="Proveedor (cotización)" htmlFor="economics-quote">
                  <select
                    id="economics-quote"
                    value={quote?.id ?? ""}
                    onChange={(e) => {
                      setQuoteId(e.target.value);
                      setAnalysis(null);
                    }}
                    className={INPUT_CLASS}
                  >
                    {quoteOptions.map((q) => (
                      <option key={q.id} value={q.id}>
                        {quoteName(q)} · {regionLabel(q.data?.region)} · entregado {formatAmount(q.total_landed_cost_per_unit)}
                      </option>
                    ))}
                  </select>
                </Field>
                {quote ? (
                  <dl className="grid grid-cols-2 gap-3 rounded-lg border bg-background/50 p-3 text-xs sm:grid-cols-4">
                    <div>
                      <dt className="text-muted-foreground">Precio proveedor</dt>
                      <dd className="mt-0.5 font-medium">{formatAmount(quote.unit_price)}</dd>
                    </div>
                    <div>
                      <dt className="text-muted-foreground">Coste entregado</dt>
                      <dd className="mt-0.5 font-medium text-primary">{formatAmount(quote.total_landed_cost_per_unit)}</dd>
                    </div>
                    <div>
                      <dt className="text-muted-foreground">MOQ</dt>
                      <dd className="mt-0.5 font-medium">{formatInteger(quote.moq)} uds</dd>
                    </div>
                    <div>
                      <dt className="text-muted-foreground">Plazo</dt>
                      <dd className="mt-0.5 font-medium">{quote.lead_time_days} días</dd>
                    </div>
                  </dl>
                ) : null}
              </>
            )}
          </CardContent>
        </Card>

        <Card className="xl:col-span-5">
          <CardHeader>
            <CardTitle>Supuestos del análisis</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-2 gap-3">
              <Field label="Precio de venta" htmlFor="economics-price">
                <input
                  id="economics-price"
                  type="number"
                  step="0.01"
                  min={0}
                  required
                  value={salePrice}
                  onChange={(e) => setSalePrice(e.target.value)}
                  className={INPUT_CLASS}
                />
              </Field>
              <Field label="Costes fijos mensuales" htmlFor="economics-fixed">
                <input
                  id="economics-fixed"
                  type="number"
                  step="0.01"
                  min={0}
                  required
                  value={fixedCosts}
                  onChange={(e) => setFixedCosts(e.target.value)}
                  className={INPUT_CLASS}
                />
              </Field>
            </div>
            <p className="text-xs text-muted-foreground">
              Ambos son supuestos tuyos. El coste de entrega sale de la cotización del proveedor; el volumen de ventas
              lo estima el agente a partir de la demanda de la investigación (simulado).
            </p>
            <Button type="submit" size="lg" className="w-full" disabled={submitting || !quote || loadingQuotes}>
              {submitting ? <Loader2 className="animate-spin" /> : <Calculator />}
              {submitting ? "Analizando…" : "Ejecutar análisis"}
            </Button>
          </CardContent>
        </Card>
      </form>

      {error ? (
        <Alert variant="destructive">
          <AlertTriangle className="size-4" />
          <AlertTitle>No se pudo completar la operación</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}

      {!analysis || !viability ? (
        <Card>
          <CardContent>
            <EmptyState
              icon={Calculator}
              title="Sin análisis económico todavía"
              description="Elige proveedor, fija el precio de venta y los costes fijos, y pulsa «Ejecutar análisis» para ver aquí escenarios, desglose y viabilidad."
            />
          </CardContent>
        </Card>
      ) : (
        <>
          <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6" aria-label="Indicadores del análisis">
            <KpiCard label="Precio de venta" value={formatAmount(analysis.sale_price)} icon={Tag} caption="Supuesto tuyo" />
            <KpiCard
              label="Coste total por unidad"
              value={landed !== undefined ? formatAmount(landed) : "—"}
              icon={Boxes}
              caption="Producto + logística y aduana"
              provenance="estimated"
            />
            <KpiCard
              label="Margen de contribución"
              value={contribution !== undefined ? formatAmount(contribution) : "—"}
              icon={Percent}
              caption={`${formatPercent(analysis.margin_percent)} de margen por unidad`}
              provenance="estimated"
            />
            <KpiCard
              label="Beneficio estimado (mes)"
              value={base ? formatAmount(base.monthly_profit) : "—"}
              icon={TrendingUp}
              caption={base ? `Escenario base · ${formatInteger(base.monthly_unit_sales)} uds/mes` : "Sin escenario base"}
              provenance="estimated"
            />
            <KpiCard
              label="Punto de equilibrio"
              value="—"
              icon={Target}
              caption="El motor económico aún no lo calcula"
              provenance="pending"
              provenanceTooltip="El backend no calcula el punto de equilibrio; el cliente no duplica la lógica económica."
            />
            <KpiCard
              label="Riesgo económico"
              value={RECOMMENDATION_LABEL[analysis.recommendation]}
              icon={ShieldAlert}
              caption={`Recomendación del agente · confianza ${formatPercent(analysis.confidence, 0)} · ${risks.length} riesgo${risks.length === 1 ? "" : "s"}`}
              provenance="estimated"
            />
          </section>

          <SectionNav
            label="Secciones del análisis"
            items={[
              { label: "Escenarios", href: "#escenarios" },
              { label: "Desglose de costes", href: "#desglose" },
              { label: "Resumen y decisión", href: "#viabilidad" },
              ...PENDING_ANALYSES.map((item) => ({
                label: item.title,
                icon: item.icon,
                pendingReason: "Pendiente: el backend aún no lo calcula",
              })),
            ]}
          />

          <section className="grid gap-4 xl:grid-cols-12">
            <Card id="escenarios" className="scroll-mt-4 xl:col-span-7">
              <CardHeader>
                <CardTitle>Comparativa de escenarios</CardTitle>
                <CardAction>
                  <DataProvenanceBadge
                    status="estimated"
                    tooltip="Los escenarios varían solo el volumen de ventas, que el agente estima con factores de simulación fijos. El precio es el mismo en los tres."
                  />
                </CardAction>
              </CardHeader>
              <CardContent className="space-y-5">
                <p className="text-xs text-muted-foreground">
                  Mismo precio y coste en los tres escenarios; cambia el volumen mensual de ventas.
                </p>
                <div className="grid gap-3 sm:grid-cols-3">
                  {scenarios.map(({ key, label, scenario }) => (
                    <ScenarioCard
                      key={key}
                      title={label}
                      badge={key === "base" ? "Referencia" : undefined}
                      highlighted={key === "base"}
                      headline={{
                        label: "Beneficio / mes",
                        value: formatAmount(scenario.monthly_profit),
                        negative: scenario.monthly_profit < 0,
                      }}
                      metrics={[
                        { label: "Unidades / mes", value: formatInteger(scenario.monthly_unit_sales) },
                        { label: "Ingresos / mes", value: formatAmount(scenario.monthly_revenue) },
                        { label: "Margen", value: formatPercent(scenario.margin_percent) },
                      ]}
                    />
                  ))}
                </div>
                <div>
                  <p className="mb-1 text-xs font-medium text-muted-foreground">Beneficio mensual por escenario</p>
                  <BarChart
                    ariaLabel="Beneficio mensual estimado por escenario"
                    valueHeader="Beneficio / mes"
                    formatValue={formatAmount}
                    data={scenarios.map(({ key, label, scenario }) => ({
                      key,
                      label,
                      value: scenario.monthly_profit,
                      highlight: key === "base",
                    }))}
                  />
                </div>
              </CardContent>
            </Card>

            <Card id="desglose" className="scroll-mt-4 xl:col-span-5">
              <CardHeader>
                <CardTitle>Desglose económico por unidad</CardTitle>
                <CardAction>
                  <DataProvenanceBadge
                    status="estimated"
                    tooltip="Precio y logística del directorio de proveedores simulado; la logística y la aduana son estimaciones, no tarifas reales."
                  />
                </CardAction>
              </CardHeader>
              <CardContent className="space-y-2">
                <BreakdownRow label="Precio de venta (supuesto)" value={formatAmount(analysis.sale_price)} strong />
                {analysisQuote ? (
                  <>
                    <BreakdownRow
                      label={`Producto (${quoteName(analysisQuote)})`}
                      value={`−${formatAmount(analysisQuote.unit_price)}`}
                      tone="cost"
                    />
                    <BreakdownRow
                      label="Logística y aduana (simulada)"
                      value={`−${formatAmount(analysisQuote.logistics_cost_per_unit)}`}
                      tone="cost"
                    />
                    <BreakdownRow
                      label="Coste total de entrega"
                      value={`−${formatAmount(analysisQuote.total_landed_cost_per_unit)}`}
                      tone="cost"
                      strong
                    />
                  </>
                ) : (
                  <p className="rounded-md bg-background/50 px-3 py-2 text-xs text-muted-foreground">
                    No se encontró la cotización de este análisis; no se puede desglosar el coste.
                  </p>
                )}
                {contribution !== undefined ? (
                  <BreakdownRow
                    label={`Margen de contribución · ${formatPercent(analysis.margin_percent)}`}
                    value={formatAmount(contribution)}
                    tone="result"
                    strong
                  />
                ) : null}
                <BreakdownRow
                  label="Costes fijos mensuales (no por unidad)"
                  value={formatAmount(analysis.monthly_fixed_costs)}
                  tone="cost"
                />
                <div className="flex items-start gap-1.5 pt-1 text-[11px] text-muted-foreground">
                  <DataProvenanceBadge
                    status="pending"
                    tooltip="Pasarela de pago, devoluciones, publicidad/CAC, fulfillment y otros costes (spec §7) no forman parte del motor económico actual."
                  />
                  <span>Pasarela de pago, devoluciones, CAC y fulfillment: pendientes. Importes sin divisa.</span>
                </div>
              </CardContent>
            </Card>
          </section>

          <section className="grid gap-4 xl:grid-cols-12">
            <Card id="viabilidad" className="scroll-mt-4 xl:col-span-5">
              <CardHeader>
                <CardTitle>Viabilidad económica</CardTitle>
                <CardAction>
                  <DataProvenanceBadge
                    status="estimated"
                    tooltip="Recomendación del agente de análisis económico sobre supuestos simulados."
                  />
                </CardAction>
              </CardHeader>
              <CardContent className="space-y-4">
                <VerdictBanner tone={viability.tone} title={viability.title} detail={viability.detail} />

                <div>
                  <p className="mb-2 text-xs font-medium text-muted-foreground">Beneficio mensual por escenario</p>
                  <ul className="space-y-1.5">
                    {scenarios.map(({ key, label, scenario }) => (
                      <li key={key} className="flex items-center gap-2 text-xs">
                        {scenario.monthly_profit > 0 ? (
                          <Check className="size-4 shrink-0 text-emerald-500" />
                        ) : (
                          <X className="size-4 shrink-0 text-red-500" />
                        )}
                        <span className="flex-1">{label}</span>
                        <span className="font-medium tabular-nums">{formatAmount(scenario.monthly_profit)}</span>
                      </li>
                    ))}
                  </ul>
                </div>

                <RiskList risks={risks} />

                <div className="flex flex-wrap gap-2 border-t pt-3">
                  <Button type="button" onClick={goLegal}>
                    Enviar a revisión legal
                    <ArrowRight />
                  </Button>
                  <Button type="button" variant="outline" onClick={validateWithCeo} disabled={landed === undefined}>
                    <Brain />
                    Validar con el Director ejecutivo
                  </Button>
                </div>
              </CardContent>
            </Card>

            <PendingFeatures
              className="xl:col-span-7"
              title="Análisis avanzado"
              tooltip="Requieren exponer el cálculo desde el motor económico del backend; el cliente no duplica esa lógica."
              items={PENDING_ANALYSES}
              note="El motor económico hoy solo modela coste de entrega + costes fijos mensuales y tres volúmenes de venta. Estas secciones necesitan que el backend exponga ese cálculo (p. ej. una simulación sin estado) para no duplicar la lógica económica en la interfaz."
            />
          </section>
        </>
      )}

      <NextStepBar
        steps={[
          { label: "Economía validada", icon: Calculator, state: analysis ? "done" : "current" },
          { label: "Revisión legal", icon: Scale, state: analysis ? "current" : "todo" },
          { label: "Plan de lanzamiento", icon: Rocket, state: "todo" },
          { label: "Seguimiento de resultados", icon: Activity, state: "todo" },
        ]}
        action={
          <Button type="button" disabled={!analysis} onClick={goLegal}>
            Enviar a revisión legal
            <ArrowRight />
          </Button>
        }
      />
    </div>
  );
}
