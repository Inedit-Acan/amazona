// DATOS DE DEMOSTRACIÓN — pantalla de Proveedores y abastecimiento.
//
// Valores inventados (con permiso del propietario, 22-09-2026) para que el
// panel se vea como el mockup mientras el backend no los proporciona.
// Deterministas por proveedor. La pantalla dice cuáles son (DataProvenanceBadge).
//
// ## Qué dejó de estar aquí en el Milestone 39 (ADR 0017)
//
// Las ocho capacidades del plan maestro §16 —envío directo, dropshipping,
// envío ciego, packaging, tracking, devoluciones, dirección de retorno UE y
// SLA— y la verificación del proveedor. Eran ocho afirmaciones sobre el mundo
// salidas de un generador pseudoaleatorio, y ahora son declaraciones reales con
// procedencia que vienen del backend. Lo que nadie ha declarado se enseña como
// **no declarado**, no como «no».
//
// Lo que sigue siendo de demostración, porque el backend no lo guarda todavía:
// ciudad, certificaciones, calidad, compliance, escalabilidad y plazos de
// entrega del perfil. Cada uno con su casilla pendiente en el milestone.

import type {
  SupplierCapabilityAnswer,
  SupplierQuoteDetail,
  SupplierRiskAssessment,
  SupplyCapability,
} from "../api.ts";
import { demoRandom } from "./random.ts";

/** Moneda de las cotizaciones de ejemplo. Está escrita porque un precio sin
 * moneda no se compara con ninguno, no porque nadie la haya negociado. */
const DEMO_CURRENCY = "EUR";

const DEMO_CAPABILITIES: SupplyCapability[] = [
  "direct_shipping",
  "dropshipping",
  "blind_shipping",
  "custom_packaging",
  "tracking",
  "returns",
  "eu_return_address",
  "sla",
];

/** Capacidades de ejemplo, declaradas como lo que son: simuladas. */
function demoCapabilityAnswers(seed: string, moq: number): SupplierCapabilityAnswer[] {
  const r = (salt: string) => demoRandom(seed, salt);
  return DEMO_CAPABILITIES.map((capability, k) => ({
    capability,
    supported: capability === "dropshipping" ? moq <= 10 : r(`cap${k}`) > 0.45,
    provenance: "simulated" as const,
    source: "lib/demo/sourcing.ts",
    note: null,
    observed_at: null,
    product_specific: false,
  }));
}

const DEMO_RISK_DIMENSIONS = [
  "identity",
  "financial",
  "quality",
  "delivery",
  "legal",
  "fraud",
  "dependency",
  "geopolitical_logistics",
] as const;

/** Riesgo de ejemplo por dimensión. Igual que el real: ocho respuestas, ninguna
 * puntuación total. */
function demoRisk(seed: string): SupplierRiskAssessment[] {
  const r = (salt: string) => demoRandom(seed, salt);
  return DEMO_RISK_DIMENSIONS.map((dimension, k) => {
    const draw = r(`risk${k}`);
    const level = draw > 0.8 ? "high" : draw > 0.45 ? "medium" : "low";
    return {
      dimension,
      level,
      rationale: "evaluación de demostración: no sale de ningún hecho comprobado",
      provenance: "simulated" as const,
      basis: ["lib/demo/sourcing.ts"],
    };
  });
}

/** Cotizaciones de ejemplo cuando el producto no tiene ninguna real. */
export function demoQuotes(productId: string): SupplierQuoteDetail[] {
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
    currency: DEMO_CURRENCY,
    quoted_unit: "piece",
    quoted_quantity: 1,
    moq,
    lead_time_days: lead,
    transit_days: null,
    transport_mode: null,
    incoterm: region === "eu" ? "DAP" : "DDP",
    payment_terms: null,
    destination_market: "eu",
    valid_from: null,
    valid_until: null,
    provenance: "simulated" as const,
    source: "lib/demo/sourcing.ts",
    logistics_cost_per_unit: logistics,
    logistics_provenance: "simulated" as const,
    total_landed_cost_per_unit: Math.round((unit + logistics) * 100) / 100,
    data: { name, region },
    supplier: {
      id,
      name,
      identity_key: null,
      identity_method: null,
      region,
      country: null,
      city: null,
      website: null,
      // Un proveedor de demostración no lo ha verificado nadie: lo escribió un
      // fichero. Antes decía «verified» si su fiabilidad pasaba de 0,85.
      verification: "simulated" as const,
      verified_by: null,
      reliability_score: reliability,
      reliability_provenance: "simulated" as const,
      last_checked_at: null,
    },
    capabilities: demoCapabilityAnswers(id, moq),
    unanswered_capabilities: [],
    risk: demoRisk(id),
  }));
}

/** País y ciudad de ejemplo por proveedor de demostración. */
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

export interface DemoSupplierProfile {
  country: string;
  flag: "cn" | "eu" | "vn" | "mx" | "es" | "pl" | "hk";
  city: string;
  certifications: string[];
  certificationPending: boolean;
  /** Días de entrega al destino (mín, máx). */
  delivery: [number, number];
  transport: string;
  /** 0–1. */
  quality: number;
  compliance: number;
  scalability: number;
}

/** Perfil de demostración de un proveedor (real o demo): lo que el backend no
 * guarda todavía. El país y la ciudad reales, cuando existen, mandan sobre el
 * ejemplo: lo demo es relleno, nunca sustituto de un dato real. */
export function demoSupplierProfile(quote: SupplierQuoteDetail): DemoSupplierProfile {
  const seed = quote.supplier_id;
  const region = quote.supplier?.region ?? (quote.data?.region as string | undefined) ?? "china";
  const fixed = DEMO_LOCATION[seed];
  const byRegion = REGION_LOCATION[region] ?? REGION_LOCATION.china;
  const r = (salt: string) => demoRandom(seed, salt);
  const nearby = region === "eu";
  const certs = ["CE", "RoHS", "FCC"].slice(0, 2 + Math.floor(r("certs") * 2));
  const deliveryMin = nearby ? 1 + Math.floor(r("dmin") * 2) : 6 + Math.floor(r("dmin") * 6);
  const verified = quote.supplier?.verification === "third_party_verified";
  return {
    country: quote.supplier?.country ?? fixed?.country ?? byRegion.country,
    flag: fixed?.flag ?? byRegion.flag,
    city: quote.supplier?.city ?? fixed?.city ?? byRegion.cities[Math.floor(r("city") * byRegion.cities.length)],
    certifications: certs,
    certificationPending: !verified,
    delivery: [deliveryMin, deliveryMin + (nearby ? 2 : 3 + Math.floor(r("dspan") * 4))],
    transport: nearby ? "Terrestre (DDP)" : "Aéreo (DDP)",
    quality: 0.8 + r("quality") * 0.15,
    compliance: verified ? 0.88 + r("compliance") * 0.1 : 0.7 + r("compliance") * 0.1,
    scalability: 0.78 + r("scalability") * 0.18,
  };
}

export const DEMO_SEARCH_OPTIONS = {
  logisticsModels: [
    { value: "any", label: "Cualquiera" },
    { value: "direct", label: "Declara envío directo" },
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
