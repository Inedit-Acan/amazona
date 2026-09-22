import type { MarketplaceListing, Storefront } from "./api.ts";
import {
  DEMO_CHANNELS,
  DEMO_EU_MARKETS,
  DEMO_FUNNEL_RATIOS,
  DEMO_QUALITY,
} from "./demo/storefront.ts";
import type { ReadinessItem } from "./ecommerce.ts";

// Vista de la pantalla de Tienda y canales (mockup docs/design/tienda y canales
// de venta.png). Real: borradores de tienda y listados de Amazon, su estado,
// el copy generado, el plan de pasarela y el catálogo. Demo
// (lib/demo/storefront.ts): canales sin integración, embudo, calidad no medible,
// mercados europeos y ficha maestra.

export type ChannelTone = "ok" | "warn" | "bad" | "neutral";

export interface ChannelCardView {
  key: "store" | "amazon" | "google" | "tiktok";
  name: string;
  status: string;
  tone: ChannelTone;
  /** 0–1. */
  readiness: number;
  isDemo: boolean;
}

const LAUNCH_STATUS: Record<Storefront["launch_status"], { label: string; tone: ChannelTone; readiness: number }> = {
  READY: { label: "Activo", tone: "ok", readiness: 1 },
  NEEDS_REVIEW: { label: "Preparación", tone: "warn", readiness: 0.62 },
  BLOCKED: { label: "Bloqueado", tone: "bad", readiness: 0.25 },
};

/** Proporción del checklist de lanzamiento ya cumplida (lo que no existe cuenta como pendiente). */
export function readinessRatio(items: ReadinessItem[]): number {
  return items.length ? items.filter((i) => i.state === "done").length / items.length : 0;
}

export function channelCards(input: {
  storefront?: Pick<Storefront, "launch_status">;
  listing?: Pick<MarketplaceListing, "listing_status">;
  storeReadiness: number;
}): ChannelCardView[] {
  const { storefront, listing, storeReadiness } = input;
  const store = storefront ? LAUNCH_STATUS[storefront.launch_status] : undefined;
  const amazon = listing ? LAUNCH_STATUS[listing.listing_status] : undefined;
  return [
    {
      key: "store",
      name: "Tienda propia",
      status: store ? store.label : "Sin generar",
      tone: store ? store.tone : "neutral",
      readiness: storeReadiness,
      isDemo: false,
    },
    {
      key: "amazon",
      name: "Amazon",
      status: amazon ? amazon.label : DEMO_CHANNELS.amazon.status,
      tone: amazon ? amazon.tone : "warn",
      readiness: amazon ? amazon.readiness : DEMO_CHANNELS.amazon.readiness,
      isDemo: !amazon,
    },
    { key: "google", name: "Google Shopping", status: DEMO_CHANNELS.google.status, tone: "neutral", readiness: DEMO_CHANNELS.google.readiness, isDemo: true },
    { key: "tiktok", name: "TikTok Shop", status: DEMO_CHANNELS.tiktok.status, tone: "bad", readiness: DEMO_CHANNELS.tiktok.readiness, isDemo: true },
  ];
}

export interface FunnelStep {
  label: string;
  value: number;
}

/** Embudo mensual: las compras son los pedidos del escenario base y las visitas salen
 * de la conversión estimada (mismos supuestos que Economía). */
export function purchaseFunnel(monthlyOrders: number, conversionPct: number): { steps: FunnelStep[]; conversion: number } {
  const visits = conversionPct > 0 ? Math.round(monthlyOrders / (conversionPct / 100)) : 0;
  const steps = [
    { label: "Visitas", value: visits },
    { label: "Producto", value: Math.round(visits * DEMO_FUNNEL_RATIOS.product) },
    { label: "Añadir carrito", value: Math.round(visits * DEMO_FUNNEL_RATIOS.cart) },
    { label: "Checkout", value: Math.round(visits * DEMO_FUNNEL_RATIOS.checkout) },
    { label: "Compra", value: Math.round(monthlyOrders) },
  ];
  return { steps, conversion: visits > 0 ? monthlyOrders / visits : 0 };
}

export interface QualityAxis {
  label: string;
  /** 0–100. */
  value: number;
}

/** Calidad del escaparate: contenido e información legal salen de datos del panel;
 * el resto es de demostración hasta que haya analítica. */
export function storeQuality(contentRatio: number, legalRatio: number): { score: number; label: string; axes: QualityAxis[] } {
  const axes: QualityAxis[] = [
    { label: "Contenido", value: Math.round(contentRatio * 100) },
    { label: "Conversión", value: DEMO_QUALITY.conversion },
    { label: "SEO", value: DEMO_QUALITY.seo },
    { label: "Confianza", value: DEMO_QUALITY.trust },
    { label: "Información legal", value: Math.round(legalRatio * 100) },
    { label: "Mobile", value: DEMO_QUALITY.mobile },
    { label: "Velocidad estimada", value: DEMO_QUALITY.speed },
  ];
  const score = Math.round(axes.reduce((s, a) => s + a.value, 0) / axes.length);
  const label = score >= 85 ? "Excelente" : score >= 70 ? "Buena" : score >= 50 ? "Mejorable" : "Insuficiente";
  return { score, label, axes };
}

export interface MarketConfigRow {
  key: string;
  country: string;
  flag?: string;
  price: number | null;
  language: string;
  status: string;
  tone: ChannelTone;
}

const STATUS_TONE: Record<string, ChannelTone> = { Activo: "ok", Preparación: "warn", Pendiente: "bad", Bloqueado: "bad" };

/** Mercados de venta: los países de la UE (demo, con el precio aprobado como base y
 * el estado real de la tienda de la UE en España) y los borradores reales de otros mercados. */
export function marketConfig(
  approvedPrice: number,
  storefronts: Pick<Storefront, "market" | "launch_status" | "data">[],
): MarketConfigRow[] {
  const latest = new Map<string, Pick<Storefront, "market" | "launch_status" | "data">>();
  for (const s of storefronts) if (!latest.has(s.market)) latest.set(s.market, s);
  const eu = latest.get("eu");
  const rows: MarketConfigRow[] = DEMO_EU_MARKETS.map((m) => {
    const status = m.country === "España" && eu ? LAUNCH_STATUS[eu.launch_status].label : m.status;
    return {
      key: m.country,
      country: m.country,
      flag: m.flag,
      price: Math.round((approvedPrice + m.priceDelta) * 100) / 100,
      language: m.language,
      status,
      tone: STATUS_TONE[status] ?? "neutral",
    };
  });
  const extra: Record<string, { country: string; flag?: string; language: string }> = {
    us: { country: "Estados Unidos", language: "English" },
    mx: { country: "México", flag: "mx", language: "Español" },
  };
  for (const [market, info] of Object.entries(extra)) {
    const s = latest.get(market);
    if (!s) continue;
    const status = LAUNCH_STATUS[s.launch_status].label;
    rows.push({ key: market, ...info, price: s.data?.catalog_entry?.price ?? null, status, tone: STATUS_TONE[status] ?? "neutral" });
  }
  return rows;
}
