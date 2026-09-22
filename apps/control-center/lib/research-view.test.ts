import assert from "node:assert/strict";
import { test } from "node:test";
import type { Product, ResearchCandidate } from "./api.ts";
import { buildRows, demandLevel, opportunityScore, radarAverage, riskLevel, topInsight } from "./research-view.ts";

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
