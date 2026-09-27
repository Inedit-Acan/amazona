import type {
  ComparisonProviderSummary,
  Product,
  ProductAlias,
  ResearchCandidate,
  ResearchComparison,
} from "./api.ts";
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
  /** De dónde salen las señales de esta fila (Milestone 34):
   *
   * - `real`: medidas contra una fuente externa.
   * - `mixed`: parte medidas, parte relleno de fixtures.
   * - `simulated`: fixtures del backend.
   * - `demo`: ni siquiera eso — las rellena esta pantalla porque el producto
   *   no se investigó en esta sesión. */
  provenance: SignalProvenance;
  /** Otros nombres que se resolvieron a este producto (Milestone 36). Vacío
   * cuando siempre llegó igual: no hubo nada que resolver. */
  alsoKnownAs: ProductAlias[];
}

export type SignalProvenance = "real" | "mixed" | "simulated" | "demo";

/** Por qué dos nombres son el mismo producto, en palabras (Milestone 36).
 *
 * Se dice en la pantalla porque una fusión que no se ve es indistinguible de un
 * error: quien mira tiene que poder saber que su «air fryer» acabó en el
 * producto «Air fryer», y por qué vía. */
export function identityMethodLabel(method: string): string {
  if (method.startsWith("alias:")) {
    return `alias declarado (catálogo ${method.slice("alias:".length)})`;
  }
  if (method === "normalised") {
    return "misma escritura";
  }
  return method;
}

