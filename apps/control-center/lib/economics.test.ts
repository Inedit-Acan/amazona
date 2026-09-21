import { test } from "node:test";
import assert from "node:assert/strict";
import {
  RECOMMENDATION_LABEL,
  dedupeQuotesBySupplier,
  scenarioList,
  unitContribution,
  viabilityStatement,
  type Recommendation,
} from "./economics.ts";
import { formatAmount, formatInteger, formatPercent } from "./format.ts";
import type { EconomicScenario, SupplierQuote } from "./api.ts";

function scenario(profit: number, units = 100): EconomicScenario {
  return { monthly_unit_sales: units, margin_percent: 0.5, monthly_revenue: units * 20, monthly_profit: profit };
}

function quote(id: string, supplierId: string, landed: number): SupplierQuote {
  return {
    id,
    product_id: "p",
    supplier_id: supplierId,
    unit_price: landed - 1,
    moq: 100,
    lead_time_days: 10,
    verified: true,
    reliability_score: 0.9,
    logistics_cost_per_unit: 1,
    total_landed_cost_per_unit: landed,
    data: null,
  };
}

test("scenarioList devuelve siempre conservador → base → optimista, aunque el backend los envíe desordenados", () => {
  const list = scenarioList({
    data: { scenarios: { optimistic: scenario(300), conservative: scenario(50), base: scenario(150) } },
  });
  assert.deepEqual(list.map((s) => s.key), ["conservative", "base", "optimistic"]);
  assert.deepEqual(list.map((s) => s.label), ["Conservador", "Base", "Optimista"]);
});

test("scenarioList tolera datos ausentes o escenarios parciales", () => {
  assert.deepEqual(scenarioList({ data: null }), []);
  assert.deepEqual(scenarioList({ data: {} }), []);
  const partial = scenarioList({ data: { scenarios: { base: scenario(10) } as never } });
  assert.deepEqual(partial.map((s) => s.key), ["base"]);
});

test("unitContribution es precio − coste entregado (puede ser negativa)", () => {
  assert.equal(unitContribution(20, 5.4), 14.6);
  assert.ok(unitContribution(4, 5.4) < 0);
});

test("nunca se afirma «rentable» sin «bajo estas hipótesis» (spec §7.10)", () => {
  for (const rec of ["GO", "REVIEW", "NO_GO"] as Recommendation[]) {
    const { title } = viabilityStatement(rec);
    if (/rentable/i.test(title)) {
      assert.match(title, /bajo estas hipótesis/i);
    }
  }
  assert.equal(viabilityStatement("GO").tone, "ok");
  assert.equal(viabilityStatement("REVIEW").tone, "warn");
  assert.equal(viabilityStatement("NO_GO").tone, "bad");
});

test("hay una etiqueta en español para cada recomendación", () => {
  assert.deepEqual(Object.keys(RECOMMENDATION_LABEL).sort(), ["GO", "NO_GO", "REVIEW"]);
});

test("dedupeQuotesBySupplier deja una cotización por proveedor, la más barata", () => {
  const result = dedupeQuotesBySupplier([
    quote("a2", "s1", 6),
    quote("a1", "s1", 5),
    quote("b1", "s2", 8),
  ]);
  assert.deepEqual(result.map((q) => q.id), ["a1", "b1"]);
});

test("dedupeQuotesBySupplier conserva la cotización pedida por URL aunque no sea la más barata", () => {
  const result = dedupeQuotesBySupplier([quote("a1", "s1", 5), quote("a2", "s1", 6)], "a2");
  assert.deepEqual(result.map((q) => q.id), ["a2"]);
});

test("formatos: importes sin divisa, enteros y porcentajes en es-ES", () => {
  assert.equal(formatAmount(1234.5), "1.234,50");
  assert.equal(formatInteger(2180.4), "2.180");
  assert.equal(formatPercent(0.578), "57,8 %");
  assert.equal(formatPercent(0.5, 0), "50 %");
});
