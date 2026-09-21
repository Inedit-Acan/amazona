import type { SupplierQuote } from "@/lib/api";

/** El backend no garantiza el orden de `quotes` (la consulta no lleva ORDER BY):
 * el ranking del agente es por coste total de entrega ascendente, así que se
 * reaplica aquí. */
export function sortByLandedCost(quotes: SupplierQuote[]): SupplierQuote[] {
  return [...quotes].sort((a, b) => a.total_landed_cost_per_unit - b.total_landed_cost_per_unit);
}

/** Filtros aplicados en el cliente sobre los resultados reales devueltos por el
 * backend (que solo acepta categoría, región de destino y nº de resultados). */
export interface QuoteFilters {
  maxUnitPrice?: number;
  maxLeadTimeDays?: number;
  maxMoq?: number;
}

export function applyFilters(quotes: SupplierQuote[], filters: QuoteFilters): SupplierQuote[] {
  return quotes.filter(
    (q) =>
      (filters.maxUnitPrice === undefined || q.unit_price <= filters.maxUnitPrice) &&
      (filters.maxLeadTimeDays === undefined || q.lead_time_days <= filters.maxLeadTimeDays) &&
      (filters.maxMoq === undefined || q.moq <= filters.maxMoq),
  );
}

export type Distinction = "lowest_cost" | "most_reliable" | "fastest" | "lowest_moq";

export const DISTINCTION_LABEL: Record<Distinction, string> = {
  lowest_cost: "Menor coste entregado",
  most_reliable: "Más fiable",
  fastest: "Plazo más corto",
  lowest_moq: "Menor MOQ",
};

/** Qué proveedor lidera cada criterio dentro del conjunto encontrado. Con un
 * solo proveedor todo "lidera" trivialmente, así que no se distingue nada. */
export function distinctionsFor(quotes: SupplierQuote[]): Map<string, Distinction[]> {
  const result = new Map<string, Distinction[]>();
  if (quotes.length < 2) return result;

  const best: [Distinction, (q: SupplierQuote) => number, "min" | "max"][] = [
    ["lowest_cost", (q) => q.total_landed_cost_per_unit, "min"],
    ["most_reliable", (q) => q.reliability_score, "max"],
    ["fastest", (q) => q.lead_time_days, "min"],
    ["lowest_moq", (q) => q.moq, "min"],
  ];

  for (const [distinction, value, direction] of best) {
    const target = direction === "min" ? Math.min(...quotes.map(value)) : Math.max(...quotes.map(value));
    for (const quote of quotes) {
      if (value(quote) === target) {
        result.set(quote.id, [...(result.get(quote.id) ?? []), distinction]);
      }
    }
  }
  return result;
}

/** Ejes del radar de proveedor que el backend puede respaldar hoy. Calidad,
 * compliance y escalabilidad (parte de la spec §6.10) no tienen dato real. */
export const SUPPLIER_RADAR_AXES = [
  { key: "price", label: "Precio" },
  { key: "logistics", label: "Logística" },
  { key: "reliability", label: "Fiabilidad" },
  { key: "flexibility", label: "Flexibilidad" },
  { key: "speed", label: "Rapidez" },
] as const;

/** Todo normalizado a 0-1 con "más alto = mejor": en los ejes donde menos es
 * mejor (precio, logística, MOQ, plazo) el mejor del conjunto vale 1 y el resto
 * lo que le corresponde proporcionalmente (mín / valor). La fiabilidad ya es
 * 0-1 en origen. Es una métrica RELATIVA al conjunto encontrado, no absoluta. */
export function supplierRadarValues(quote: SupplierQuote, quotes: SupplierQuote[]): Record<string, number> {
  const ratio = (pick: (q: SupplierQuote) => number) => {
    const value = pick(quote);
    if (value <= 0) return 1;
    const min = Math.min(...quotes.map(pick).filter((v) => v > 0));
    return Math.min(1, min / value);
  };
  return {
    price: ratio((q) => q.unit_price),
    logistics: ratio((q) => q.logistics_cost_per_unit),
    reliability: quote.reliability_score,
    flexibility: ratio((q) => q.moq),
    speed: ratio((q) => q.lead_time_days),
  };
}

export function averageRadarValues(quotes: SupplierQuote[]): Record<string, number> {
  const all = quotes.map((q) => supplierRadarValues(q, quotes));
  const average: Record<string, number> = {};
  for (const axis of SUPPLIER_RADAR_AXES) {
    average[axis.key] = all.reduce((sum, v) => sum + v[axis.key], 0) / all.length;
  }
  return average;
}

/** Importe sin símbolo de divisa: el backend no especifica moneda. */
export function formatAmount(value: number): string {
  return value.toLocaleString("es-ES", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
