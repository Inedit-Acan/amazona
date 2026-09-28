import assert from "node:assert/strict";
import { test } from "node:test";
import type { Product, ResearchCandidate } from "./api.ts";
import {
  alsoKnownAsNote,
  buildRows,
  scoringWithheldNote,
  comparisonView,
  demandLevel,
  identityMethodLabel,
  interestChart,
  opportunityScore,
  radarAverage,
  realInterestSeries,
  riskLevel,
  signalsMode,
  topInsight,
} from "./research-view.ts";

const product = (id: string, category = "electronics"): Product => ({
  id,
  name: `Producto ${id}`,
  category,
  status: "CANDIDATE",
  created_by: "agent",
  source: "research",
});

const candidate = (productId: string, demand: number, competition: string): ResearchCandidate => ({
  product_id: productId,
  name: `Producto ${productId}`,
  category: "electronics",
  opportunity_score: 0.5,
  confidence: 0.8,
  data: {
    demand_signal: demand,
    competition_level: competition,
    future_outlook_signal: 0.7,
    regulatory_risk_signal: 0.2,
    scalability_signal: 0.8,
    niche_rationale: "real",
  },
});

test("opportunityScore: media ponderada de las cinco señales", () => {
  assert.equal(opportunityScore({ demand: 1, competitionFavorability: 1, future: 1, regulatoryRisk: 0, scalability: 1 }), 100);
  assert.equal(opportunityScore({ demand: 0, competitionFavorability: 0, future: 0, regulatoryRisk: 1, scalability: 0 }), 0);
  assert.equal(opportunityScore({ demand: 0.82, competitionFavorability: 0.6, future: 0.78, regulatoryRisk: 0.35, scalability: 0.75 }), 74);
});

test("demandLevel y riskLevel por umbrales", () => {
  assert.deepEqual([demandLevel(0.8), demandLevel(0.6), demandLevel(0.3)], ["Alta", "Media", "Baja"]);
  assert.equal(riskLevel(0.2, "low"), "Bajo");
  assert.equal(riskLevel(0.3, "medium"), "Medio");
  assert.equal(riskLevel(0.5, "high"), "Alto");
});

test("buildRows: las señales reales sustituyen a las de demostración y se ordena por score", () => {
  const rows = buildRows([product("a"), product("b")], [candidate("b", 0.9, "low")]);
  const b = rows.find((r) => r.productId === "b")!;
  assert.equal(b.isDemo, false);
  assert.equal(b.demand, "Alta");
  assert.equal(b.competition, "Baja");
  assert.equal(b.rationale, "real");
  assert.equal(rows.find((r) => r.productId === "a")!.isDemo, true);
  assert.ok(rows[0].score >= rows[1].score);
});

test("buildRows: los valores de demostración son estables para el mismo producto", () => {
  const [first] = buildRows([product("x")], []);
  const [again] = buildRows([product("x")], []);
  assert.deepEqual(first, again);
  assert.equal(first.trend.length, 12);
  assert.equal(first.margin[1] - first.margin[0], 15);
});

test("radarAverage y topInsight", () => {
  const rows = buildRows([product("a"), product("b", "home")], [candidate("a", 0.9, "low"), { ...candidate("b", 0.3, "high"), category: "home" }]);
  const avg = radarAverage(rows);
  assert.ok(Math.abs(avg.demand - 0.6) < 1e-9);
  assert.match(topInsight(rows)!, /electrónica muestran un 50 % más de demanda/);
  assert.equal(topInsight(rows.slice(0, 1)), null);
  assert.match(topInsight(buildRows([product("c", "home"), product("d", "home")], []))!, /Todos los candidatos actuales son de hogar/);
});


// --- Procedencia de las señales (Milestone 34) -----------------------------

function candidateFor(productId: string, data: Record<string, unknown>) {
  return {
    product_id: productId,
    name: "Candidato",
    category: "home",
    opportunity_score: 0.5,
    confidence: 0.85,
    data,
  };
}

