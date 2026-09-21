import { test } from "node:test";
import assert from "node:assert/strict";
import {
  applyFilters,
  averageRadarValues,
  distinctionsFor,
  sortByLandedCost,
  supplierRadarValues,
} from "./sourcing.ts";
import { toCsv } from "./csv.ts";
import type { SupplierQuote } from "./api.ts";

function quote(overrides: Partial<SupplierQuote> & { id: string }): SupplierQuote {
  return {
    product_id: "p1",
    supplier_id: `s-${overrides.id}`,
    unit_price: 4,
    moq: 500,
    lead_time_days: 20,
    verified: true,
    reliability_score: 0.8,
    logistics_cost_per_unit: 1,
    total_landed_cost_per_unit: 5,
    data: null,
    ...overrides,
  };
}

const cheap = quote({ id: "a", unit_price: 2, logistics_cost_per_unit: 0.5, total_landed_cost_per_unit: 2.5, moq: 1000, lead_time_days: 30, reliability_score: 0.7 });
const fast = quote({ id: "b", unit_price: 4, logistics_cost_per_unit: 1, total_landed_cost_per_unit: 5, moq: 200, lead_time_days: 10, reliability_score: 0.95 });
const pricey = quote({ id: "c", unit_price: 8, logistics_cost_per_unit: 2, total_landed_cost_per_unit: 10, moq: 400, lead_time_days: 20, reliability_score: 0.5, verified: false });

test("sortByLandedCost ordena de menor a mayor coste entregado sin mutar la entrada", () => {
  const input = [pricey, cheap, fast];
  const sorted = sortByLandedCost(input);
  assert.deepEqual(sorted.map((q) => q.id), ["a", "b", "c"]);
  assert.deepEqual(input.map((q) => q.id), ["c", "a", "b"]);
});

test("applyFilters sin filtros devuelve todo y cada filtro descarta lo que lo supera", () => {
  const all = [cheap, fast, pricey];
  assert.equal(applyFilters(all, {}).length, 3);
  assert.deepEqual(applyFilters(all, { maxMoq: 400 }).map((q) => q.id), ["b", "c"]);
  assert.deepEqual(applyFilters(all, { maxLeadTimeDays: 20 }).map((q) => q.id), ["b", "c"]);
  assert.deepEqual(applyFilters(all, { maxUnitPrice: 4, maxMoq: 500 }).map((q) => q.id), ["b"]);
  assert.deepEqual(applyFilters(all, { maxUnitPrice: 1 }), []);
});

test("distinctionsFor no distingue nada con un solo proveedor", () => {
  assert.equal(distinctionsFor([cheap]).size, 0);
});

test("distinctionsFor marca al líder de cada criterio", () => {
  const map = distinctionsFor([cheap, fast, pricey]);
  assert.deepEqual(map.get("a"), ["lowest_cost"]);
  assert.deepEqual(map.get("b"), ["most_reliable", "fastest", "lowest_moq"]);
  assert.equal(map.get("c"), undefined);
});

test("distinctionsFor reconoce empates (ambos lideran)", () => {
  const twin = quote({ id: "d", total_landed_cost_per_unit: 2.5 });
  const map = distinctionsFor([cheap, twin]);
  assert.ok(map.get("a")?.includes("lowest_cost"));
  assert.ok(map.get("d")?.includes("lowest_cost"));
});

test("supplierRadarValues: el mejor del conjunto vale 1 y el resto es proporcional; fiabilidad es literal", () => {
  const all = [cheap, fast, pricey];
  const values = supplierRadarValues(cheap, all);
  assert.equal(values.price, 1);
  assert.equal(values.logistics, 1);
  assert.equal(values.reliability, 0.7);
  assert.equal(values.flexibility, 0.2); // min moq 200 / 1000
  assert.ok(Math.abs(values.speed - 10 / 30) < 1e-9);

  const worst = supplierRadarValues(pricey, all);
  assert.equal(worst.price, 0.25); // 2 / 8
  assert.equal(worst.logistics, 0.25); // 0.5 / 2
});

test("supplierRadarValues nunca sale del rango 0-1", () => {
  const all = [cheap, fast, pricey];
  for (const q of all) {
    for (const value of Object.values(supplierRadarValues(q, all))) {
      assert.ok(value >= 0 && value <= 1, `fuera de rango: ${value}`);
    }
  }
});

test("averageRadarValues promedia eje a eje", () => {
  const all = [cheap, fast];
  const average = averageRadarValues(all);
  const a = supplierRadarValues(cheap, all);
  const b = supplierRadarValues(fast, all);
  assert.ok(Math.abs(average.price - (a.price + b.price) / 2) < 1e-9);
  assert.ok(Math.abs(average.reliability - (0.7 + 0.95) / 2) < 1e-9);
});

test("toCsv escapa comillas, comas y saltos de línea, y antepone BOM", () => {
  const csv = toCsv(["Nombre", "Nota"], [["Acme, S.L.", 'dice "hola"'], ["Otro", "línea1\nlínea2"]]);
  assert.ok(csv.startsWith("﻿"));
  assert.ok(csv.includes('"Acme, S.L.","dice ""hola"""'));
  assert.ok(csv.includes('"línea1\nlínea2"'));
});
