import type { AdCreative, AudienceSegment, MarketingCampaign } from "./api.ts";
import {
  ATTRIBUTION_MODELS,
  BUCKETS,
  DEMO_CHANNELS,
  DEMO_FUNNEL_RATIOS,
  DEMO_OWNED_AUDIENCES,
  DEMO_PERIOD,
  DEMO_RECOMMENDATIONS,
  demoAudiences,
  demoCacFactor,
  demoCreatives,
  demoDaily,
  type AttributionModel,
  type BucketKey,
  type ChannelKey,
  type DemoAudience,
} from "./demo/marketing.ts";

// Vista de la pantalla de Marketing y adquisición (mockup docs/design/
// marketing.png). Real: las propuestas del agente de marketing (presupuesto
// diario por plataforma, audiencias, creatividad, CTR y conversión estimados,
// recomendación y riesgos) y los supuestos de Economía (precio, CAC objetivo y
// CAC máximo). Demo (lib/demo/marketing.ts): todo lo que requiere gasto real en
// plataformas publicitarias — inversión, conversiones, funnel, rendimiento
// diario y atribución —, más audiencias, creatividades y canales sin propuesta.

const round2 = (value: number) => Math.round(value * 100) / 100;

export interface PlanRow {
  key: ChannelKey;
  label: string;
  bucket: BucketKey;
  focus: string;
  /** Presupuesto del periodo (mes). */
  amount: number;
  /** Parte del total (0–1). */
  share: number;
  cacFactor: number;
  /** El importe sale de una propuesta real del agente (presupuesto diario × días). */
  isReal: boolean;
}

/** Plan por canal: los canales con propuesta real del agente en el mercado usan su
 * presupuesto diario; el resto, el reparto de demostración de `baseBudget` (el
 * presupuesto que Economía supone: pedidos mensuales × CAC objetivo). */
export function acquisitionPlan(
  campaigns: Pick<MarketingCampaign, "platform" | "daily_budget">[],
  baseBudget: number,
): PlanRow[] {
  const rows = DEMO_CHANNELS.map((c) => {
    const real = campaigns.find((campaign) => campaign.platform === c.key);
    return {
      key: c.key,
      label: c.label,
      bucket: c.bucket,
      focus: c.focus,
      amount: real ? round2(real.daily_budget * DEMO_PERIOD.days) : round2(baseBudget * c.share),
      share: 0,
      cacFactor: c.cacFactor,
      isReal: Boolean(real),
    };
  });
  return withShares(rows);
}

function withShares(rows: PlanRow[]): PlanRow[] {
  const total = rows.reduce((sum, r) => sum + r.amount, 0);
  return rows.map((r) => ({ ...r, share: total > 0 ? r.amount / total : 0 }));
}

/** «Optimizar con IA»: el mismo total repartido en proporción a presupuesto ÷ CAC
 * relativo, es decir, más peso a los canales que captan más barato. */
export function optimizePlan(rows: PlanRow[]): PlanRow[] {
  const total = rows.reduce((sum, r) => sum + r.amount, 0);
  const weights = rows.map((r) => r.amount / (r.cacFactor * r.cacFactor));
  const weightSum = weights.reduce((sum, w) => sum + w, 0) || 1;
  return withShares(rows.map((r, k) => ({ ...r, amount: round2((total * weights[k]) / weightSum), isReal: false })));
}

export function planTotal(rows: PlanRow[]): number {
  return round2(rows.reduce((sum, r) => sum + r.amount, 0));
}

// --- Rendimiento ---------------------------------------------------------------

export interface DayPoint {
  day: number;
  spend: number;
  conversions: number;
  revenue: number;
}

export interface BucketPerformance {
  key: BucketKey;
  label: string;
  color: string;
  days: DayPoint[];
  spend: number;
  conversions: number;
  revenue: number;
  /** Clics / impresiones y compras / clics (reales si hay propuesta del agente). */
  ctr: number;
  conversionRate: number;
}

type PerformanceEstimates = Partial<Record<string, { avg_ctr: number; conversion_rate: number }>>;

/** Serie diaria del periodo por grupo de canales: gasto ≈ presupuesto diario del
 * plan con variación, conversiones = gasto ÷ CAC (el CAC objetivo de Economía por el
 * factor del canal y del producto) e ingresos = conversiones × precio. */
