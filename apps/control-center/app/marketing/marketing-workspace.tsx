"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  Activity,
  AlertTriangle,
  ArrowDown,
  ArrowRight,
  ArrowUp,
  Fingerprint,
  Loader2,
  MoreHorizontal,
  MousePointerClick,
  Package,
  PackageSearch,
  Receipt,
  Repeat,
  Sparkles,
  Target,
  TrendingUp,
  Users,
  Wallet,
  type LucideIcon,
} from "lucide-react";
import { ApiError, api, type Product } from "@/lib/api";
import {
  CAMPAIGN_OBJECTIVES,
  CONVERSION_EVENTS,
  DEMO_DURATION_DAYS,
  DEMO_PERIOD,
  demoAdText,
  demoSocial,
  type ChannelKey,
} from "@/lib/demo/marketing";
import { DEMO_SUBCATEGORY } from "@/lib/demo/research";
import { buildBaseline } from "@/lib/economics-baseline";
import { dedupeQuotesBySupplier } from "@/lib/economics";
import { evaluate } from "@/lib/economics-model";
import { formatEuro, formatInteger, formatPercent } from "@/lib/format";
import { campaignPlan, latestCampaign, PLATFORM_LABELS } from "@/lib/marketing";
import {
  acquisitionPlan,
  audienceRows,
  channelPerformance,
  creativeRows,
  marketingSummary,
  optimizePlan,
  planTotal,
  profitabilityGuard,
  recommendations,
  type PlanRow,
} from "@/lib/marketing-view";
import type { ProductMarketingData } from "@/lib/product-channels";
import { categoryLabel } from "@/lib/research-view";
import { DataProvenanceBadge } from "@/components/data-provenance-badge";
import { EmptyState } from "@/components/empty-state";
import { KpiCard } from "@/components/kpi-card";
import { LevelChip, type LevelTone } from "@/components/level-chip";
import { PageHeader } from "@/components/page-header";
import { RingGauge } from "@/components/ring-gauge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { MARKETING_DESCRIPTION, MARKETING_TITLE } from "./copy";
import { AttributionCard, CreativesCard, FunnelCard, PerformanceCard, PreviewCard, RecommendationsCard } from "./marketing-panels";

const MARKETS = [
  { value: "eu", label: "España + UE" },
  { value: "us", label: "Estados Unidos" },
  { value: "mx", label: "México" },
];

const DEMO_TOOLTIP =
  "Incluye datos de demostración: no hay integración con Meta / Google / TikTok Ads, así que la inversión, las conversiones, los ingresos atribuidos, el funnel, el rendimiento diario y la atribución son simulados, igual que las creatividades, las audiencias sin propuesta del agente y los canales sin integración. Real: las propuestas de campaña del agente (canal, presupuesto diario, audiencias, creatividad, CTR y conversión estimados) y los supuestos de Economía (precio, margen, CAC objetivo y CAC máximo).";

const CHANNEL_MARK: Record<ChannelKey, { color: string; letter?: string; icon?: LucideIcon }> = {
  meta: { color: "#4f8df7", letter: "M" },
  google: { color: "#f2c94c", letter: "G" },
  tiktok: { color: "#e056c8", letter: "T" },
  creators: { color: "#a8a4f0", icon: Users },
  other: { color: "#7a8b99", icon: MoreHorizontal },
};

const AUDIENCE_ICON: Record<string, LucideIcon> = {
  people: Users,
  tech: Sparkles,
  activity: Activity,
  retarget: Repeat,
  lookalike: Fingerprint,
};

const INTENT_TONE: Record<string, LevelTone> = {
  "Alta intención": "ok",
  Media: "warn",
  "Datos propios": "neutral",
  Plataforma: "neutral",
};

const INPUT_CLASS = "w-full min-w-0 rounded-md border bg-background px-2.5 py-1.5 text-sm";

