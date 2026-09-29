import assert from "node:assert/strict";
import { test } from "node:test";
import type { MirrorCost } from "./economics-mirror.ts";
import { evaluateMirror, totalCost } from "./economics-mirror.ts";
import FIXTURES from "./economics-parity-fixtures.json" with { type: "json" };

// El backend es la implementación canónica. Estos fixtures salen de ejecutarlo
// (`app/economics/unit_economics.py`), y este fichero falla el día que el
// espejo del navegador deje de coincidir con él.

function costsFrom(inputs: (typeof FIXTURES)[number]["inputs"]): MirrorCost[] {
  return [
    { status: "known", amount: Number(inputs.product) },
    { status: "known", amount: Number(inputs.logistics) },
    // El arancel va dentro de la logística: no suma, y no por eso es cero.
    { status: "included_in_another", amount: null },
    inputs.channel === null
      ? { status: "not_applicable", amount: null }
      : { status: "known", amount: Number(inputs.channel) },
    { status: "known", amount: Number(inputs.payment) },
    { status: "unknown_optional", amount: null },
  ];
}

for (const fixture of FIXTURES) {
  test(`paridad con el backend: ${fixture.name}`, () => {
    const result = evaluateMirror({
      salePrice: Number(fixture.inputs.salePrice),
      costs: costsFrom(fixture.inputs),
      unitsPerOrder: fixture.inputs.unitsPerOrder,
      expectedMonthlyOrders: fixture.inputs.expectedMonthlyOrders,
      monthlyFixedCosts: Number(fixture.inputs.monthlyFixedCosts),
    });

    // A dos decimales: es lo que la pantalla enseña, y JavaScript no tiene
    // decimales exactos sin una biblioteca.
    const round = (value: number) => Math.round(value * 100) / 100;
    const expected = (value: string) => Math.round(Number(value) * 100) / 100;

    assert.equal(round(result.marginPerUnit), expected(fixture.expected.marginPerUnit));
    assert.equal(round(result.marginPerOrder!), expected(fixture.expected.marginPerOrder));
    assert.equal(
      round(result.allocatedFixedCostPerOrder!),
      expected(fixture.expected.allocatedFixedCostPerOrder),
    );
    assert.equal(round(result.maxBreakevenCac!), expected(fixture.expected.maxBreakevenCac));
  });
}

test("solo los costes conocidos entran en la suma", () => {
  const costs: MirrorCost[] = [
    { status: "known", amount: 4 },
    { status: "included_in_another", amount: null },
    { status: "not_applicable", amount: null },
    { status: "unknown_required", amount: null },
    { status: "unknown_optional", amount: null },
  ];

  assert.equal(totalCost(costs), 4);
});

test("sin unidades por pedido no hay margen por pedido ni techo de CAC", () => {
  const result = evaluateMirror({
    salePrice: 20,
    costs: [{ status: "known", amount: 6 }],
    unitsPerOrder: null,
    expectedMonthlyOrders: 300,
    monthlyFixedCosts: 500,
  });

  assert.equal(result.marginPerUnit, 14);
  assert.equal(result.marginPerOrder, null);
  assert.equal(result.maxBreakevenCac, null);
  assert.ok(result.missingInputs.includes("units_per_order"));
});

test("sin pedidos esperados el margen sigue en pie y el techo no", () => {
  const result = evaluateMirror({
    salePrice: 20,
    costs: [{ status: "known", amount: 6 }],
    unitsPerOrder: 1,
    expectedMonthlyOrders: null,
    monthlyFixedCosts: 500,
  });

  assert.equal(result.marginPerOrder, 14);
  assert.equal(result.breakevenCacBeforeFixedCosts, 14);
  assert.equal(result.allocatedFixedCostPerOrder, null);
  assert.equal(result.maxBreakevenCac, null);
  assert.ok(result.missingInputs.includes("expected_monthly_orders"));
});

test("un techo negativo se conserva negativo", () => {
  const result = evaluateMirror({
    salePrice: 5,
    costs: [{ status: "known", amount: 6 }],
    unitsPerOrder: 1,
    expectedMonthlyOrders: 300,
    monthlyFixedCosts: 500,
  });

  assert.ok(result.maxBreakevenCac !== null && result.maxBreakevenCac < 0);
});

test("más unidades por pedido suben el techo sin tocar el margen por unidad", () => {
  const base = { salePrice: 20, costs: [{ status: "known" as const, amount: 6 }], monthlyFixedCosts: 500 };
  const one = evaluateMirror({ ...base, unitsPerOrder: 1, expectedMonthlyOrders: 300 });
  const three = evaluateMirror({ ...base, unitsPerOrder: 3, expectedMonthlyOrders: 100 });

  assert.equal(one.marginPerUnit, three.marginPerUnit);
  assert.ok(three.maxBreakevenCac! > one.maxBreakevenCac!);
});
