import type { SupplierQuote } from "@/lib/api";

/** Ejes del radar de proveedores, normalizados a 0-1 con «más alto = mejor».
 *
 * En los ejes donde menos es mejor (precio, logística, MOQ, plazo) el mejor del
 * conjunto vale 1 y el resto lo que le corresponde proporcionalmente
 * (mín / valor). Es una métrica RELATIVA al conjunto encontrado, no absoluta.
 *
 * Desde el Milestone 39 un eje puede valer `null`: lo que el proveedor no ha
 * dicho **no tiene valor**, y no vale cero. Un MOQ desconocido pintado como 0
 * sería un proveedor perfectamente flexible que nadie ha comprobado, que es el
 * cero inventado aplicado a un gráfico.
 */
export function supplierRadarValues(
  quote: SupplierQuote,
  quotes: SupplierQuote[],
): Record<string, number | null> {
  const ratio = (pick: (q: SupplierQuote) => number | null) => {
    const value = pick(quote);
    if (value === null) return null;
    if (value <= 0) return 1;
    const known = quotes.map(pick).filter((v): v is number => v !== null && v > 0);
    if (known.length === 0) return 1;
    return Math.min(1, Math.min(...known) / value);
  };
  return {
    price: ratio((q) => q.unit_price),
    logistics: ratio((q) => q.logistics_cost_per_unit),
    flexibility: ratio((q) => q.moq),
    speed: ratio((q) => q.lead_time_days),
  };
}
