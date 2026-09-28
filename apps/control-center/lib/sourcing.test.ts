import { test } from "node:test";
import assert from "node:assert/strict";
import { supplierRadarValues } from "./sourcing.ts";
import { toCsv } from "./csv.ts";
import { quoteFixture } from "./quote-fixture.ts";

const cheap = quoteFixture({
  id: "a",
  supplier_id: "s-a",
  unit_price: 2,
  logistics_cost_per_unit: 0.5,
  total_landed_cost_per_unit: 2.5,
  moq: 1000,
  lead_time_days: 30,
});
const fast = quoteFixture({
  id: "b",
  supplier_id: "s-b",
  unit_price: 4,
  logistics_cost_per_unit: 1,
  total_landed_cost_per_unit: 5,
  moq: 200,
  lead_time_days: 10,
});
const pricey = quoteFixture({
  id: "c",
  supplier_id: "s-c",
  unit_price: 8,
  logistics_cost_per_unit: 2,
  total_landed_cost_per_unit: 10,
  moq: 400,
  lead_time_days: 20,
});

test("supplierRadarValues: el mejor del conjunto vale 1 y el resto es proporcional", () => {
  const all = [cheap, fast, pricey];
  const values = supplierRadarValues(cheap, all);
  assert.equal(values.price, 1);
  assert.equal(values.logistics, 1);
  assert.equal(values.flexibility, 0.2); // min moq 200 / 1000
  assert.ok(Math.abs((values.speed ?? 0) - 10 / 30) < 1e-9);

  const worst = supplierRadarValues(pricey, all);
  assert.equal(worst.price, 0.25); // 2 / 8
  assert.equal(worst.logistics, 0.25); // 0.5 / 2
});

test("supplierRadarValues nunca sale del rango 0-1", () => {
  const all = [cheap, fast, pricey];
  for (const q of all) {
    for (const value of Object.values(supplierRadarValues(q, all))) {
      assert.ok(value !== null && value >= 0 && value <= 1, `fuera de rango: ${value}`);
    }
  }
});

test("supplierRadarValues: un dato que nadie ha declarado no vale cero, vale nada", () => {
  // Un MOQ desconocido pintado como 0 sería un proveedor perfectamente flexible
  // que nadie ha comprobado (Milestone 39).
  const silent = quoteFixture({
    id: "d",
    supplier_id: "s-d",
    moq: null,
    unit_price: null,
    logistics_cost_per_unit: 2,
  });

  const values = supplierRadarValues(silent, [cheap, fast, pricey, silent]);

  assert.equal(values.flexibility, null);
  assert.equal(values.price, null);
  // Lo que sí declara se sigue puntuando con normalidad.
  assert.equal(values.logistics, 0.25);
});

test("supplierRadarValues: si nadie del conjunto declara un eje, el que lo declara es el mejor", () => {
  const only = quoteFixture({ id: "e", supplier_id: "s-e", moq: 50 });
  const silent = quoteFixture({ id: "f", supplier_id: "s-f", moq: null });

  assert.equal(supplierRadarValues(only, [only, silent]).flexibility, 1);
});

test("toCsv escapa comillas, comas y saltos de línea, y antepone BOM", () => {
  const csv = toCsv(["Nombre", "Nota"], [["Acme, S.L.", 'dice "hola"'], ["Otro", "línea1\nlínea2"]]);
  assert.ok(csv.startsWith("﻿"));
  assert.ok(csv.includes('"Acme, S.L.","dice ""hola"""'));
  assert.ok(csv.includes('"línea1\nlínea2"'));
});
