import type { SupplierQuote } from "./api.ts";
import { DEMO_SALE, DEMO_TRANSPORT_SHARE, DEMO_UNIT_COSTS } from "./demo/economics.ts";
import { COMPATIBILITY_CRITERIA, demoSupplierProfile, type DemoSupplierProfile } from "./demo/sourcing.ts";
import { supplierRadarValues } from "./sourcing.ts";

// Vista de la pantalla de Proveedores (mockup docs/design/panel proveedores.png).
// Precio, logística, MOQ, plazo, fiabilidad y verificación son de la cotización
// (real o de demostración); país, ciudad, certificaciones, envío directo, plazo de
// entrega, calidad, compliance, escalabilidad y compatibilidad vienen del perfil
// de demostración (lib/demo/sourcing.ts).

export const SUPPLIER_AXES = [
  { key: "price", label: "Precio" },
  { key: "logistics", label: "Logística" },
  { key: "reliability", label: "Fiabilidad" },
  { key: "quality", label: "Calidad" },
  { key: "compliance", label: "Compliance" },
  { key: "flexibility", label: "Flexibilidad" },
  { key: "scalability", label: "Escalabilidad" },
] as const;

export type SupplierRisk = "Bajo" | "Medio" | "Alto";

export interface RankedSupplier {
  quote: SupplierQuote;
  profile: DemoSupplierProfile;
  axes: Record<string, number>;
  /** 0–100. */
  score: number;
  risk: SupplierRisk;
}

export function supplierAxes(quote: SupplierQuote, quotes: SupplierQuote[], profile: DemoSupplierProfile): Record<string, number> {
  const relative = supplierRadarValues(quote, quotes);
  return {
    price: relative.price,
    logistics: relative.logistics,
    reliability: quote.reliability_score,
    quality: profile.quality,
    compliance: profile.compliance,
    flexibility: relative.flexibility,
    scalability: profile.scalability,
  };
}

export function supplierRisk(quote: SupplierQuote, profile: DemoSupplierProfile): SupplierRisk {
  if (quote.reliability_score < 0.75) return "Alto";
  if (!quote.verified || profile.compliance < 0.8) return "Medio";
  return "Bajo";
}

/** Proveedores con su perfil, ejes, score (media de los 7 ejes) y riesgo, de mayor a menor score. */
export function rankSuppliers(quotes: SupplierQuote[]): RankedSupplier[] {
  return quotes
    .map((quote) => {
      const profile = demoSupplierProfile(quote);
      const axes = supplierAxes(quote, quotes, profile);
      const values = Object.values(axes);
      return {
        quote,
        profile,
        axes,
        score: Math.round((values.reduce((a, b) => a + b, 0) / values.length) * 100),
        risk: supplierRisk(quote, profile),
      };
    })
    .sort((a, b) => b.score - a.score || a.quote.total_landed_cost_per_unit - b.quote.total_landed_cost_per_unit);
}

export function averageAxes(ranked: RankedSupplier[]): Record<string, number> {
  const avg: Record<string, number> = {};
  for (const { key } of SUPPLIER_AXES) {
    avg[key] = ranked.length ? ranked.reduce((sum, r) => sum + r.axes[key], 0) / ranked.length : 0;
  }
  return avg;
}

/** Etiqueta destacada de cada proveedor del top: recomendado (#1), mejor precio y
 * mejor opción en el destino (entrega más rápida desde la misma región). */
export function topBadges(ranked: RankedSupplier[], destinationRegion: string): Map<string, string> {
  const badges = new Map<string, string>();
  if (ranked.length === 0) return badges;
  badges.set(ranked[0].quote.id, "Proveedor recomendado");
  const rest = ranked.slice(1);
  const cheapest = [...rest].sort((a, b) => a.quote.unit_price - b.quote.unit_price)[0];
  const local = rest
    .filter((r) => r.quote.data?.region === destinationRegion)
    .sort((a, b) => a.profile.delivery[0] - b.profile.delivery[0])[0];
  if (local) badges.set(local.quote.id, destinationRegion === "eu" ? "Mejor opción UE" : "Mejor opción local");
  if (cheapest && !badges.has(cheapest.quote.id)) badges.set(cheapest.quote.id, "Mejor precio");
  return badges;
}

