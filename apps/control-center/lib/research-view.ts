import type { Product, ResearchCandidate } from "./api.ts";
import {
  DEMO_INSIGHTS,
  DEMO_SUBCATEGORY,
  demoMarginRange,
  demoRandom,
  demoSignals,
  demoTrend,
} from "./demo/research.ts";

// Vista de la pantalla de Investigación (mockup docs/design/investigacion.png).
// Las señales del agente (demanda, competencia, futuro, riesgo regulatorio,
// escalabilidad) son reales cuando el producto se ha investigado en esta
// sesión; si no, vienen de lib/demo/research.ts. Tendencia, margen, subcategoría
// e ideas clave son siempre de demostración: el backend no los calcula.

export type Level = "Alta" | "Media" | "Baja";
export type Risk = "Bajo" | "Medio" | "Alto";

export const CATEGORY_LABEL: Record<string, string> = {
  electronics: "Electrónica",
  home: "Hogar",
  accessories: "Accesorios",
};

export function categoryLabel(category: string): string {
  return CATEGORY_LABEL[category] ?? category;
}

const COMPETITION_FAVORABILITY: Record<string, number> = { low: 1, medium: 0.6, high: 0.3 };
const COMPETITION_LEVEL: Record<string, Level> = { low: "Baja", medium: "Media", high: "Alta" };

export const RADAR_KEYS = ["demand", "future", "profitability", "logistics", "regulation", "scalability"] as const;
export type RadarKey = (typeof RADAR_KEYS)[number];

export interface ResearchRow {
  productId: string;
  name: string;
  category: string;
  categoryLabel: string;
  subcategory: string;
  /** 0–100. */
  score: number;
  demand: Level;
  competition: Level;
  growth: number;
  trend: number[];
  margin: [number, number];
  risk: Risk;
  insights: string[];
  rationale: string;
  radar: Record<RadarKey, number>;
  /** true si las señales del agente son de demostración (no investigado en esta sesión). */
  isDemo: boolean;
}

export function demandLevel(signal: number): Level {
  return signal >= 0.7 ? "Alta" : signal >= 0.5 ? "Media" : "Baja";
}

/** Score de oportunidad 0–100: media ponderada de las cinco señales del agente,
 * todas en «más alto = mejor». (El `opportunity_score` del agente solo combina
 * demanda y competencia.) */
export function opportunityScore(s: {
  demand: number;
  competitionFavorability: number;
  future: number;
  regulatoryRisk: number;
  scalability: number;
}): number {
  return Math.round(
    100 * (0.35 * s.demand + 0.2 * s.competitionFavorability + 0.2 * s.future + 0.1 * (1 - s.regulatoryRisk) + 0.15 * s.scalability),
  );
}

export function riskLevel(regulatoryRisk: number, competition: string): Risk {
  const score = regulatoryRisk * 0.6 + (competition === "high" ? 0.4 : competition === "medium" ? 0.2 : 0);
  return score < 0.3 ? "Bajo" : score < 0.45 ? "Medio" : "Alto";
}

export function buildRows(products: Product[], candidates: ResearchCandidate[]): ResearchRow[] {
  const byProduct = new Map(candidates.map((c) => [c.product_id, c]));
  const rows = products.map((product): ResearchRow => {
    const candidate = byProduct.get(product.id);
    const demo = demoSignals(product.id);
    const d = candidate?.data ?? {};
    const demand = d.demand_signal ?? demo.demand_signal;
    const competition = d.competition_level ?? demo.competition_level;
    const future = d.future_outlook_signal ?? demo.future_outlook_signal;
    const regulatoryRisk = d.regulatory_risk_signal ?? demo.regulatory_risk_signal;
    const scalability = d.scalability_signal ?? demo.scalability_signal;
    const competitionFavorability = COMPETITION_FAVORABILITY[competition] ?? 0.3;
    const trend = demoTrend(product.id, demand);
    const margin = demoMarginRange(product.id, competitionFavorability);
    const subcategories = DEMO_SUBCATEGORY[product.category] ?? ["General"];
    return {
      productId: product.id,
      name: product.name,
      category: product.category,
      categoryLabel: categoryLabel(product.category),
      subcategory: subcategories[Math.floor(demoRandom(product.id, "sub") * subcategories.length)],
      score: opportunityScore({ demand, competitionFavorability, future, regulatoryRisk, scalability }),
      demand: demandLevel(demand),
      competition: COMPETITION_LEVEL[competition] ?? "Media",
      growth: trend.growth,
      trend: trend.series,
      margin,
      risk: riskLevel(regulatoryRisk, competition),
      insights: DEMO_INSIGHTS[product.category] ?? DEMO_INSIGHTS.electronics,
      rationale: d.niche_rationale ?? demo.niche_rationale,
      radar: {
        demand,
        future,
        profitability: Math.min(1, (margin[0] + margin[1]) / 2 / 70),
        logistics: 0.5 + demoRandom(product.id, "logistics") * 0.4,
        regulation: 1 - regulatoryRisk,
        scalability,
      },
      isDemo: !candidate,
    };
  });
  return rows.sort((a, b) => b.score - a.score);
}

export function radarAverage(rows: ResearchRow[]): Record<RadarKey, number> {
  const avg = {} as Record<RadarKey, number>;
  for (const key of RADAR_KEYS) {
    avg[key] = rows.length ? rows.reduce((sum, r) => sum + r.radar[key], 0) / rows.length : 0;
  }
  return avg;
}

/** Frase de insight a partir de las filas: la categoría con más demanda media frente al total. */
export function topInsight(rows: ResearchRow[]): string | null {
  if (rows.length < 2) return null;
  const total = rows.reduce((sum, r) => sum + r.radar.demand, 0) / rows.length;
  const byCategory = new Map<string, number[]>();
  for (const r of rows) byCategory.set(r.categoryLabel, [...(byCategory.get(r.categoryLabel) ?? []), r.radar.demand]);
  if (byCategory.size === 1) {
    const [only] = byCategory.keys();
    return `Todos los candidatos actuales son de ${only.toLowerCase()}: analiza el mercado en otras categorías para compararlas.`;
  }
  const [label, values] = [...byCategory.entries()]
    .map(([k, v]) => [k, v.reduce((a, b) => a + b, 0) / v.length] as const)
    .sort((a, b) => b[1] - a[1])[0];
  const pct = Math.round((values / total - 1) * 100);
  if (pct <= 0) return `La demanda está repartida por igual entre categorías; ${label.toLowerCase()} encabeza por poco.`;
  return `Los productos de ${label.toLowerCase()} muestran un ${pct} % más de demanda que la media de los candidatos.`;
}
