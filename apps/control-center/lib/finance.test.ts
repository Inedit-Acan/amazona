import assert from "node:assert/strict";
import { test } from "node:test";
import { budgetBreakdown, portfolioRows } from "./finance.ts";

const totals = (limit: number, reserved: number, committed: number, spent: number) => ({
  total_budget_hard_limit: limit,
  total_reserved: reserved,
  total_committed: committed,
  total_spent: spent,
});

test("budgetBreakdown: disponible = límite - (reservado + comprometido + gastado) y uso sobre el límite", () => {
  const b = budgetBreakdown(totals(1000, 100, 200, 300));
  assert.equal(b.available, 400);
  assert.equal(b.utilization, 0.6);
  assert.equal(b.overLimit, false);
});

test("budgetBreakdown: sin límite no hay uso y pasarse del límite no da disponible negativo", () => {
  const none = budgetBreakdown(totals(0, 0, 0, 0));
  assert.equal(none.utilization, null);
  assert.equal(none.available, 0);
  assert.equal(none.overLimit, false);
  const over = budgetBreakdown(totals(100, 60, 60, 0));
  assert.equal(over.available, 0);
  assert.equal(over.overLimit, true);
  assert.equal(over.utilization, 1.2);
});

const analysis = (profit: number | null, recommendation: "GO" | "REVIEW" | "NO_GO" = "GO", price = 20) => ({
  sale_price: price,
  margin_percent: 0.5,
  recommendation,
  data: profit === null ? null : { scenarios: { base: { monthly_profit: profit } } },
});
// El tipo completo del escenario no importa para esta prueba.
const cast = <T,>(value: unknown) => value as T;

test("portfolioRows toma la última decisión de cada producto y ordena por beneficio base", () => {
  const products = [
    { id: "a", name: "Alfa", category: "home" },
    { id: "b", name: "Beta", category: "home" },
    { id: "c", name: "Gamma", category: "home" },
    { id: "d", name: "Sin análisis", category: "home" },
  ];
  const rows = portfolioRows(
    products,
    cast<Parameters<typeof portfolioRows>[1]>({
      a: [analysis(100, "GO", 30), analysis(9999)],
      b: [analysis(-50, "NO_GO")],
      c: [analysis(null, "REVIEW")],
    }),
  );
  assert.deepEqual(
    rows.map((r) => [r.name, r.monthlyProfit, r.recommendation]),
    [
      ["Alfa", 100, "GO"],
      ["Beta", -50, "NO_GO"],
      ["Gamma", null, "REVIEW"],
    ],
  );
  assert.equal(rows[0].salePrice, 30);
});
