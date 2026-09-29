import type {
  RiskDimension,
  RiskLevel,
  SupplierCapabilityAnswer,
  SupplierProvenance,
  SupplierQuote,
  SupplierQuoteDetail,
  SupplyCapability,
} from "./api.ts";
import { DEMO_SALE, DEMO_TRANSPORT_SHARE, DEMO_UNIT_COSTS } from "./demo/economics.ts";
import { demoSupplierProfile, type DemoSupplierProfile } from "./demo/sourcing.ts";
import { supplierRadarValues } from "./sourcing.ts";

/** La moneda en la que el panel razona sobre márgenes, igual que el backend. */
const ACCOUNTING_CURRENCY = "EUR";

/** Si dos importes se pueden sumar sin inventar un tipo de cambio. Dos monedas
 * desconocidas tampoco lo son: que nadie haya dicho en qué moneda está un
 * precio no permite suponer que coinciden. */
function comparable(left: string | null, right: string): boolean {
  return left !== null && left.trim().toUpperCase() === right;
}

// Vista de la pantalla de Proveedores.
//
// Desde el Milestone 39 (ADR 0017) las capacidades del §16, la verificación y
// el riesgo por dimensiones son **reales**: vienen del backend con su
// procedencia. Lo que sigue siendo de demostración es lo que el backend no
// guarda todavía —ciudad de ejemplo, certificaciones, calidad, compliance y
// escalabilidad— y vive en lib/demo/sourcing.ts.
//
// Y lo que nadie ha declarado se queda **sin declarar**: ni cero, ni «no».

export const SUPPLIER_AXES = [
  { key: "price", label: "Precio" },
  { key: "logistics", label: "Logística" },
  { key: "reliability", label: "Fiabilidad" },
  { key: "quality", label: "Calidad" },
  { key: "compliance", label: "Compliance" },
  { key: "flexibility", label: "Flexibilidad" },
  { key: "scalability", label: "Escalabilidad" },
] as const;

export type SupplierRisk = "Bajo" | "Medio" | "Alto" | "Sin evaluar";

export interface RankedSupplier {
  quote: SupplierQuoteDetail;
  profile: DemoSupplierProfile;
  /** `null` en un eje = nadie ha dicho ese dato. **No es cero.** */
  axes: Record<string, number | null>;
  /** 0–100, o `null` cuando falta algún eje: promediar lo que falta como cero
   * convertiría a un proveedor del que no se sabe nada en uno malo, y a uno del
   * que se sabe la mitad en uno mediocre. */
  score: number | null;
  /** Cuántos de los siete ejes tienen valor. Es lo que hace legible un `null`. */
  knownAxes: number;
  /** El peor nivel de las ocho dimensiones de §11. No es una puntuación: es un
   * máximo, y la pantalla enseña las ocho al lado. */
  risk: SupplierRisk;
}

export function supplierAxes(
  quote: SupplierQuoteDetail,
  quotes: SupplierQuoteDetail[],
  profile: DemoSupplierProfile,
): Record<string, number | null> {
  const relative = supplierRadarValues(quote, quotes);
  return {
    price: relative.price,
    logistics: relative.logistics,
    // Nulo cuando nadie la ha valorado. Antes era 0.0 por defecto de columna.
    reliability: quote.supplier?.reliability_score ?? null,
    quality: profile.quality,
    compliance: profile.compliance,
    flexibility: relative.flexibility,
    scalability: profile.scalability,
  };
}

const RISK_ORDER: Record<RiskLevel, number> = { high: 0, medium: 1, low: 2, unknown: 3 };
const RISK_LABEL: Record<RiskLevel, SupplierRisk> = {
  high: "Alto",
  medium: "Medio",
  low: "Bajo",
  unknown: "Sin evaluar",
};

/** El peor nivel de las dimensiones evaluadas, o «Sin evaluar» si no hay
 * ninguna. Deliberadamente un máximo y no una media: una dimensión en rojo no
 * se compensa con siete en verde, y §11 prohíbe reducir el riesgo a un número. */
export function supplierRisk(quote: SupplierQuoteDetail): SupplierRisk {
  const assessed = (quote.risk ?? []).filter((r) => r.level !== "unknown");
  if (assessed.length === 0) return "Sin evaluar";
  const worst = assessed.reduce((a, b) => (RISK_ORDER[a.level] <= RISK_ORDER[b.level] ? a : b));
  return RISK_LABEL[worst.level];
}

/** Las dimensiones que nadie ha podido evaluar. Un perfil sin rojos no
 * significa que no haya riesgo mientras esta lista no esté vacía. */
export function unassessedRisk(quote: SupplierQuoteDetail): RiskDimension[] {
  return (quote.risk ?? []).filter((r) => r.level === "unknown").map((r) => r.dimension);
}

