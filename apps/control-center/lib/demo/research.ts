// DATOS DE DEMOSTRACIÓN — pantalla de Investigación.
//
// Valores inventados (con permiso del propietario, 22-09-2026) para que el
// panel se vea como el mockup mientras el backend no los proporciona. Son
// deterministas por producto (mismo producto → mismos valores al recargar).
// Se usan solo cuando no hay dato real. Sustituir cuando existan los
// endpoints (docs/design/AMAZONA_estado_paneles_rediseno.md, sección de
// Investigación).

/** Hash estable 0..1 de un texto (FNV-1a), con una sal para sacar varios valores. */
export function demoRandom(seed: string, salt: string): number {
  let h = 0x811c9dc5;
  for (const ch of `${seed}:${salt}`) {
    h ^= ch.charCodeAt(0);
    h = Math.imul(h, 0x01000193);
  }
  return (h >>> 0) / 0xffffffff;
}

/** Señales del agente cuando el producto no tiene investigación en esta sesión. */
export function demoSignals(productId: string) {
  const r = (salt: string, min: number, max: number) => min + demoRandom(productId, salt) * (max - min);
  const competition = demoRandom(productId, "competition");
  return {
    demand_signal: r("demand", 0.45, 0.9),
    competition_level: competition < 0.35 ? "low" : competition < 0.75 ? "medium" : "high",
    future_outlook_signal: r("future", 0.4, 0.85),
    regulatory_risk_signal: r("regulatory", 0.2, 0.55),
    scalability_signal: r("scalability", 0.45, 0.85),
    niche_rationale: "Señales de demostración: lanza «Analizar mercado» para obtener las del agente.",
  };
}

/** Crecimiento de interés a 12 meses y su serie mensual (índice 0–100). */
export function demoTrend(productId: string, demand: number): { growth: number; series: number[] } {
  const growth = Math.round(10 + demand * 45 + demoRandom(productId, "growth") * 12);
  const start = 40 + demoRandom(productId, "start") * 15;
  const series = Array.from({ length: 12 }, (_, k) => {
    const noise = (demoRandom(productId, `m${k}`) - 0.5) * 8;
    return Math.round(start * (1 + (growth / 100) * (k / 11)) + noise);
  });
  return { growth, series };
}

/** Margen preliminar como rango (%). */
export function demoMarginRange(productId: string, competitionFavorability: number): [number, number] {
  const low = Math.round((25 + competitionFavorability * 25 + demoRandom(productId, "margin") * 5) / 5) * 5;
  return [low, low + 15];
}

export const DEMO_SUBCATEGORY: Record<string, string[]> = {
  electronics: ["Audio", "Accesorios móviles", "Hogar inteligente"],
  home: ["Cocina", "Organización", "Climatización"],
  accessories: ["Viaje", "Deporte", "Escritorio"],
};

export const DEMO_INSIGHTS: Record<string, string[]> = {
  electronics: ["Crecimiento sostenido", "Tendencia fitness y salud", "Oportunidad en nichos", "Baja saturación en UE"],
  home: ["Mayor conciencia de salud", "Tendencia en entornos urbanos", "Interés estable todo el año", "Buen potencial de marca propia"],
  accessories: ["Tendencia wellness", "Potencial de regalo", "Demanda estacional (Q4)", "Diferenciación por tecnología"],
};

/** Interés relativo por fuente, últimos 12 meses (índice 0–100). */
export const DEMO_INTEREST_BY_SOURCE: { key: string; label: string; color: string; series: number[] }[] = [
  { key: "google", label: "Google", color: "var(--emerald)", series: [42, 45, 44, 50, 53, 55, 58, 57, 63, 68, 74, 86] },
  { key: "marketplaces", label: "Marketplaces", color: "#5aa9e6", series: [35, 37, 40, 41, 45, 44, 49, 52, 55, 58, 63, 72] },
  { key: "ecommerce", label: "E-commerce", color: "#b57bff", series: [28, 30, 29, 33, 35, 38, 37, 41, 44, 47, 50, 58] },
  { key: "social", label: "Redes sociales", color: "#f8925c", series: [20, 22, 25, 24, 27, 30, 29, 33, 35, 38, 40, 45] },
];

export const DEMO_FILTERS = {
  markets: ["España + UE", "Unión Europea", "Estados Unidos", "México"],
  periods: [
    { months: 12, label: "12 meses" },
    { months: 6, label: "6 meses" },
    { months: 3, label: "3 meses" },
  ],
  businessModels: ["Sin stock (Dropshipping)", "Stock propio", "Marketplace (FBA)"],
};
