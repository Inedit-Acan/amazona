// DATOS DE DEMOSTRACIÓN — pantalla de Marketing y adquisición.
//
// Valores inventados (con permiso del propietario, 22-09-2026) para que el
// panel se vea como el mockup mientras el backend no los proporciona: no hay
// integración con Meta / Google / TikTok Ads, así que no existen gasto,
// conversiones, funnel ni atribución reales. Se usan solo cuando no hay dato
// real. Sustituir cuando existan los endpoints
// (docs/design/AMAZONA_estado_paneles_rediseno.md, sección 5).

import { demoRandom } from "./random.ts";

export type ChannelKey = "meta" | "google" | "tiktok" | "creators" | "other";
/** Grupos del gráfico de rendimiento y de la atribución (creators va con «otros»). */
export type BucketKey = "meta" | "google" | "tiktok" | "other";

export interface DemoChannel {
  key: ChannelKey;
  label: string;
  bucket: BucketKey;
  /** Parte del presupuesto recomendado (suman 1). */
  share: number;
  focus: string;
  /** CAC del canal relativo al CAC objetivo de Economía. */
  cacFactor: number;
  /** Clics / impresiones. */
  ctr: number;
  /** Compras / clics. */
  conversionRate: number;
}

export const DEMO_CHANNELS: DemoChannel[] = [
  { key: "meta", label: "Meta Ads", bucket: "meta", share: 0.35, focus: "Prospección + retargeting", cacFactor: 0.92, ctr: 0.033, conversionRate: 0.045 },
  { key: "google", label: "Google Ads", bucket: "google", share: 0.3, focus: "Search + Shopping", cacFactor: 0.86, ctr: 0.041, conversionRate: 0.052 },
  { key: "tiktok", label: "TikTok Ads", bucket: "tiktok", share: 0.2, focus: "Vídeo / UGC", cacFactor: 1.12, ctr: 0.021, conversionRate: 0.03 },
  { key: "creators", label: "Creators / Influencers", bucket: "other", share: 0.1, focus: "Colaboraciones", cacFactor: 1.25, ctr: 0.018, conversionRate: 0.034 },
  { key: "other", label: "Otros", bucket: "other", share: 0.05, focus: "YouTube, Display, etc.", cacFactor: 1.35, ctr: 0.012, conversionRate: 0.028 },
];

export const BUCKETS: { key: BucketKey; label: string; color: string }[] = [
  { key: "meta", label: "Meta", color: "#4f8df7" },
  { key: "google", label: "Google", color: "#f2c94c" },
  { key: "tiktok", label: "TikTok", color: "#e056c8" },
  { key: "other", label: "Otros", color: "#a8a4f0" },
];

/** Periodo de la demostración (un mes cerrado de campaña). */
export const DEMO_PERIOD = { label: "Septiembre 2026", month: "sep", days: 30 };

/** Proporción de clics que llega a cada paso del funnel. */
export const DEMO_FUNNEL_RATIOS = { landing: 0.86, cart: 0.148, checkout: 0.553 };

/** Reparto relativo de cada modelo de atribución respecto al último clic. */
export const ATTRIBUTION_MODELS = [
  { key: "last_click", label: "Último clic", tilt: { meta: 1, google: 1, tiktok: 1, other: 1 } },
  { key: "first_click", label: "Primer clic", tilt: { meta: 0.95, google: 0.7, tiktok: 1.6, other: 1.2 } },
  { key: "linear", label: "Lineal", tilt: { meta: 0.97, google: 0.9, tiktok: 1.2, other: 1.15 } },
  { key: "data_driven", label: "Data driven", tilt: { meta: 1.02, google: 0.97, tiktok: 1.08, other: 0.9 } },
] as const;

export type AttributionModel = (typeof ATTRIBUTION_MODELS)[number]["key"];

export const CAMPAIGN_OBJECTIVES = ["Ventas", "Tráfico", "Clientes potenciales", "Reconocimiento"];
export const CONVERSION_EVENTS = ["Compra", "Añadir al carrito", "Iniciar checkout", "Registro"];
export const DEMO_DURATION_DAYS = 14;

export type AudienceIntent = "Alta intención" | "Media" | "Datos propios" | "Plataforma";

export interface DemoAudience {
  name: string;
  detail: string;
  score: number;
  intent: AudienceIntent;
  icon: "people" | "tech" | "activity" | "retarget" | "lookalike";
}