export function channelPerformance(input: {
  productId: string;
  plan: PlanRow[];
  cacObjective: number;
  price: number;
  estimates?: PerformanceEstimates;
}): BucketPerformance[] {
  const { productId, plan, cacObjective, price, estimates = {} } = input;
  const productFactor = demoCacFactor(productId);
  return BUCKETS.map((bucket) => {
    const rows = plan.filter((r) => r.bucket === bucket.key);
    const amount = rows.reduce((sum, r) => sum + r.amount, 0);
    const weight = (pick: (c: (typeof DEMO_CHANNELS)[number]) => number) => {
      const channels = DEMO_CHANNELS.filter((c) => c.bucket === bucket.key);
      const total = rows.reduce((sum, r) => sum + r.amount, 0);
      if (total <= 0) return pick(channels[0]);
      return rows.reduce((sum, r) => sum + pick(channels.find((c) => c.key === r.key)!) * r.amount, 0) / total;
    };
    const cac = cacObjective * productFactor * weight((c) => c.cacFactor);
    const dailyBase = amount / DEMO_PERIOD.days;
    const days: DayPoint[] = [];
    for (let day = 1; day <= DEMO_PERIOD.days; day++) {
      const noise = demoDaily(productId, bucket.key, day);
      const spend = round2(dailyBase * (0.8 + 0.3 * noise.spend));
      const dayCac = cac * (0.85 + 0.3 * noise.cac);
      const conversions = dayCac > 0 ? spend / dayCac : 0;
      days.push({ day, spend, conversions, revenue: conversions * price });
    }
    const estimate = estimates[bucket.key];
    return {
      key: bucket.key,
      label: bucket.label,
      color: bucket.color,
      days,
      spend: round2(days.reduce((sum, d) => sum + d.spend, 0)),
      conversions: days.reduce((sum, d) => sum + d.conversions, 0),
      revenue: days.reduce((sum, d) => sum + d.revenue, 0),
      ctr: estimate?.avg_ctr ?? weight((c) => c.ctr),
      conversionRate: estimate?.conversion_rate ?? weight((c) => c.conversionRate),
    };
  });
}

export type SeriesMetric = "spend" | "revenue" | "roas" | "cac";

/** Valor diario de una métrica para el gráfico de rendimiento por canal. */
export function metricSeries(bucket: BucketPerformance, metric: SeriesMetric): { x: number; y: number }[] {
  return bucket.days.map((d) => {
    const y =
      metric === "spend"
        ? d.spend
        : metric === "revenue"
          ? d.revenue
          : metric === "roas"
            ? d.spend > 0 ? d.revenue / d.spend : 0
            : d.conversions > 0 ? d.spend / d.conversions : 0;
    return { x: d.day, y: round2(y) };
  });
}

export interface MarketingSummary {
  spend: number;
  revenue: number;
  conversions: number;
  cac: number;
  roas: number;
  /** Deltas frente a lo previsto (fracciones) y frente al ROAS objetivo (en «x»). */
  spendVsPlan: number;
  revenueVsPlan: number;
  cacVsMax: number;
  roasVsTarget: number;
  conversionsVsPlan: number;
  targetRoas: number;
  /** 0–100. */
  health: number;
  healthLabel: string;
}

/** KPIs del periodo. Lo previsto: el presupuesto del plan gastado entero al CAC objetivo. */
export function marketingSummary(
  performance: BucketPerformance[],
  input: { budget: number; cacObjective: number; maxCac: number; price: number },
): MarketingSummary {
  const { budget, cacObjective, maxCac, price } = input;
  const spend = round2(performance.reduce((sum, b) => sum + b.spend, 0));
  const conversions = Math.round(performance.reduce((sum, b) => sum + b.conversions, 0));
  const revenue = round2(conversions * price);
  const cac = conversions > 0 ? round2(spend / conversions) : 0;
  const roas = spend > 0 ? revenue / spend : 0;
  const plannedConversions = cacObjective > 0 ? budget / cacObjective : 0;
  const targetRoas = cacObjective > 0 ? price / cacObjective : 0;
  const clamp01 = (v: number) => Math.max(0, Math.min(1, v));
  const cacScore = maxCac > 0 ? clamp01((maxCac - cac) / maxCac / 0.6) : 0;
  const roasScore = targetRoas > 0 ? clamp01(roas / targetRoas) : 0;
  const pacingScore = budget > 0 ? clamp01(1 - Math.abs(spend / budget - 1)) : 0;
  const health = Math.round(((cacScore + roasScore + pacingScore) / 3) * 100);
  return {
    spend,
    revenue,
    conversions,
    cac,
    roas,
    spendVsPlan: budget > 0 ? spend / budget - 1 : 0,
    revenueVsPlan: plannedConversions > 0 ? revenue / (plannedConversions * price) - 1 : 0,
    cacVsMax: maxCac > 0 ? cac / maxCac - 1 : 0,
    roasVsTarget: roas - targetRoas,
    conversionsVsPlan: plannedConversions > 0 ? conversions / plannedConversions - 1 : 0,
    targetRoas,
    health,
    healthLabel:
      cac > maxCac ? "CAC por encima del máximo" : health >= 80 ? "En buen rendimiento" : health >= 60 ? "Rendimiento aceptable" : "Requiere atención",
  };
}

