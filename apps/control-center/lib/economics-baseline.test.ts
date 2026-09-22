import assert from "node:assert/strict";
import { test } from "node:test";
import type { EconomicAnalysis, SupplierQuote } from "./api.ts";
import { buildBaseline } from "./economics-baseline.ts";
import { DEMO_SALE, DEMO_UNIT_COSTS } from "./demo/economics.ts";
import { demoQuotes } from "./demo/sourcing.ts";
import { rankSuppliers } from "./sourcing-view.ts";

const quote: SupplierQuote = {
  id: "q1",
  product_id: "p1",
  supplier_id: "sup-1",
  unit_price: 5,
  moq: 200,
  lead_time_days: 20,
  verified: true,
  reliability_score: 0.9,
  logistics_cost_per_unit: 2,
  total_landed_cost_per_unit: 7,
  data: { name: "Proveedor Real", region: "vietnam" },
};

const analysis: EconomicAnalysis = {
  correlation_id: "c1",
  product_id: "p1",
  supplier_quote_id: "q1",
  sale_price: 24,
  monthly_fixed_costs: 800,
  margin_percent: 0.7,
  recommendation: "GO",
  confidence: 0.8,
  data: { scenarios: { conservative: s(50), base: s(210.4), optimistic: s(400) } },
};

function s(units: number) {
  return { monthly_unit_sales: units, margin_percent: 0.7, monthly_revenue: 0, monthly_profit: 0 };
}

test("buildBaseline: con cotización y análisis reales solo los costes sin backend son demo", () => {
  const b = buildBaseline(quote, analysis);
  assert.equal(b.inputs.salePrice, 24);
  assert.equal(b.inputs.monthlyFixedCosts, 800);
  assert.equal(b.inputs.monthlyOrders, 210);
  assert.equal(b.inputs.supplierCost, 5);
  assert.equal(b.inputs.transport + b.inputs.tariff, 2);
  assert.equal(b.inputs.initialInvestment, DEMO_SALE.firstOrderUnits * 7);
  assert.equal(b.inputs.cac, DEMO_UNIT_COSTS.cac);
  assert.deepEqual(b.supplier, { name: "Proveedor Real", region: "vietnam", verified: true, isDemo: false });
  assert.equal(b.costSources.supplier, "verified");
  assert.equal(b.demoFields.length, 1);
});

test("buildBaseline: sin datos reales todo sale de la demo y se declara", () => {
  const b = buildBaseline(undefined, undefined);
  assert.equal(b.inputs.salePrice, DEMO_SALE.salePrice);
  assert.equal(b.inputs.monthlyOrders, DEMO_SALE.monthlyOrders);
  const first = rankSuppliers(demoQuotes("demo"))[0].quote;
  assert.equal(b.inputs.supplierCost, first.unit_price);
  assert.equal(b.supplier.name, first.data?.name);
  assert.equal(b.supplier.isDemo, true);
  assert.equal(b.costSources.supplier, "third_party");
  assert.equal(b.demoFields.length, 4);
});