const CATEGORY_AUDIENCES: Record<string, DemoAudience[]> = {
  electronics: [
    { name: "Deportistas urbanos", detail: "18–35 · running / gym", score: 89, intent: "Alta intención", icon: "people" },
    { name: "Usuarios de tecnología", detail: "Tecnología + deporte", score: 86, intent: "Alta intención", icon: "tech" },
    { name: "Running frecuente", detail: "Deporte y vida saludable", score: 81, intent: "Media", icon: "activity" },
  ],
  home: [
    { name: "Hogar y decoración", detail: "25–45 · decoración / DIY", score: 88, intent: "Alta intención", icon: "people" },
    { name: "Recién mudados", detail: "25–39 · primera vivienda", score: 84, intent: "Alta intención", icon: "tech" },
    { name: "Organización y limpieza", detail: "30–55 · hogar práctico", score: 79, intent: "Media", icon: "activity" },
  ],
  accessories: [
    { name: "Viajeros frecuentes", detail: "25–45 · viajes / escapadas", score: 87, intent: "Alta intención", icon: "people" },
    { name: "Compradores de regalo", detail: "Regalos + estilo de vida", score: 83, intent: "Alta intención", icon: "tech" },
    { name: "Estilo de vida activo", detail: "Deporte y bienestar", score: 78, intent: "Media", icon: "activity" },
  ],
};

/** Audiencias que no dependen de la categoría: se alimentan de datos propios o de la plataforma. */
export const DEMO_OWNED_AUDIENCES: DemoAudience[] = [
  { name: "Remarketing", detail: "Visitantes / carrito / checkout", score: 76, intent: "Datos propios", icon: "retarget" },
  { name: "Lookalike (compradores)", detail: "Basado en clientes actuales", score: 72, intent: "Plataforma", icon: "lookalike" },
];

export function demoAudiences(category: string): DemoAudience[] {
  return CATEGORY_AUDIENCES[category] ?? CATEGORY_AUDIENCES.electronics;
}

const CATEGORY_HEADLINES: Record<string, string[]> = {
  electronics: ["Libertad para moverte", "Sonido que te impulsa", "Sin límites", "Resistencia en cada paso"],
  home: ["Tu casa, a otro nivel", "Orden sin esfuerzo", "Luz que transforma", "Hecho para el día a día"],
  accessories: ["Llévalo contigo", "Diseño que acompaña", "Listo para todo", "Detalles que marcan"],
};

export interface DemoCreative {
  name: string;
  headline: string;
  seconds: number;
  score: number;
  /** CTR relativo al de la mejor creatividad (1 = el mejor). */
  ctrIndex: number;
  hue: number;
}

/** Cuatro vídeos de ejemplo por producto (deterministas). */
export function demoCreatives(productId: string, category: string): DemoCreative[] {
  const headlines = CATEGORY_HEADLINES[category] ?? CATEGORY_HEADLINES.electronics;
  const base = [92, 87, 84, 79];
  const seconds = [28, 20, 15, 22];
  const ctr = [0.79, 1, 0.74, 0.66];
  return headlines.map((headline, k) => ({
    name: `Video ${String(k + 1).padStart(2, "0")}`,
    headline,
    seconds: seconds[k],
    score: Math.min(98, base[k] + Math.round(demoRandom(productId, `creative-${k}`) * 3)),
    ctrIndex: ctr[k],
    hue: [160, 200, 28, 250][k],
  }));
}

/** Interacciones de la vista previa del anuncio. */
export function demoSocial(productId: string) {
  return {
    likes: 300 + Math.round(demoRandom(productId, "likes") * 300),
    comments: 8 + Math.round(demoRandom(productId, "comments") * 20),
    shares: 2 + Math.round(demoRandom(productId, "shares") * 6),
  };
}

/** Factor del CAC real frente al objetivo (0,8–1,1): el rendimiento de la demo por producto. */
export function demoCacFactor(productId: string): number {
  return 0.8 + demoRandom(productId, "cac") * 0.3;
}

/** Variación diaria (0–1) del gasto y del CAC de un grupo de canales. */
export function demoDaily(productId: string, bucket: BucketKey, day: number): { spend: number; cac: number } {
  return { spend: demoRandom(productId, `${bucket}-spend-${day}`), cac: demoRandom(productId, `${bucket}-cac-${day}`) };
}

/** Recomendaciones fijas de la demo (las demás se calculan con los datos del panel). */
export const DEMO_RECOMMENDATIONS = {
  shopping: { title: "Activar Google Shopping", roasUplift: 1.2 },
  tiktok: { title: "Revisar segmentación TikTok", detail: "Competencia creciente en tu nicho." },
};

/** Texto del anuncio cuando el agente aún no ha generado creatividad. */
export function demoAdText(productName: string): string {
  return `${productName}: calidad verificada, envío rápido y devolución gratuita en 30 días.`;
}