export interface LandedLine {
  key: string;
  label: string;
  amount: number;
  total?: boolean;
}

/** Coste total estimado por unidad («landed cost»): mismos supuestos que Economía. */
export function landedBreakdown(quote: SupplierQuote): LandedLine[] {
  const transport = Math.round(quote.logistics_cost_per_unit * DEMO_TRANSPORT_SHARE * 100) / 100;
  const tariff = Math.round((quote.logistics_cost_per_unit - transport) * 100) / 100;
  const payment = (DEMO_SALE.salePrice * DEMO_UNIT_COSTS.paymentFeePct) / 100;
  const returns = (DEMO_SALE.salePrice * DEMO_UNIT_COSTS.returnsPct) / 100;
  const lines: LandedLine[] = [
    { key: "supplier", label: "Precio proveedor", amount: quote.unit_price },
    { key: "transport", label: "Transporte (aéreo, DDP)", amount: transport },
    { key: "tariff", label: "Arancel / IVA (estimado)", amount: tariff },
    { key: "fulfillment", label: "Gestión / fulfillment", amount: DEMO_UNIT_COSTS.fulfillment },
    { key: "payment", label: "Pago / cambio divisa", amount: payment },
    { key: "returns", label: `Reserva devoluciones (${DEMO_UNIT_COSTS.returnsPct} %)`, amount: returns },
  ];
  return [...lines, { key: "total", label: "Coste total estimado", amount: lines.reduce((s, l) => s + l.amount, 0), total: true }];
}

export interface CompatibilityItem {
  label: string;
  ok: boolean;
}

/** Compatibilidad con el modelo de AMAZONA. El MOQ es real; el resto, del perfil demo. */
export function compatibility(quote: SupplierQuote, profile: DemoSupplierProfile): CompatibilityItem[] {
  return COMPATIBILITY_CRITERIA.map((label) => ({
    label,
    ok:
      label === "MOQ bajo (≤ 10)"
        ? quote.moq <= 10
        : label === "Dropshipping / envío directo"
          ? profile.directShipping
          : !profile.compatibilityGaps.includes(label),
  }));
}

export interface SearchParams {
  destination: string;
  /** "" = global. */
  origin: string;
  /** "direct" = solo proveedores con envío directo. */
  logistics: string;
  minPrice: string;
  maxPrice: string;
  maxLeadTime: string;
  maxMoq: string;
  requireCertification: boolean;
  verifiedOnly: boolean;
  maxResults: number;
}

export const DEFAULT_SEARCH: SearchParams = {
  destination: "eu",
  origin: "",
  logistics: "direct",
  minPrice: "",
  maxPrice: "",
  maxLeadTime: "",
  maxMoq: "",
  requireCertification: false,
  verifiedOnly: false,
  maxResults: 5,
};

function limit(value: string): number | undefined {
  if (value.trim() === "") return undefined;
  const n = Number(value);
  return Number.isFinite(n) && n >= 0 ? n : undefined;
}

/** Filtros de «Parámetros de búsqueda», aplicados en el cliente sobre las cotizaciones. */
export function filterSuppliers(ranked: RankedSupplier[], p: SearchParams): RankedSupplier[] {
  const minPrice = limit(p.minPrice);
  const maxPrice = limit(p.maxPrice);
  const maxLead = limit(p.maxLeadTime);
  const maxMoq = limit(p.maxMoq);
  return ranked.filter(
    ({ quote, profile }) =>
      (!p.origin || quote.data?.region === p.origin) &&
      (p.logistics !== "direct" || profile.directShipping) &&
      (minPrice === undefined || quote.unit_price >= minPrice) &&
      (maxPrice === undefined || quote.unit_price <= maxPrice) &&
      (maxLead === undefined || quote.lead_time_days <= maxLead) &&
      (maxMoq === undefined || quote.moq <= maxMoq) &&
      (!p.requireCertification || (profile.certifications.includes("CE") && !profile.certificationPending)) &&
      (!p.verifiedOnly || quote.verified),
  );
}