const PRODUCT = {
  id: "p-1",
  name: "Candidato",
  category: "home",
  status: "CANDIDATE",
  source: "research",
  created_by: "agent",
  created_at: "2026-09-26T10:00:00Z",
} as unknown as Parameters<typeof buildRows>[0][number];

test("una fila sin candidato del backend es de demostración, no un fixture", () => {
  const [row] = buildRows([PRODUCT], []);

  assert.equal(row.provenance, "demo");
});

test("un análisis anterior al Milestone 34 se lee como fixture, no como real", () => {
  const [row] = buildRows([PRODUCT], [candidateFor("p-1", { demand_signal: 0.7, competition_level: "low" })]);

  assert.equal(row.provenance, "simulated");
});

test("la procedencia del backend se respeta tal cual", () => {
  const [real] = buildRows([PRODUCT], [candidateFor("p-1", { provenance: "real", demand_signal: 0.7 })]);
  const [mixed] = buildRows([PRODUCT], [candidateFor("p-1", { provenance: "mixed", demand_signal: 0.7 })]);

  assert.equal(real.provenance, "real");
  assert.equal(mixed.provenance, "mixed");
});

test("signalsMode dice «real» solo cuando todo lo es", () => {
  const rows = buildRows([PRODUCT], [candidateFor("p-1", { provenance: "real", demand_signal: 0.7 })]);

  assert.deepEqual(signalsMode(rows), { label: "Real (señales medidas)", status: "verified" });
});

test("basta una señal de relleno para que la cabecera no pueda decir «real»", () => {
  const rows = buildRows([PRODUCT], [candidateFor("p-1", { provenance: "mixed", demand_signal: 0.7 })]);

  assert.equal(signalsMode(rows).status, "mixed");
  assert.match(signalsMode(rows).label, /parte medido/);
});

test("todo fixtures se sigue llamando simulación", () => {
  const rows = buildRows([PRODUCT], [candidateFor("p-1", { provenance: "simulated", demand_signal: 0.7 })]);

  assert.deepEqual(signalsMode(rows), { label: "Simulación (señales de fixtures)", status: "demo" });
});

test("si algo lo rellena la propia pantalla, eso manda sobre lo demás", () => {
  const second = { ...PRODUCT, id: "p-2" };
  const rows = buildRows(
    [PRODUCT, second],
    [candidateFor("p-1", { provenance: "real", demand_signal: 0.7 })],
  );

  assert.equal(signalsMode(rows).status, "demo");
});

test("sin filas no se dice nada de nada", () => {
  assert.deepEqual(signalsMode([]), { label: "Sin señales", status: "demo" });
});


// --- La evidencia real en el gráfico (Milestone 35) ------------------------

const DEMO_SOURCES = [
  { key: "google", label: "Google", color: "#0f0", series: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12] },
  { key: "social", label: "Redes", color: "#00f", series: [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13] },
];

function measuredCandidate(
  productId: string,
  observations: { period: string; value: number }[],
  over: Record<string, unknown> = {},
) {
  return {
    product_id: productId,
    name: "Air fryer",
    category: "home",
    opportunity_score: null,
    confidence: 0.6,
    data: {
      provenance: "real",
      signals: [
        {
          kind: "demand",
          value: 0.62,
          confidence: 0.6,
          provider: "wikimedia-pageviews",
          source: "wikimedia.org",
          query: "Air fryer",
          market: "us",
          observed_at: "2026-09-01T00:00:00Z",
          method: "PROXY FOR INTEREST",
          raw_reference: "https://wikimedia.org/…",
          basis: "measured",
          observations,
        },
      ],
      ...over,
    },
  } as unknown as Parameters<typeof interestChart>[0][number];
}

test("sin observaciones medidas el gráfico enseña la demo y lo dice", () => {
  const chart = interestChart([], DEMO_SOURCES, 12);

  assert.equal(chart.provenance, "demo");
  assert.equal(chart.series.length, 2);
  assert.match(chart.caption, /demostración/);
});

