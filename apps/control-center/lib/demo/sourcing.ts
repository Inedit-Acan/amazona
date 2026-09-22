// DATOS DE DEMOSTRACIÓN — pantalla de Proveedores y abastecimiento.
//
// Valores inventados (con permiso del propietario, 22-09-2026) para que el
// panel se vea como el mockup mientras el backend no los proporciona.
// Deterministas por proveedor. Sustituir cuando existan los endpoints
// (docs/design/AMAZONA_estado_paneles_rediseno.md, sección 1).

import type { SupplierQuote } from "../api.ts";
import { demoRandom } from "./random.ts";

/** Cotizaciones de ejemplo cuando el producto no tiene ninguna real. */
export function demoQuotes(productId: string): SupplierQuote[] {
  const rows: [string, string, string, number, number, number, number, number][] = [
    // id, nombre, región, precio, logística, MOQ, plazo (días), fiabilidad
    ["demo-shenzhen-audiotech", "Shenzhen AudioTech Co.", "china", 8.4, 2.46, 1, 9, 0.93],
    ["demo-soundpro-europe", "SoundPro Europe", "eu", 11.2, 0.95, 1, 4, 0.9],
    ["demo-global-electronics", "Global Electronics Ltd.", "vietnam", 7.6, 2.8, 50, 18, 0.84],
    ["demo-iberia-gadgets", "Iberia Gadgets S.L.", "eu", 13.1, 0.6, 5, 3, 0.86],
    ["demo-techsource-hk", "TechSource HK", "china", 8.9, 2.55, 10, 12, 0.8],
  ];
  return rows.map(([id, name, region, unit, logistics, moq, lead, reliability]) => ({
    id,
    product_id: productId,
    supplier_id: id,
    unit_price: unit,
    moq,
    lead_time_days: lead,
    verified: reliability >= 0.85,
    reliability_score: reliability,
    logistics_cost_per_unit: logistics,
    total_landed_cost_per_unit: Math.round((unit + logistics) * 100) / 100,
    data: { name, region },
  }));
}

/** País y ciudad de ejemplo por proveedor de demostración (el backend solo da la región). */
const DEMO_LOCATION: Record<string, { country: string; flag: "cn" | "eu" | "vn" | "mx" | "es" | "pl" | "hk"; city: string }> = {
  "demo-shenzhen-audiotech": { country: "China", flag: "cn", city: "Shenzhen" },
  "demo-soundpro-europe": { country: "Polonia", flag: "pl", city: "Varsovia" },
  "demo-global-electronics": { country: "Vietnam", flag: "vn", city: "Hanói" },
  "demo-iberia-gadgets": { country: "España", flag: "es", city: "Valencia" },
  "demo-techsource-hk": { country: "Hong Kong", flag: "hk", city: "Hong Kong" },
};

const REGION_LOCATION: Record<string, { country: string; flag: "cn" | "eu" | "vn" | "mx"; cities: string[] }> = {
  china: { country: "China", flag: "cn", cities: ["Shenzhen", "Cantón", "Ningbo"] },
  vietnam: { country: "Vietnam", flag: "vn", cities: ["Hanói", "Ho Chi Minh"] },
  mexico: { country: "México", flag: "mx", cities: ["Monterrey", "Guadalajara"] },
  eu: { country: "Unión Europea", flag: "eu", cities: ["Varsovia", "Róterdam", "Valencia"] },
};

export const COMPATIBILITY_CRITERIA = [
  "Dropshipping / envío directo",
  "MOQ bajo (≤ 10)",
  "Packaging neutro",
  "Tracking automático",
  "Stock sincronizable (API/CSV)",
  "Dirección de devoluciones UE",
  "SLA contractual",
  "Pago después de venta",
] as const;

export interface DemoSupplierProfile {
  country: string;
  flag: "cn" | "eu" | "vn" | "mx" | "es" | "pl" | "hk";
  city: string;
  certifications: string[];
  certificationPending: boolean;
  directShipping: boolean;
  /** Días de entrega al destino (mín, máx). */
  delivery: [number, number];
  transport: string;
  /** 0–1. */
  quality: number;
  compliance: number;
  scalability: number;
  /** Criterios de compatibilidad que el proveedor no cumple (o no ha confirmado). */
  compatibilityGaps: string[];
}

/** Perfil de demostración de un proveedor (real o demo): lo que el backend no guarda. */
export function demoSupplierProfile(quote: SupplierQuote): DemoSupplierProfile {
  const seed = quote.supplier_id;
  const region = quote.data?.region ?? "china";
  const fixed = DEMO_LOCATION[seed];
  const byRegion = REGION_LOCATION[region] ?? REGION_LOCATION.china;
  const r = (salt: string) => demoRandom(seed, salt);
  const nearby = region === "eu";
  const certs = ["CE", "RoHS", "FCC"].slice(0, 2 + Math.floor(r("certs") * 2));
  const deliveryMin = nearby ? 1 + Math.floor(r("dmin") * 2) : 6 + Math.floor(r("dmin") * 6);
  const gaps = COMPATIBILITY_CRITERIA.filter((c, k) => k >= 5 && r(`gap${k}`) < 0.55);
  return {
    country: fixed?.country ?? byRegion.country,
    flag: fixed?.flag ?? byRegion.flag,
    city: fixed?.city ?? byRegion.cities[Math.floor(r("city") * byRegion.cities.length)],
    certifications: certs,
    certificationPending: !quote.verified,
    directShipping: quote.moq <= 10 || r("direct") < 0.7,
    delivery: [deliveryMin, deliveryMin + (nearby ? 2 : 3 + Math.floor(r("dspan") * 4))],
    transport: nearby ? "Terrestre (DDP)" : "Aéreo (DDP)",
    quality: 0.8 + r("quality") * 0.15,
    compliance: quote.verified ? 0.88 + r("compliance") * 0.1 : 0.7 + r("compliance") * 0.1,
    scalability: 0.78 + r("scalability") * 0.18,
    compatibilityGaps: gaps,
  };
}

export const DEMO_SEARCH_OPTIONS = {
  logisticsModels: [
    { value: "direct", label: "Envío directo" },
    { value: "any", label: "Cualquiera" },
  ],
  leadTimes: [
    { value: "", label: "Sin límite" },
    { value: "7", label: "≤ 7 días" },
    { value: "14", label: "≤ 14 días" },
    { value: "21", label: "≤ 21 días" },
    { value: "30", label: "≤ 30 días" },
  ],
  moqs: [
    { value: "", label: "Sin límite" },
    { value: "10", label: "≤ 10" },
    { value: "50", label: "≤ 50" },
    { value: "100", label: "≤ 100" },
    { value: "500", label: "≤ 500" },
  ],
};
