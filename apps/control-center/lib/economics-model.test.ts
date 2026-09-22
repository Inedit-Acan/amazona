import assert from "node:assert/strict";
import { test } from "node:test";
import {
  costLines,
  economicRisk,
  evaluate,
  profitCurve,
  scenarios,
  sensitivity,
  verdict,
  viabilityItems,
  type EconomicsInputs,
} from "./economics-model.ts";

const base: EconomicsInputs = {
  salePrice: 29.9,
  supplierCost: 8.4,
  transport: 2.1,
  tariff: 0.36,
  fulfillment: 0.75,
  paymentFeePct: 2.9,
  returnsPct: 4,
  cac: 3.2,
  otherCosts: 0.4,
  conversionPct: 2.8,
  monthlyOrders: 300,
  monthlyFixedCosts: 1000,
  initialInvestment: 6000,
};

const close = (a: number, b: number, eps = 0.01) => assert.ok(Math.abs(a - b) < eps, `${a} ≈ ${b}`);

test("costLines: los porcentajes se aplican sobre el precio de venta", () => {
  const lines = costLines(base);
  close(lines.find((l) => l.key === "payment")!.amount, 0.8671, 0.0001);
  close(lines.find((l) => l.key === "returns")!.amount, 1.196, 0.0001);
  assert.equal(lines.find((l) => l.key === "payment")!.label, "Pasarela de pago (2,9 %)");
});

test("evaluate: contribución, margen, beneficio, break-even y recuperación coherentes", () => {
  const r = evaluate(base);
  close(r.unitCost, 17.2731);
  close(r.contribution, 12.6269);
  close(r.contributionMargin, 0.4223, 0.001);
  close(r.monthlyRevenue, 8970);
  close(r.monthlyProfit, 2788.07);
  assert.equal(r.breakEvenUnits, 80);
  close(r.breakEvenRevenue!, 80 * 29.9);
  close(r.paybackMonths!, 6000 / 2788.07);
});

test("evaluate: con el CAC máximo y el precio mínimo el beneficio es cero", () => {
  const r = evaluate(base);
  close(evaluate({ ...base, cac: r.maxCac }).monthlyProfit, 0);
  close(evaluate({ ...base, salePrice: r.minViablePrice }).monthlyProfit, 0);
});

test("evaluate: si cada unidad pierde dinero no hay break-even ni recuperación", () => {
  const r = evaluate({ ...base, salePrice: 10 });
  assert.equal(r.breakEvenUnits, null);
  assert.equal(r.breakEvenRevenue, null);
  assert.equal(r.paybackMonths, null);
});

test("scenarios: conservador → optimista varían precio y volumen", () => {
  const [c, b, o] = scenarios(base);
  assert.deepEqual([c.key, b.key, o.key], ["conservative", "base", "optimistic"]);
  assert.equal(c.inputs.salePrice, 27.9);
  assert.equal(c.inputs.monthlyOrders, 120);
  assert.equal(b.inputs.salePrice, 29.9);
  assert.equal(o.inputs.salePrice, 32.89);
  assert.equal(o.inputs.monthlyOrders, 600);
  assert.ok(c.result.monthlyProfit < b.result.monthlyProfit && b.result.monthlyProfit < o.result.monthlyProfit);
});

test("profitCurve: con 0 pedidos se pierden los costes fijos", () => {
  const [first, second] = profitCurve(base, [0, 300]);
  assert.equal(first.y, -1000);
  close(second.y, 2788.07);
});

test("sensitivity: ordenada de mayor a menor impacto, con nivel por umbral", () => {
  const items = sensitivity(base);
  assert.equal(items.length, 6);
  for (let k = 1; k < items.length; k++) assert.ok(items[k - 1].impact >= items[k].impact);
  for (const item of items) {
    assert.equal(item.level, item.impact >= 0.3 ? "Alto" : item.impact >= 0.12 ? "Medio" : "Bajo");
  }
  assert.equal(items[0].key, "conversion");
});

test("economicRisk, viabilityItems y verdict: bajo con margen sano; alto si se pierde dinero", () => {
  assert.equal(economicRisk(base).level, "Bajo");
  assert.deepEqual(
    viabilityItems(base).map((v) => v.value),
    ["Alta", "Alta", "Medio", "Bajo"],
  );
  assert.equal(verdict(base).tone, "ok");
  const losing = { ...base, salePrice: 16 };
  assert.equal(economicRisk(losing).level, "Alto");
  assert.equal(verdict(losing).tone, "bad");
});