// --- Funnel y atribución ---------------------------------------------------------

export interface FunnelStep {
  label: string;
  value: number;
  /** Paso anterior → este (null en el primero); en clics es el CTR. */
  rate: number | null;
}

/** Funnel del periodo reconstruido hacia atrás desde las compras con el CTR y la
 * conversión (clic → compra) del canal. Nunca crece de un paso al siguiente. */
export function conversionFunnel(purchases: number, ctr: number, conversionRate: number): FunnelStep[] {
  const clicks = conversionRate > 0 ? Math.round(purchases / conversionRate) : 0;
  const impressions = ctr > 0 ? Math.round(clicks / ctr) : 0;
  const landing = Math.round(clicks * DEMO_FUNNEL_RATIOS.landing);
  const checkout = Math.max(purchases, Math.round(landing * DEMO_FUNNEL_RATIOS.cart * DEMO_FUNNEL_RATIOS.checkout));
  const cart = Math.max(checkout, Math.round(landing * DEMO_FUNNEL_RATIOS.cart));
  const values: [string, number][] = [
    ["Impresiones", impressions],
    ["Clics", clicks],
    ["Landing", Math.max(landing, cart)],
    ["Añadir carrito", cart],
    ["Checkout", checkout],
    ["Compras", purchases],
  ];
  return values.map(([label, value], k) => ({
    label,
    value,
    rate: k === 0 ? null : values[k - 1][1] > 0 ? value / values[k - 1][1] : 0,
  }));
}

/** Funnel de un grupo de canales o del total (CTR y conversión ponderados por clics). */
export function funnelFor(performance: BucketPerformance[], bucket: BucketKey | "all"): FunnelStep[] {
  const selected = bucket === "all" ? performance : performance.filter((b) => b.key === bucket);
  const purchases = Math.round(selected.reduce((sum, b) => sum + b.conversions, 0));
  const clicks = selected.reduce((sum, b) => sum + (b.conversionRate > 0 ? b.conversions / b.conversionRate : 0), 0);
  const impressions = selected.reduce((sum, b) => sum + (b.conversionRate > 0 && b.ctr > 0 ? b.conversions / b.conversionRate / b.ctr : 0), 0);
  return conversionFunnel(purchases, impressions > 0 ? clicks / impressions : 0, clicks > 0 ? purchases / clicks : 0);
}

export interface AttributionSlice {
  key: BucketKey | "direct";
  label: string;
  color: string;
  share: number;
  revenue: number;
}

/** Ingresos atribuidos por canal según el modelo. El último clic reparte según las
 * conversiones de cada canal; los demás modelos inclinan ese reparto. */
export function attribution(performance: BucketPerformance[], model: AttributionModel, total: number): AttributionSlice[] {
  const tilt = ATTRIBUTION_MODELS.find((m) => m.key === model)!.tilt;
  const weights = performance.map((b) => b.revenue * tilt[b.key]);
  const sum = weights.reduce((acc, w) => acc + w, 0) || 1;
  return performance.map((b, k) => ({
    key: b.key,
    label: b.key === "other" ? "Directo / Otros" : b.label,
    color: b.color,
    share: weights[k] / sum,
    revenue: round2((total * weights[k]) / sum),
  }));
}

// --- Audiencias, creatividades y recomendaciones -----------------------------------

export interface AudienceRow extends DemoAudience {
  isDemo: boolean;
}

/** Audiencias: los segmentos reales del agente (score según su alcance relativo) y,
 * detrás, las de demostración hasta completar cinco, con remarketing y lookalike al final. */
