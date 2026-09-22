// DATOS DE DEMOSTRACIÓN — pantalla de Tienda y canales de venta.
//
// Valores inventados (con permiso del propietario, 22-09-2026) para que el
// panel se vea como el mockup mientras el backend no los proporciona. Se usan
// solo cuando no hay dato real. Sustituir cuando existan los endpoints
// (docs/design/AMAZONA_estado_paneles_rediseno.md, sección 4).

import { demoRandom } from "./random.ts";

/** Características destacadas de la ficha cuando el borrador no trae viñetas. */
export const DEMO_FEATURES = [
  { icon: "sound", title: "Cancelación de ruido", detail: "activa" },
  { icon: "water", title: "Resistencia al agua", detail: "IPX7" },
  { icon: "battery", title: "Hasta 8 horas", detail: "de batería" },
  { icon: "design", title: "Diseño ergonómico", detail: "y ultraligero" },
] as const;

export const DEMO_REVIEWS = { rating: 4.8, count: 1284 };

/** Precio tachado de referencia (el de antes de la oferta). */
export const DEMO_COMPARE_AT_FACTOR = 1.334;

export const DEMO_TRUST_BADGES = ["Envío gratis en España", "Pago seguro", "Devolución 30 días"];

export const DEMO_CHANNELS = {
  amazon: { status: "Preparación", readiness: 0.62 },
  google: { status: "Elegible", readiness: 0.81 },
  tiktok: { status: "Pendiente análisis", readiness: 0.25 },
};

export const CHECKOUT_MODES = [
  { value: "embedded", label: "Checkout embebido" },
  { value: "hosted", label: "Página externa (Stripe Checkout)" },
  { value: "custom", label: "Checkout personalizado" },
];

export const PAYMENT_METHODS = [
  { key: "card", label: "Tarjeta (Visa, Mastercard)", enabled: true },
  { key: "klarna", label: "Klarna", enabled: false },
  { key: "apple", label: "Apple Pay", enabled: true },
  { key: "bizum", label: "Bizum", enabled: false },
  { key: "google", label: "Google Pay", enabled: true },
  { key: "transfer", label: "Transferencia", enabled: false },
  { key: "paypal", label: "PayPal", enabled: true },
  { key: "other", label: "Otros", enabled: false },
];

/** Proporción de visitas que llega a cada paso del embudo (la compra se ajusta al volumen real). */
export const DEMO_FUNNEL_RATIOS = { product: 0.74, cart: 0.21, checkout: 0.145 };

/** Puntuaciones del escaparate que no se pueden medir todavía (0–100). */
export const DEMO_QUALITY = { content: 96, conversion: 88, seo: 83, trust: 94, mobile: 92, speed: 87 };

export const DEMO_EU_MARKETS = [
  { country: "España", flag: "es", language: "Español", priceDelta: 0, status: "Activo" },
  { country: "Francia", flag: "fr", language: "Français", priceDelta: 1, status: "Preparación" },
  { country: "Alemania", flag: "de", language: "Deutsch", priceDelta: 2, status: "Preparación" },
  { country: "Italia", flag: "it", language: "Italiano", priceDelta: 1, status: "Pendiente" },
] as const;

export const DEMO_PAGES = [
  { name: "Ficha de producto", status: "Publicada" },
  { name: "Carrito", status: "Publicada" },
  { name: "Checkout", status: "Borrador" },
  { name: "Aviso legal", status: "Publicada" },
  { name: "Política de privacidad", status: "Publicada" },
  { name: "Envíos y devoluciones", status: "Borrador" },
];

export const DEMO_AB_TESTS = [
  { name: "Titular: beneficio vs. característica", variantA: "3,1 %", variantB: "3,6 %", status: "En curso" },
  { name: "Botón «Comprar ahora» vs. «Añadir al carrito»", variantA: "2,8 %", variantB: "2,5 %", status: "Finalizado" },
];

export const THEMES = [
  { key: "emerald", label: "Esmeralda", color: "#00d69a" },
  { key: "blue", label: "Azul", color: "#3b82f6" },
  { key: "amber", label: "Ámbar", color: "#f59e0b" },
];

/** Ficha maestra de producto que el backend no guarda (deterministas por producto). */
export function demoMasterData(productId: string) {
  const r = (salt: string) => demoRandom(productId, salt);
  const ean = `84${String(Math.floor(r("ean") * 1e11)).padStart(11, "0")}`;
  return {
    ean,
    weightKg: Math.round((0.1 + r("weight") * 0.6) * 100) / 100,
    dimensions: `${10 + Math.floor(r("dx") * 10)} x ${6 + Math.floor(r("dy") * 6)} x ${3 + Math.floor(r("dz") * 4)} cm`,
  };
}
