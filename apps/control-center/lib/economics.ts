import type { EconomicAnalysis, EconomicScenario, SupplierQuote } from "@/lib/api";

// El motor económico vive en el backend (economics/scenarios.py, "una única
// fuente de verdad económica"). Este módulo NO calcula escenarios, punto de
// equilibrio ni sensibilidad: solo ordena, etiqueta y reexpresa lo que el
// backend ya devolvió.

export const SCENARIO_KEYS = ["conservative", "base", "optimistic"] as const;
export type ScenarioKey = (typeof SCENARIO_KEYS)[number];

export const SCENARIO_LABELS: Record<ScenarioKey, string> = {
  conservative: "Conservador",
  base: "Base",
  optimistic: "Optimista",
};

export interface ScenarioEntry {
  key: ScenarioKey;
  label: string;
  scenario: EconomicScenario;
}

/** Escenarios presentes en el análisis, siempre en orden conservador → optimista. */
export function scenarioList(analysis: Pick<EconomicAnalysis, "data">): ScenarioEntry[] {
  const scenarios = analysis.data?.scenarios;
  if (!scenarios) return [];
  return SCENARIO_KEYS.flatMap((key) =>
    scenarios[key] ? [{ key, label: SCENARIO_LABELS[key], scenario: scenarios[key] }] : [],
  );
}

/** Contribución por unidad = precio de venta − coste total de entrega: la misma
 * definición que el backend usa dentro de build_scenarios. */
export function unitContribution(salePrice: number, landedCost: number): number {
  return salePrice - landedCost;
}

export type Recommendation = EconomicAnalysis["recommendation"];

export const RECOMMENDATION_LABEL: Record<Recommendation, string> = {
  GO: "Favorable",
  REVIEW: "A revisar",
  NO_GO: "No viable",
};

export interface Viability {
  title: string;
  detail: string;
  tone: "ok" | "warn" | "bad";
}

/** Nunca se afirma "rentable" sin "bajo estas hipótesis" (spec §7.10). No se
 * reescriben los umbrales del agente: solo se traduce su recomendación. */
export function viabilityStatement(recommendation: Recommendation): Viability {
  switch (recommendation) {
    case "GO":
      return {
        title: "Rentable bajo estas hipótesis",
        detail:
          "La demanda estimada y los factores de escenario son simulados: valida los supuestos antes de decidir.",
        tone: "ok",
      };
    case "REVIEW":
      return {
        title: "Requiere revisión",
        detail: "El agente recomienda revisar el análisis antes de seguir adelante.",
        tone: "warn",
      };
    case "NO_GO":
      return {
        title: "No viable bajo estas hipótesis",
        detail: "Con estos supuestos el agente no considera viable el producto.",
        tone: "bad",
      };
  }
}

/** Cada búsqueda de proveedores crea cotizaciones nuevas, así que un producto
 * puede tener el mismo proveedor varias veces (una por búsqueda). Se deja una
 * por proveedor — la de menor coste entregado, salvo que se pida conservar una
 * concreta (la que llega por URL desde Proveedores). */
export function dedupeQuotesBySupplier(quotes: SupplierQuote[], keepId?: string): SupplierQuote[] {
  const chosen = new Map<string, SupplierQuote>();
  const sorted = [...quotes].sort((a, b) => a.total_landed_cost_per_unit - b.total_landed_cost_per_unit);
  for (const quote of sorted) {
    const current = chosen.get(quote.supplier_id);
    if (!current || (quote.id === keepId && current.id !== keepId)) {
      chosen.set(quote.supplier_id, quote);
    }
  }
  return [...chosen.values()].sort((a, b) => a.total_landed_cost_per_unit - b.total_landed_cost_per_unit);
}