/** Proveedores con su perfil, ejes, score y riesgo. Ordena por score cuando lo
 * hay; los que no tienen score van después, y dentro de cada grupo manda el
 * coste de aterrizaje más bajo — y los que no lo tienen, al final. */
export function rankSuppliers(quotes: SupplierQuoteDetail[]): RankedSupplier[] {
  return quotes
    .map((quote) => {
      const profile = demoSupplierProfile(quote);
      const axes = supplierAxes(quote, quotes, profile);
      const values = Object.values(axes);
      const known = values.filter((v): v is number => v !== null);
      return {
        quote,
        profile,
        axes,
        score:
          known.length === values.length
            ? Math.round((known.reduce((a, b) => a + b, 0) / known.length) * 100)
            : null,
        knownAxes: known.length,
        risk: supplierRisk(quote),
      };
    })
    .sort(
      (a, b) =>
        Number(a.score === null) - Number(b.score === null) ||
        (b.score ?? 0) - (a.score ?? 0) ||
        Number(a.quote.total_landed_cost_per_unit === null) -
          Number(b.quote.total_landed_cost_per_unit === null) ||
        (a.quote.total_landed_cost_per_unit ?? 0) - (b.quote.total_landed_cost_per_unit ?? 0),
    );
}

/** La media de cada eje entre los proveedores que lo tienen. Un eje que nadie
 * declara vale `null`: no hay media de nada. */
export function averageAxes(ranked: RankedSupplier[]): Record<string, number | null> {
  const avg: Record<string, number | null> = {};
  for (const { key } of SUPPLIER_AXES) {
    const known = ranked.map((r) => r.axes[key]).filter((v): v is number => v !== null);
    avg[key] = known.length ? known.reduce((a, b) => a + b, 0) / known.length : null;
  }
  return avg;
}

/** Etiqueta destacada de cada proveedor del top: recomendado (#1), mejor precio
 * y mejor opción en el destino. Un proveedor sin precio no puede ser «mejor
 * precio»: no compite en un eje que no tiene. */
export function topBadges(ranked: RankedSupplier[], destinationRegion: string): Map<string, string> {
  const badges = new Map<string, string>();
  if (ranked.length === 0) return badges;
  badges.set(ranked[0].quote.id, "Proveedor recomendado");
  const rest = ranked.slice(1);
  const cheapest = rest
    .filter((r) => r.quote.unit_price !== null)
    .sort((a, b) => (a.quote.unit_price ?? 0) - (b.quote.unit_price ?? 0))[0];
  const local = rest
    .filter((r) => region(r.quote) === destinationRegion)
    .sort((a, b) => a.profile.delivery[0] - b.profile.delivery[0])[0];
  if (local) badges.set(local.quote.id, destinationRegion === "eu" ? "Mejor opción UE" : "Mejor opción local");
  if (cheapest && !badges.has(cheapest.quote.id)) badges.set(cheapest.quote.id, "Mejor precio");
  return badges;
}

/** De dónde sale la mercancía: el país del proveedor si consta y, si no, su
 * región. El `data.region` del mock sigue valiendo para las cotizaciones
 * antiguas, que no tienen proveedor con país. */
export function region(quote: SupplierQuoteDetail): string | null {
  return quote.supplier?.region ?? (quote.data?.region as string | undefined) ?? null;
}

export interface LandedLine {
  key: string;
  label: string;
  amount: number;
  total?: boolean;
}

/** Coste total estimado por unidad («landed cost»): mismos supuestos que
 * Economía. Devuelve `null` cuando falta el precio o la logística — un desglose
 * que trata lo desconocido como cero da un total que parece cierto. */