export function audienceRows(segments: AudienceSegment[] | undefined, category: string): AudienceRow[] {
  const list = segments ?? [];
  const max = Math.max(0, ...list.map((s) => s.estimated_reach));
  const icons: DemoAudience["icon"][] = ["people", "tech", "activity"];
  const real: AudienceRow[] = list.slice(0, 3).map((s, k) => {
    const score = Math.round(70 + 20 * (max > 0 ? s.estimated_reach / max : 0));
    return {
      name: s.name,
      detail: [s.age_range, s.interests.slice(0, 2).join(" / ")].filter(Boolean).join(" · "),
      score,
      intent: score >= 85 ? "Alta intención" : "Media",
      icon: icons[k],
      isDemo: false,
    };
  });
  const demo = demoAudiences(category)
    .slice(real.length)
    .map((a) => ({ ...a, isDemo: true }));
  return [...real, ...demo, ...DEMO_OWNED_AUDIENCES.map((a) => ({ ...a, isDemo: true }))];
}

export type CreativeStatus = "Aprobado" | "En revisión" | "Ajustar";

export interface CreativeRow {
  name: string;
  headline: string;
  seconds: number;
  score: number;
  status: CreativeStatus;
  ctrIndex: number;
  hue: number;
  /** Texto y llamada a la acción de la propuesta real (solo el primer vídeo). */
  primaryText: string | null;
  cta: string;
}

export function creativeStatus(score: number): CreativeStatus {
  return score >= 85 ? "Aprobado" : score >= 80 ? "En revisión" : "Ajustar";
}

/** Cuatro creatividades: la primera lleva el titular y el texto reales si el agente los generó. */
export function creativeRows(productId: string, category: string, creative: AdCreative | undefined): CreativeRow[] {
  return demoCreatives(productId, category).map((c, k) => ({
    ...c,
    headline: k === 0 && creative?.headline ? creative.headline : c.headline,
    status: creativeStatus(c.score),
    primaryText: k === 0 && creative ? creative.primary_text : null,
    cta: k === 0 && creative?.cta ? creative.cta : "Comprar ahora",
  }));
}

export interface Recommendation {
  kind: "scale" | "reduce" | "abtest" | "shopping" | "segment" | "agent";
  title: string;
  detail: string;
}

/** Recomendaciones: la del agente (si hay propuesta real) y las derivadas del rendimiento. */
export function recommendations(input: {
  performance: BucketPerformance[];
  cacObjective: number;
  creatives: CreativeRow[];
  agentAdvice?: string | null;
}): Recommendation[] {
  const { performance, cacObjective, creatives, agentAdvice } = input;
  const list: Recommendation[] = [];
  if (agentAdvice) list.push({ kind: "agent", title: "Recomendación del agente", detail: agentAdvice });

  const paid = performance.filter((b) => b.key !== "other" && b.conversions > 0);
  const cacOf = (b: BucketPerformance) => b.spend / b.conversions;
  const best = [...paid].sort((a, b) => cacOf(a) - cacOf(b))[0];
  if (best && cacObjective > 0) {
    const gap = 1 - cacOf(best) / cacObjective;
    list.push(
      gap >= 0
        ? { kind: "scale", title: `Escala inversión en ${best.label}`, detail: `El CAC está un ${Math.round(gap * 100)} % por debajo del objetivo.` }
        : { kind: "reduce", title: `Contén la inversión en ${best.label}`, detail: `Incluso el mejor canal supera el CAC objetivo en un ${Math.round(-gap * 100)} %.` },
    );
  }

  const byCtr = [...creatives].sort((a, b) => b.ctrIndex - a.ctrIndex);
  if (byCtr.length >= 2) {
    const uplift = Math.round((byCtr[0].ctrIndex / byCtr[1].ctrIndex - 1) * 100);
    list.push({ kind: "abtest", title: "A/B test de creatividades", detail: `El ${byCtr[0].name} muestra un ${uplift} % más de CTR.` });
  }

  const google = performance.find((b) => b.key === "google");
  if (google && google.spend > 0) {
    const roas = (google.revenue / google.spend) * DEMO_RECOMMENDATIONS.shopping.roasUplift;
    list.push({
      kind: "shopping",
      title: DEMO_RECOMMENDATIONS.shopping.title,
      detail: `Potencial de ROAS estimado: ${roas.toLocaleString("es-ES", { maximumFractionDigits: 1 })}x.`,
    });
  }
  list.push({ kind: "segment", ...DEMO_RECOMMENDATIONS.tiktok });
  return list;
}

/** «Rentabilidad protegida»: el CAC previsto del canal elegido no supera el CAC máximo de Economía. */
export function profitabilityGuard(channelCac: number, maxCac: number): { ok: boolean; detail: string } {
  return channelCac <= maxCac
    ? { ok: true, detail: "La configuración respeta los límites económicos." }
    : { ok: false, detail: "El CAC previsto del canal supera el CAC máximo de Economía." };
}