function Field({ label, htmlFor, children }: { label: string; htmlFor: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0 space-y-1">
      <label htmlFor={htmlFor} className="text-xs text-muted-foreground">
        {label}
      </label>
      {children}
    </div>
  );
}

/** Variación frente a lo previsto bajo el valor de un KPI. */
function Delta({ value, text, good }: { value: number; text: string; good: boolean }) {
  const Icon = value >= 0 ? ArrowUp : ArrowDown;
  return (
    <p className={cn("flex items-center gap-1 text-xs", good ? "text-primary" : "text-warning")}>
      <Icon className="size-3 shrink-0" />
      {text}
    </p>
  );
}

function signedPercent(fraction: number, digits = 0): string {
  return `${fraction >= 0 ? "+" : "−"}${formatPercent(Math.abs(fraction), digits)}`;
}

function roasText(value: number): string {
  return `${value.toLocaleString("es-ES", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} x`;
}

function ChannelMark({ channel }: { channel: ChannelKey }) {
  const mark = CHANNEL_MARK[channel];
  return (
    <span
      className="flex size-6 shrink-0 items-center justify-center rounded-md text-[11px] font-bold text-background"
      style={{ background: mark.color }}
      aria-hidden
    >
      {mark.icon ? <mark.icon className="size-3.5" /> : mark.letter}
    </span>
  );
}