test("con observaciones medidas el gráfico las usa y avisa de que es un proxy", () => {
  const chart = interestChart(
    [measuredCandidate("p-1", [{ period: "2026-07", value: 100 }, { period: "2026-08", value: 140 }])],
    DEMO_SOURCES,
    12,
  );

  assert.equal(chart.provenance, "real");
  assert.equal(chart.series.length, 1);
  assert.equal(chart.series[0].label, "Wikipedia (visitas/mes)");
  assert.deepEqual(chart.series[0].points, [{ x: 0, y: 100 }, { x: 1, y: 140 }]);
  assert.match(chart.caption, /no son ventas/);
});

test("las observaciones de varios candidatos se suman por periodo", () => {
  const chart = interestChart(
    [
      measuredCandidate("p-1", [{ period: "2026-08", value: 100 }]),
      measuredCandidate("p-2", [{ period: "2026-08", value: 40 }]),
    ],
    DEMO_SOURCES,
    12,
  );

  assert.deepEqual(chart.series[0].points, [{ x: 0, y: 140 }]);
});

test("una señal simulada nunca entra en la serie real", () => {
  const candidate = measuredCandidate("p-1", [{ period: "2026-08", value: 100 }]);
  candidate.data.signals![0].basis = "simulated";

  assert.equal(realInterestSeries([candidate], 12), null);
  assert.equal(interestChart([candidate], DEMO_SOURCES, 12).provenance, "demo");
});

test("una estimación tampoco entra: viene del mundo y no es una observación", () => {
  const candidate = measuredCandidate("p-1", [{ period: "2026-08", value: 100 }]);
  candidate.data.signals![0].basis = "estimated";

  assert.equal(realInterestSeries([candidate], 12), null);
});

test("la serie respeta el periodo elegido", () => {
  const observations = Array.from({ length: 12 }, (_, i) => ({
    period: `2026-${String(i + 1).padStart(2, "0")}`,
    value: i + 1,
  }));

  const chart = interestChart([measuredCandidate("p-1", observations)], DEMO_SOURCES, 3);

  assert.equal(chart.series[0].points.length, 3);
  assert.deepEqual(chart.series[0].points.at(-1), { x: 2, y: 12 });
});

// --- El informe de contraste ------------------------------------------------

function comparison(over: Record<string, unknown> = {}) {
  return {
    id: "cmp-1",
    category: "home",
    market: "us",
    baseline_provider: "fixtures",
    candidate_provider: "wikimedia-pageviews",
    correlation_id: "cid-1",
    created_at: "2026-09-27T10:00:00Z",
    summary: {
      category: "home",
      market: "us",
      baseline: {
        provider: "fixtures",
        candidates: 4,
        coverage: { demand: 4, competition: 4 },
        scorable: 4,
        mean_confidence: 0.3,
        measured_signals: 0,
        simulated_signals: 20,
      },
      candidate: {
        provider: "wikimedia-pageviews",
        candidates: 2,
        coverage: { demand: 2 },
        scorable: 0,
        mean_confidence: 0.65,
        measured_signals: 4,
        simulated_signals: 0,
      },
      shared: [],
      only_baseline: ["silicone kitchen organizer"],
      only_candidate: ["air fryer"],
      deltas: [],
      verdict: "Ningún candidato en común",
      ...over,
    },
  } as unknown as Parameters<typeof comparisonView>[0];
}

test("el informe traduce los proveedores y sus recuentos", () => {
  const view = comparisonView(comparison());

  assert.equal(view.baselineLabel, "Fixtures");
  assert.equal(view.candidateLabel, "Wikipedia (visitas/mes)");
  assert.equal(view.verdict, "Ningún candidato en común");
  assert.equal(view.shared, 0);
});

test("una cobertura ausente se enseña como cero candidatos, no como un hueco", () => {
  const view = comparisonView(comparison());

  const competition = view.rows.find((row) => row.label === "Con competencia");
  assert.equal(competition?.baseline, "4");
  assert.equal(competition?.candidate, "0");
});

test("sin confianza no se inventa un cero", () => {
  const view = comparisonView(
    comparison({
      candidate: {
        provider: "wikimedia-pageviews",
        candidates: 0,
        coverage: {},
        scorable: 0,
        mean_confidence: null,
        measured_signals: 0,
        simulated_signals: 0,
      },
    }),
  );

  assert.equal(view.rows.find((row) => row.label === "Confianza media")?.candidate, "—");
});