/** La nota de identidad de una fila, o null si no hay nada que contar. */
export function alsoKnownAsNote(aliases: ProductAlias[]): string | null {
  if (aliases.length === 0) {
    return null;
  }
  const names = aliases.map((entry) => `«${entry.alias}» (${identityMethodLabel(entry.method)})`);
  return `También llegó como ${names.join(", ")}`;
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
      // Sin candidato del backend, lo que se enseña lo rellena esta pantalla:
      // eso es `demo`, y no es lo mismo que un fixture del backend. Un análisis
      // anterior al Milestone 34 no traía procedencia y era de fixtures.
      provenance: !candidate ? "demo" : ((d.provenance as SignalProvenance | undefined) ?? "simulated"),
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
      alsoKnownAs: product.also_known_as ?? [],
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

/** Qué enseña la pantalla, en una línea, para la cabecera (Milestone 34).
 *
 * El orden es de menos a más fiable a propósito: basta con que algo sea de
 * relleno para que la cabecera no pueda decir «real». Decir «real» de un
 * conjunto que es medio inventado es la clase de media verdad que este
 * milestone existe para quitar de en medio. */
export function signalsMode(rows: ResearchRow[]): { label: string; status: "verified" | "mixed" | "demo" } {
  if (rows.length === 0) return { label: "Sin señales", status: "demo" };
  const kinds = new Set(rows.map((row) => row.provenance));
  if (kinds.has("demo")) {
    return { label: "Simulación (señales de demostración)", status: "demo" };
  }
  if (kinds.has("simulated") && kinds.size === 1) {
    return { label: "Simulación (señales de fixtures)", status: "demo" };
  }
  if (kinds.has("simulated") || kinds.has("mixed")) {
    return { label: "Mixto (parte medido, parte relleno)", status: "mixed" };
  }
  return { label: "Real (señales medidas)", status: "verified" };
}

// --- La evidencia real en el gráfico (Milestone 35) ------------------------

export interface InterestSeries {
  key: string;
  label: string;
  color: string;
  points: { x: number; y: number }[];
}

export interface InterestChart {
  series: InterestSeries[];
  /** `real` cuando las series vienen de observaciones medidas; `demo` cuando
   * las rellena esta pantalla. Nunca se mezclan en el mismo gráfico: un
   * gráfico mitad medido y mitad inventado no se puede leer. */
  provenance: "real" | "demo";
  caption: string;
}

/** Suma por periodo las observaciones reales de todas las señales de demanda.
 *
 * Devuelve `null` cuando no hay ninguna: eso no es un cero, es que nadie ha
 * medido todavía, y el gráfico enseñará entonces su serie de demostración
 * diciendo que lo es. */
export function realInterestSeries(candidates: ResearchCandidate[], months: number): InterestSeries[] | null {
  const byProvider = new Map<string, Map<string, number>>();
  for (const candidate of candidates) {
    for (const signal of candidate.data.signals ?? []) {
      if (signal.simulated || !signal.observations?.length || signal.kind !== "demand") continue;
      const periods = byProvider.get(signal.provider) ?? new Map<string, number>();
      for (const observation of signal.observations) {
        periods.set(observation.period, (periods.get(observation.period) ?? 0) + observation.value);
      }
      byProvider.set(signal.provider, periods);
    }
  }
  if (byProvider.size === 0) return null;

  const colors = ["var(--emerald)", "#5aa9e6", "#b57bff", "#f8925c"];
  return [...byProvider.entries()].map(([provider, periods], index) => {
    const ordered = [...periods.entries()].sort(([a], [b]) => a.localeCompare(b)).slice(-months);
    return {
      key: provider,
      label: PROVIDER_LABEL[provider] ?? provider,
      color: colors[index % colors.length],
      points: ordered.map(([, value], x) => ({ x, y: value })),
    };
  });
}

export const PROVIDER_LABEL: Record<string, string> = {
  "wikimedia-pageviews": "Wikipedia (visitas/mes)",
  fixtures: "Fixtures",
};

/** Qué serie enseña el gráfico de interés, y de dónde sale. */
export function interestChart(
  candidates: ResearchCandidate[],
  demo: { key: string; label: string; color: string; series: number[] }[],
  months: number,
): InterestChart {
  const real = realInterestSeries(candidates, months);
  if (real) {
    return {
      series: real,
      provenance: "real",
      caption:
        "Visitas mensuales medidas. Es un proxy de interés: no son ventas ni intención de compra.",
    };
  }
  return {
    series: demo.map((source) => ({
      key: source.key,
      label: source.label,
      color: source.color,
      points: source.series.slice(-months).map((y, x) => ({ x, y })),
    })),
    provenance: "demo",
    caption: "Datos de demostración: todavía no hay observaciones medidas para estos candidatos.",
  };
}

/** Lo que hay que enseñar de una comparación entre proveedores (Milestone 35). */
export interface ComparisonView {
  verdict: string;
  baselineLabel: string;
  candidateLabel: string;
  rows: { label: string; baseline: string; candidate: string }[];
  shared: number;
}

export function comparisonView(comparison: ResearchComparison): ComparisonView {
  const { baseline, candidate } = comparison.summary;
  const coverage = (summary: ComparisonProviderSummary, kind: string) =>
    String(summary.coverage[kind] ?? 0);
  return {
    verdict: comparison.summary.verdict,
    baselineLabel: PROVIDER_LABEL[baseline.provider] ?? baseline.provider,
    candidateLabel: PROVIDER_LABEL[candidate.provider] ?? candidate.provider,
    shared: comparison.summary.shared.length,
    rows: [
      { label: "Candidatos", baseline: String(baseline.candidates), candidate: String(candidate.candidates) },
      { label: "Con demanda", baseline: coverage(baseline, "demand"), candidate: coverage(candidate, "demand") },
      {
        label: "Con competencia",
        baseline: coverage(baseline, "competition"),
        candidate: coverage(candidate, "competition"),
      },
      { label: "Puntuables", baseline: String(baseline.scorable), candidate: String(candidate.scorable) },
      {
        label: "Confianza media",
        baseline: baseline.mean_confidence === null ? "—" : baseline.mean_confidence.toFixed(2),
        candidate: candidate.mean_confidence === null ? "—" : candidate.mean_confidence.toFixed(2),
      },
      {
        label: "Señales medidas",
        baseline: String(baseline.measured_signals),
        candidate: String(candidate.measured_signals),
      },
    ],
  };
}