export function MarketingWorkspace({
  products,
  productId,
  data,
  initialMarket,
}: {
  products: Product[];
  productId?: string;
  data: ProductMarketingData;
  initialMarket: string;
}) {
  const router = useRouter();
  const product = products.find((p) => p.id === productId);

  const [market, setMarket] = useState(MARKETS.some((m) => m.value === initialMarket) ? initialMarket : "eu");
  const [platform, setPlatform] = useState("meta");
  const [objective, setObjective] = useState(CAMPAIGN_OBJECTIVES[0]);
  const [event, setEvent] = useState(CONVERSION_EVENTS[0]);
  const [dailyBudget, setDailyBudget] = useState("20");
  const [duration, setDuration] = useState(String(DEMO_DURATION_DAYS));
  const [optimized, setOptimized] = useState(false);
  const [creativeIndex, setCreativeIndex] = useState(0);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (products.length === 0 || !product) {
    return (
      <div>
        <PageHeader title={MARKETING_TITLE} description={MARKETING_DESCRIPTION} />
        <Card>
          <CardContent>
            <EmptyState
              icon={PackageSearch}
              title="Aún no hay productos que promocionar"
              description="La campaña parte de un producto investigado, con sus análisis económico y legal."
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

  // Los mismos supuestos que Economía: precio, margen de contribución, CAC objetivo y CAC máximo.
  const economic = data.economics[0];
  const quoteOptions = dedupeQuotesBySupplier(data.quotes, economic?.supplier_quote_id);
  const quote = quoteOptions.find((q) => q.id === economic?.supplier_quote_id) ?? quoteOptions[0];
  const baseline = buildBaseline(quote, economic);
  const economics = evaluate(baseline.inputs);
  const price = baseline.inputs.salePrice;
  const cacObjective = baseline.inputs.cac;
  const maxCac = economics.maxCac;

  // Propuestas reales del agente: la última de cada plataforma en este mercado.
  const marketCampaigns = campaignPlan(data.campaigns, market);
  const campaign = latestCampaign(data.campaigns, market, platform) ?? marketCampaigns[0];
  const estimates = Object.fromEntries(
    marketCampaigns.flatMap((c) => {
      const estimate = c.data?.performance_estimate;
      return estimate ? [[c.platform, { avg_ctr: estimate.avg_ctr, conversion_rate: estimate.conversion_rate }] as const] : [];
    }),
  );

  const basePlan = acquisitionPlan(marketCampaigns, Math.round(baseline.inputs.monthlyOrders * cacObjective));
  const plan = optimized ? optimizePlan(basePlan) : basePlan;
  const budget = planTotal(basePlan);
  const performance = channelPerformance({ productId: product.id, plan: basePlan, cacObjective, price, estimates });
  const summary = marketingSummary(performance, { budget, cacObjective, maxCac, price });
  const audiences = audienceRows(campaign?.data?.audience_segments, product.category);
  const creatives = creativeRows(product.id, product.category, campaign?.data?.ad_creative);
  const creative = creatives[Math.min(creativeIndex, creatives.length - 1)];
  const advice = recommendations({
    performance,
    cacObjective,
    creatives,
    agentAdvice: campaign?.data?.budget_recommendation,
  });

  const channelBucket = performance.find((b) => b.key === platform) ?? performance[0];
  const channelCac = channelBucket.conversions > 0 ? channelBucket.spend / channelBucket.conversions : 0;
  const guard = profitabilityGuard(channelCac, maxCac);
  const totalSpendPlanned = Number(dailyBudget || 0) * Number(duration || 0);
  const spentRatio = budget > 0 ? Math.min(1, summary.spend / budget) : 0;
  const subcategory = DEMO_SUBCATEGORY[product.category]?.[0];

  function changeProduct(id: string) {
    router.push(`/marketing?${new URLSearchParams({ product_id: id, market }).toString()}`);
  }

  /** Rellena el formulario con el canal más barato del plan y su presupuesto diario. */
  function suggestWithAI() {
    const best = [...performance].sort((a, b) => {
      const cacOf = (x: typeof a) => (x.conversions > 0 ? x.spend / x.conversions : Infinity);
      return cacOf(a) - cacOf(b);
    })[0];
    const channel = (best.key === "other" ? "meta" : best.key) as ChannelKey;
    const row = basePlan.find((r) => r.key === channel);
    if (PLATFORM_LABELS[channel]) setPlatform(channel);
    setObjective(CAMPAIGN_OBJECTIVES[0]);
    setEvent(CONVERSION_EVENTS[0]);
    setDuration(String(DEMO_DURATION_DAYS));
    if (row) setDailyBudget(String(Math.max(1, Math.round(row.amount / DEMO_PERIOD.days))));
  }

  async function createCampaign(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await api.createMarketingCampaignRun({
        product_id: product!.id,
        market,
        platform,
        daily_budget: Number(dailyBudget),
      });
      router.refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "La generación de la campaña falló.");
    } finally {
      setSubmitting(false);
    }
  }

  function requestInvestmentApproval() {
    const params = new URLSearchParams({
      title: `Aprobar inversión de marketing de ${product!.name} en ${MARKETS.find((m) => m.value === market)!.label}`,
      spend_amount: String(budget),
    });
    router.push(`/ceo?${params.toString()}`);
  }

  return (
    <div className="space-y-5">
      <PageHeader
        title={MARKETING_TITLE}
        description={MARKETING_DESCRIPTION}
        actions={
          <>
            <DataProvenanceBadge status="demo" tooltip={DEMO_TOOLTIP} />
            <div className="flex min-w-0 max-w-full gap-3 rounded-xl border bg-card p-3">
              <span className="flex size-14 shrink-0 items-center justify-center rounded-lg border bg-background/60 text-primary">
                <Package className="size-7" />
              </span>
              <div className="min-w-0 space-y-1">
                <select
                  value={product.id}
                  onChange={(e) => changeProduct(e.target.value)}
                  aria-label="Producto activo"
                  className="w-52 max-w-full min-w-0 truncate bg-transparent text-sm font-semibold outline-none"
                >
                  {products.map((p) => (
                    <option key={p.id} value={p.id} className="bg-popover font-normal">
                      {p.name}
                    </option>
                  ))}
                </select>
                <p className="flex flex-wrap gap-1">
                  <Badge variant="outline" className="border-primary/40 text-primary">
                    {categoryLabel(product.category)}
                  </Badge>
                  {subcategory ? <Badge variant="outline">{subcategory}</Badge> : null}
                </p>
                <Button size="xs" variant="outline" nativeButton={false} render={<Link href="/research" />}>
                  Ver ficha del producto <ArrowRight />
                </Button>
              </div>
            </div>
            <dl className="grid w-72 max-w-full grid-cols-[auto_minmax(0,1fr)] items-center gap-x-3 gap-y-1 rounded-xl border bg-card p-3 text-xs">
              <dt className="text-muted-foreground">Mercado:</dt>
              <dd>
                <select
                  value={market}
                  onChange={(e) => setMarket(e.target.value)}
                  aria-label="Mercado de la campaña"
                  className="w-full min-w-0 truncate bg-transparent text-sm font-medium outline-none"
                >
                  {MARKETS.map((m) => (
                    <option key={m.value} value={m.value} className="bg-popover">
                      {m.label}
                    </option>
                  ))}
                </select>
              </dd>
              <dt className="text-muted-foreground">Precio:</dt>
              <dd className="font-medium">{formatEuro(price)}</dd>
              <dt className="text-muted-foreground">Margen contribución:</dt>
              <dd className="font-medium text-primary">{formatEuro(economics.contribution)}</dd>
              <dt className="text-muted-foreground">CAC máximo:</dt>
              <dd className="font-medium">{formatEuro(maxCac)}</dd>
            </dl>
          </>
        }
      />

      {error ? (
        <Alert variant="destructive">
          <AlertTriangle className="size-4" />
          <AlertTitle>No se pudo completar la operación</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}

      {/* KPIs del periodo */}
      <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-[repeat(5,minmax(0,1fr))_minmax(0,1.4fr)]" aria-label="Indicadores de marketing">
        <KpiCard
          label="Inversión"
          leading={<Receipt className="size-9 shrink-0 text-primary" />}
          value={formatEuro(summary.spend, 0)}
          footer={<Delta value={summary.spendVsPlan} text={`${signedPercent(summary.spendVsPlan)} vs. previsto`} good={Math.abs(summary.spendVsPlan) <= 0.15} />}
        />
        <KpiCard
          label="Ingresos atribuidos"
          leading={<Wallet className="size-9 shrink-0 text-primary" />}
          value={formatEuro(summary.revenue, 0)}
          accent
          footer={<Delta value={summary.revenueVsPlan} text={`${signedPercent(summary.revenueVsPlan)} vs. objetivo`} good={summary.revenueVsPlan >= 0} />}
        />
        <KpiCard
          label="CAC / CPA"
          leading={<MousePointerClick className="size-9 shrink-0 text-primary" />}
          value={formatEuro(summary.cac)}
          footer={<Delta value={summary.cacVsMax} text={`${signedPercent(summary.cacVsMax)} vs. máximo`} good={summary.cacVsMax < 0} />}
        />
        <KpiCard
          label="ROAS"
          leading={<TrendingUp className="size-9 shrink-0 text-primary" />}
          value={roasText(summary.roas)}
          footer={
            <Delta
              value={summary.roasVsTarget}
              text={`${summary.roasVsTarget >= 0 ? "+" : "−"}${roasText(Math.abs(summary.roasVsTarget))} vs. objetivo`}
              good={summary.roasVsTarget >= 0}
            />
          }
        />
        <KpiCard
          label="Conversiones"
          leading={<Target className="size-9 shrink-0 text-primary" />}
          value={formatInteger(summary.conversions)}
          footer={<Delta value={summary.conversionsVsPlan} text={`${signedPercent(summary.conversionsVsPlan)} vs. previsto`} good={summary.conversionsVsPlan >= 0} />}
        />
        <KpiCard
          label="Estado general"
          leading={<RingGauge value={summary.health / 100} size={64} centerLabel={`${summary.health}/100`} />}
          value={summary.healthLabel}
          tone={summary.health >= 80 && summary.cac <= maxCac ? "success" : summary.cac > maxCac ? "danger" : "warning"}
          caption={`${DEMO_PERIOD.label} · CAC, ROAS y ritmo de gasto`}
        />
      </section>

      {/* Plan · Nueva campaña · Audiencias */}
      <section className="grid gap-4 md:grid-cols-2 2xl:grid-cols-[minmax(0,1fr)_minmax(0,0.95fr)_minmax(0,1.05fr)]">
        <Card className="min-w-0">
          <CardHeader>
            <CardTitle>Plan de adquisición por canal</CardTitle>
            <CardDescription>Distribución recomendada del presupuesto basada en datos de mercado y objetivos.</CardDescription>
            <CardAction>
              <Button size="xs" variant="outline" className="text-primary" onClick={() => setOptimized((v) => !v)}>
                <Sparkles /> {optimized ? "Ver plan base" : "Optimizar con IA"}
              </Button>
            </CardAction>
          </CardHeader>
          <CardContent className="space-y-3">
            <ul className="space-y-3">
              {plan.map((row: PlanRow) => (
                <li key={row.key} className="grid grid-cols-[minmax(0,1.6fr)_minmax(2rem,1fr)_2.4rem_3.4rem] items-center gap-x-2 gap-y-0.5 text-xs">
                  <span className="flex min-w-0 items-center gap-2">
                    <ChannelMark channel={row.key} />
                    <span className="text-[13px] leading-tight font-medium">{row.label}</span>
                  </span>
                  <span className="h-2 rounded-full bg-muted">
                    <span className="block h-full rounded-full bg-primary" style={{ width: `${Math.round(row.share * 100)}%` }} />
                  </span>
                  <span className="text-right tabular-nums">{formatPercent(row.share, 0)}</span>
                  <span className="text-right font-medium tabular-nums">{formatEuro(row.amount, 0)}</span>
                  <span className="col-span-4 pl-8 text-[11px] leading-tight text-muted-foreground">{row.focus}</span>
                </li>
              ))}
            </ul>
            <p className="text-[11px] text-muted-foreground">
              Total {formatEuro(budget, 0)} al mes (los pedidos de Economía al CAC objetivo de {formatEuro(cacObjective)}).
              {basePlan.some((r) => r.isReal) ? " Los canales con propuesta del agente usan su presupuesto diario real." : ""}
            </p>
          </CardContent>
        </Card>

        <Card className="min-w-0">
          <CardHeader>
            <CardTitle>Nueva campaña</CardTitle>
            <CardAction>
              <Button size="xs" variant="outline" className="text-primary" onClick={suggestWithAI}>
                <Sparkles /> Rellenar con IA
              </Button>
            </CardAction>
          </CardHeader>
          <CardContent>
            <form onSubmit={createCampaign} className="space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <Field label="Objetivo" htmlFor="marketing-objective">
                  <select id="marketing-objective" value={objective} onChange={(e) => setObjective(e.target.value)} className={INPUT_CLASS}>
                    {CAMPAIGN_OBJECTIVES.map((o) => (
                      <option key={o} value={o}>
                        {o}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label="Canal" htmlFor="marketing-platform">
                  <select id="marketing-platform" value={platform} onChange={(e) => setPlatform(e.target.value)} className={INPUT_CLASS}>
                    {Object.entries(PLATFORM_LABELS).map(([value, label]) => (
                      <option key={value} value={value}>
                        {label}
                      </option>
                    ))}
                    <option value="tiktok" disabled>
                      TikTok Ads (sin integración)
                    </option>
                  </select>
                </Field>
                <Field label="Mercado" htmlFor="marketing-market">
                  <select id="marketing-market" value={market} onChange={(e) => setMarket(e.target.value)} className={INPUT_CLASS}>
                    {MARKETS.map((m) => (
                      <option key={m.value} value={m.value}>
                        {m.label}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label="Evento de conversión" htmlFor="marketing-event">
                  <select id="marketing-event" value={event} onChange={(e) => setEvent(e.target.value)} className={INPUT_CLASS}>
                    {CONVERSION_EVENTS.map((c) => (
                      <option key={c} value={c}>
                        {c}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label="Presupuesto diario" htmlFor="marketing-budget">
                  <input
                    id="marketing-budget"
                    type="number"
                    step="1"
                    min={1}
                    required
                    value={dailyBudget}
                    onChange={(e) => setDailyBudget(e.target.value)}
                    className={INPUT_CLASS}
                  />
                </Field>
                <Field label="Duración (días)" htmlFor="marketing-duration">
                  <input
                    id="marketing-duration"
                    type="number"
                    step="1"
                    min={1}
                    value={duration}
                    onChange={(e) => setDuration(e.target.value)}
                    className={INPUT_CLASS}
                  />
                </Field>
              </div>
              <dl className="grid grid-cols-2 gap-3 rounded-lg border bg-background/40 p-2.5 text-xs">
                <div>
                  <dt className="text-muted-foreground">CAC objetivo (Economía)</dt>
                  <dd className="mt-0.5 text-sm font-semibold">{formatEuro(cacObjective)}</dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">Inversión total prevista</dt>
                  <dd className="mt-0.5 text-sm font-semibold">{formatEuro(totalSpendPlanned, 0)}</dd>
                </div>
              </dl>
              <div className={cn("flex items-start gap-2 rounded-lg border p-2.5 text-xs", guard.ok ? "border-primary/40 bg-primary/5" : "border-warning/40 bg-warning/5")}>
                <span className={cn("mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full", guard.ok ? "bg-primary/20 text-primary" : "bg-warning/20 text-warning")}>
                  {guard.ok ? <Target className="size-3" /> : <AlertTriangle className="size-3" />}
                </span>
                <span className="min-w-0">
                  <span className={cn("block font-medium", guard.ok ? "text-primary" : "text-warning")}>
                    {guard.ok ? "Rentabilidad protegida" : "Revisa la rentabilidad"}
                  </span>
                  <span className="block text-muted-foreground">
                    {guard.detail} CAC previsto del canal {formatEuro(channelCac)}, máximo {formatEuro(maxCac)}.
                  </span>
                </span>
              </div>
              <Button type="submit" className="w-full" disabled={submitting}>
                {submitting ? <Loader2 className="animate-spin" /> : <Sparkles />}
                {submitting ? "Generando…" : "Crear campaña"}
              </Button>
              <p className="text-[11px] text-muted-foreground">
                El agente de marketing solo recibe producto, mercado, canal y presupuesto diario: objetivo, evento y duración
                todavía no se envían.
              </p>
            </form>
          </CardContent>
        </Card>

        <Card className="min-w-0">
          <CardHeader>
            <CardTitle>Audiencias propuestas</CardTitle>
            <CardDescription>Generadas a partir de investigación de mercado y datos de las plataformas.</CardDescription>
          </CardHeader>
          <CardContent>
            <ul className="space-y-3">
              {audiences.map((audience) => {
                const Icon = AUDIENCE_ICON[audience.icon];
                return (
                  <li key={audience.name} className="grid grid-cols-[auto_minmax(0,1fr)_2.8rem_auto] items-center gap-2 sm:grid-cols-[auto_minmax(0,1fr)_minmax(2rem,0.42fr)_2.8rem_auto]">
                    <span className="flex size-8 shrink-0 items-center justify-center rounded-lg border border-primary/30 bg-primary/10 text-primary">
                      <Icon className="size-4" />
                    </span>
                    <span className="min-w-0">
                      <span className="block text-[13px] leading-tight font-medium">{audience.name}</span>
                      <span className="block text-[11px] leading-tight break-words text-muted-foreground">{audience.detail}</span>
                    </span>
                    <span className="hidden h-2 rounded-full bg-muted sm:block">
                      <span className="block h-full rounded-full bg-primary" style={{ width: `${audience.score}%` }} />
                    </span>
                    <span className="text-right text-xs tabular-nums">{audience.score}/100</span>
                    <LevelChip tone={INTENT_TONE[audience.intent] ?? "neutral"}>{audience.intent}</LevelChip>
                  </li>
                );
              })}
            </ul>
          </CardContent>
        </Card>
      </section>

      {/* Creatividades · Vista previa · Funnel */}
      <section className="grid gap-4 md:grid-cols-2 2xl:grid-cols-[minmax(0,1.45fr)_minmax(0,0.8fr)_minmax(0,1.15fr)]">
        <CreativesCard creatives={creatives} selected={creativeIndex} onSelect={setCreativeIndex} />
        <PreviewCard
          creative={creative}
          productName={product.name}
          text={creative.primaryText ?? demoAdText(product.name)}
          social={demoSocial(product.id)}
        />
        <FunnelCard performance={performance} />
      </section>

      {/* Rendimiento · Atribución · Recomendaciones · Presupuesto */}
      <section className="grid gap-4 md:grid-cols-2 2xl:grid-cols-[minmax(0,1.35fr)_minmax(0,1.1fr)_minmax(0,1fr)_minmax(0,1fr)]">
        <PerformanceCard performance={performance} />
        <AttributionCard performance={performance} total={summary.revenue} />
        <RecommendationsCard items={advice} />

        <Card className="min-w-0">
          <CardHeader>
            <CardTitle>Presupuesto y control</CardTitle>
            <CardAction>
              <Button size="xs" variant="outline" className="text-primary" nativeButton={false} render={<Link href={`/economics?product_id=${product.id}`} />}>
                Ver detalles <ArrowRight />
              </Button>
            </CardAction>
          </CardHeader>
          <CardContent className="space-y-3">
            <dl className="grid grid-cols-3 gap-2 text-xs">
              <div>
                <dt className="text-muted-foreground">Asignado</dt>
                <dd className="mt-0.5 text-sm font-semibold">{formatEuro(budget, 0)}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Gastado</dt>
                <dd className="mt-0.5 text-sm font-semibold">{formatEuro(summary.spend, 0)}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Restante</dt>
                <dd className="mt-0.5 text-sm font-semibold">{formatEuro(Math.max(0, budget - summary.spend), 0)}</dd>
              </div>
            </dl>
            <div className="flex items-center gap-2">
              <span className="h-2 flex-1 rounded-full bg-muted">
                <span className="block h-full rounded-full bg-primary" style={{ width: `${Math.round(spentRatio * 100)}%` }} />
              </span>
              <span className="text-xs font-medium tabular-nums">{formatPercent(spentRatio)}</span>
            </div>
            <dl className="grid grid-cols-3 gap-2 border-t pt-3 text-xs">
              <div>
                <dt className="text-muted-foreground">CAC actual</dt>
                <dd className="mt-0.5 text-sm font-semibold">{formatEuro(summary.cac)}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">CAC objetivo</dt>
                <dd className="mt-0.5 text-sm font-semibold text-primary">{formatEuro(cacObjective)}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">CAC máximo</dt>
                <dd className="mt-0.5 text-sm font-semibold">{formatEuro(maxCac)}</dd>
              </div>
            </dl>
            <LevelChip tone={summary.cac <= maxCac ? "ok" : "bad"}>
              {summary.cac <= maxCac ? "Dentro del rango" : "Fuera del rango"}
            </LevelChip>
            <Button className="w-full" onClick={requestInvestmentApproval}>
              Solicitar aprobación de inversión <ArrowRight />
            </Button>
          </CardContent>
        </Card>
      </section>
    </div>
  );
}