// --- Identidad de los candidatos (Milestone 36) ----------------------------

test("alsoKnownAsNote: sin otros nombres no hay nota que dar", () => {
  assert.equal(alsoKnownAsNote([]), null);
});

test("alsoKnownAsNote: dice el nombre y por qué vía se unió", () => {
  const note = alsoKnownAsNote([
    { alias: "airfryer", method: "alias:v1" },
    { alias: "AIR FRYER", method: "normalised" },
  ]);

  assert.equal(
    note,
    "También llegó como «airfryer» (alias declarado (catálogo v1)), «AIR FRYER» (misma escritura)",
  );
});

test("identityMethodLabel: un método que no conocemos se enseña tal cual", () => {
  assert.equal(identityMethodLabel("normalised"), "misma escritura");
  assert.equal(identityMethodLabel("alias:v2"), "alias declarado (catálogo v2)");
  assert.equal(identityMethodLabel("algo-nuevo"), "algo-nuevo");
});

test("buildRows: los otros nombres del producto llegan a la fila", () => {
  const withAliases: Product = {
    ...product("p-alias"),
    also_known_as: [{ alias: "airfryer", method: "alias:v1" }],
  };

  const [row] = buildRows([withAliases], []);

  assert.deepEqual(row.alsoKnownAs, [{ alias: "airfryer", method: "alias:v1" }]);
});

test("buildRows: un producto sin identidad resuelta no inventa nombres", () => {
  const [row] = buildRows([product("p-plain")], []);

  assert.deepEqual(row.alsoKnownAs, []);
});

// --- Licencias que impiden puntuar (Milestone 37) ---------------------------

test("scoringWithheldNote: sin nada retenido no hay nota", () => {
  assert.equal(scoringWithheldNote([]), null);
});

test("scoringWithheldNote: dice quién impide puntuar, no que falte el dato", () => {
  assert.equal(
    scoringWithheldNote(["ebay-browse"]),
    "Sin score: la licencia de ebay-browse no permite puntuar con sus señales",
  );
});

test("buildRows: lo retenido por licencia llega a la fila", () => {
  const [row] = buildRows(
    [PRODUCT],
    [candidateFor("p-1", { scoring_withheld_from: ["ebay-browse"], demand_signal: 0.7 })],
  );

  assert.deepEqual(row.scoringWithheldFrom, ["ebay-browse"]);
});

test("buildRows: lo normal es que no haya nada retenido", () => {
  const [row] = buildRows([PRODUCT], [candidateFor("p-1", { demand_signal: 0.7 })]);

  assert.deepEqual(row.scoringWithheldFrom, []);
});

test("signalsMode: un conjunto estimado no se presenta como real ni como simulación", () => {
  const rows = buildRows([PRODUCT], [candidateFor("p-1", { provenance: "estimated", demand_signal: 0.7 })]);

  const mode = signalsMode(rows);
  assert.equal(mode.status, "mixed");
  assert.match(mode.label, /Estimado/);
});

// --- Canal del score (Milestone 38) -----------------------------------------

test("buildRows: para qué canal se puntuó llega a la fila", () => {
  const [row] = buildRows(
    [PRODUCT],
    [candidateFor("p-1", { channel: "own_web", demand_signal: 0.7 })],
  );

  assert.equal(row.scoredForChannel, "own_web");
});

test("buildRows: sin canal la fila dice null, no una cadena vacía", () => {
  const [row] = buildRows([PRODUCT], [candidateFor("p-1", { demand_signal: 0.7 })]);

  assert.equal(row.scoredForChannel, null);
  assert.deepEqual(row.scoringWrongChannel, []);
});

test("buildRows: lo medido en otro canal llega a la fila", () => {
  const [row] = buildRows(
    [PRODUCT],
    [candidateFor("p-1", { scoring_wrong_channel: ["marketplace:ebay"], demand_signal: 0.7 })],
  );

  assert.deepEqual(row.scoringWrongChannel, ["marketplace:ebay"]);
});
