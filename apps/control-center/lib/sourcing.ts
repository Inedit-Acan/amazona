import type { SupplierQuote } from "@/lib/api";

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