export function landedBreakdown(quote: SupplierQuote): LandedLine[] | null {
  if (quote.unit_price === null || quote.logistics_cost_per_unit === null) return null;
  // Los demás renglones (fulfillment, pasarela, devoluciones) están en euros:
  // son supuestos de lib/demo/economics. Sumarles un precio en dólares daría un
  // total con símbolo de euro que no es euros, que es la misma mentira que el
  // backend se niega a contar cuando no hay tipo de cambio (ADR 0017).
  if (!comparable(quote.currency, ACCOUNTING_CURRENCY)) return null;
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

/** Etiqueta en español de cada capacidad del §16. */
export const CAPABILITY_LABEL: Record<SupplyCapability, string> = {
  direct_shipping: "Envío directo",
  dropshipping: "Dropshipping (pago tras venta)",
  blind_shipping: "Envío ciego",
  custom_packaging: "Packaging propio",
  tracking: "Tracking",
  returns: "Devoluciones",
  eu_return_address: "Dirección de devoluciones UE",
  sla: "SLA contractual",
};

export const RISK_DIMENSION_LABEL: Record<RiskDimension, string> = {
  identity: "Identidad",
  financial: "Financiero",
  quality: "Calidad",
  delivery: "Entrega",
  legal: "Legal",
  fraud: "Fraude",
  dependency: "Dependencia",
  geopolitical_logistics: "Geopolítico / logístico",
};

export const PROVENANCE_LABEL: Record<SupplierProvenance, string> = {
  third_party_verified: "Verificado por un tercero",
  supplier_claim: "Lo dice el proveedor",
  declared: "Declarado por nosotros",
  amazona_estimate: "Estimación de AMAZONA",
  simulated: "Dato de demostración",
  unknown: "Sin declarar",
};

export interface CompatibilityItem {
  label: string;
  /** `null` = **nadie lo ha declarado**. No es «no cumple». */
  ok: boolean | null;
  provenance: SupplierProvenance;
  note: string | null;
}

/** Compatibilidad con el modelo sin stock propio (§16).
 *
 * El MOQ sale de la cotización; las siete capacidades salen de lo **declarado**
 * en el backend. Hasta el Milestone 39 las ocho las inventaba un generador
 * determinista en lib/demo, que es lo que este milestone quita de en medio. */
export function compatibility(quote: SupplierQuoteDetail): CompatibilityItem[] {
  const byCapability = new Map<SupplyCapability, SupplierCapabilityAnswer>(
    (quote.capabilities ?? []).map((c) => [c.capability, c]),
  );
  const items: CompatibilityItem[] = [
    {
      label: "MOQ bajo (≤ 10)",
      ok: quote.moq === null ? null : quote.moq <= 10,
      provenance: quote.moq === null ? "unknown" : (quote.provenance ?? "unknown"),
      note: null,
    },
  ];
  for (const capability of Object.keys(CAPABILITY_LABEL) as SupplyCapability[]) {
    const answer = byCapability.get(capability);
    items.push({
      label: CAPABILITY_LABEL[capability],
      ok: answer?.supported ?? null,
      provenance: answer?.provenance ?? "unknown",
      note: answer?.note ?? null,
    });
  }
  return items;
}

/** Si una capacidad está declarada como soportada. `false` tanto si se declara
 * que no como si nadie lo ha dicho — pero quien filtre por esto tiene que saber
 * que está excluyendo también lo no declarado. */
function declaresSupport(quote: SupplierQuoteDetail, capability: SupplyCapability): boolean {
  return (quote.capabilities ?? []).some((c) => c.capability === capability && c.supported === true);
}

export interface SearchParams {
  destination: string;
  /** "" = global. */
  origin: string;
  /** "direct" = solo proveedores que DECLARAN envío directo. */
  logistics: string;
  minPrice: string;
  maxPrice: string;
  maxLeadTime: string;
  maxMoq: string;
  requireCertification: boolean;
  /** Solo proveedores cuya identidad ha verificado un tercero. */
  verifiedOnly: boolean;
  maxResults: number;
}

export const DEFAULT_SEARCH: SearchParams = {
  destination: "eu",
  origin: "",
  // «Cualquiera» por defecto desde el Milestone 39: filtrar por envío directo
  // ahora exige una declaración real, y ningún proveedor la tiene hasta que
  // alguien la escriba. Arrancar en "direct" dejaría la pantalla vacía y
  // parecería que no hay proveedores, cuando lo que no hay son respuestas.
  logistics: "any",
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

/** Filtros de «Parámetros de búsqueda», aplicados en el cliente.
 *
 * Un dato desconocido **no pasa** un filtro numérico: quien pide «MOQ ≤ 10» no
 * está pidiendo «MOQ ≤ 10 o que no se sepa». Y un filtro vacío no filtra, que
 * es distinto. */
export function filterSuppliers(ranked: RankedSupplier[], p: SearchParams): RankedSupplier[] {
  const minPrice = limit(p.minPrice);
  const maxPrice = limit(p.maxPrice);
  const maxLead = limit(p.maxLeadTime);
  const maxMoq = limit(p.maxMoq);
  const within = (value: number | null, bound: number | undefined, cmp: (v: number, b: number) => boolean) =>
    bound === undefined || (value !== null && cmp(value, bound));
  return ranked.filter(
    ({ quote, profile }) =>
      (!p.origin || region(quote) === p.origin) &&
      (p.logistics !== "direct" || declaresSupport(quote, "direct_shipping")) &&
      within(quote.unit_price, minPrice, (v, b) => v >= b) &&
      within(quote.unit_price, maxPrice, (v, b) => v <= b) &&
      within(quote.lead_time_days, maxLead, (v, b) => v <= b) &&
      within(quote.moq, maxMoq, (v, b) => v <= b) &&
      (!p.requireCertification || (profile.certifications.includes("CE") && !profile.certificationPending)) &&
      (!p.verifiedOnly || quote.supplier?.verification === "third_party_verified"),
  );
}
