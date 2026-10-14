import assert from "node:assert/strict";
import { test } from "node:test";
import { buildInitialState, DEFAULT_CONTEXT, hasHandoff } from "./ceo-handoff.ts";

// La precarga de la misión desde otras pantallas (M47, Commit 2). Antes `buildInitialState` vivía dentro de la página y no tenía
// ninguna prueba. Aquí se fijan los parámetros EXACTOS que mandan las seis pantallas de origen.

const params = (init: Record<string, string>) => new URLSearchParams(init);

test("sin precarga: el título está vacío (no se inventa uno) y el contexto es el de ejemplo", () => {
  const state = buildInitialState(params({}));
  assert.equal(state.title, "");
  assert.deepEqual(state.context, DEFAULT_CONTEXT);
  assert.equal(hasHandoff(params({})), false);
  // Ni el título ni el solicitante de demostración de la página anterior.
  assert.doesNotMatch(JSON.stringify(state), /earbuds|owner@amazona/i);
});

test("solo cuenta como precarga si trae un título que no esté en blanco", () => {
  assert.equal(hasHandoff(params({ unit_cost: "5" })), false);
  assert.equal(hasHandoff(params({ title: "   " })), false);
  assert.equal(hasHandoff(params({ title: "Validar X" })), true);
  assert.deepEqual(buildInitialState(params({ unit_cost: "9" })).context, DEFAULT_CONTEXT, "sin título no se aplica ningún parámetro");
});

test("solo título: el resto es el contexto de ejemplo", () => {
  const state = buildInitialState(params({ title: "Aprobar algo" }));
  assert.equal(state.title, "Aprobar algo");
  assert.deepEqual(state.context, DEFAULT_CONTEXT);
});

test("Investigación → misión: señal de demanda y competencia", () => {
  const state = buildInitialState(
    params({ title: "Validar oportunidad: Auriculares", product_name: "Auriculares", category: "Audio", demand_signal: "0.80", competition_level: "high" }),
  );
  assert.equal(state.context.product_validation.estimated_monthly_searches, 12000);
  assert.equal(state.context.product_validation.competition_level, "high");
  assert.equal(buildInitialState(params({ title: "t", demand_signal: "0.5" })).context.product_validation.estimated_monthly_searches, 7500);
});

test("Proveedores → misión: coste, plazo y verificación (la cadena vacía y «false» se leen bien)", () => {
  const verified = buildInitialState(params({ title: "t", unit_cost: "4.2", lead_time_days: "18", supplier_verified: "true" }));
  assert.equal(verified.context.supplier_sourcing.unit_cost, 4.2);
  assert.equal(verified.context.supplier_sourcing.lead_time_days, 18);
  assert.equal(verified.context.supplier_sourcing.supplier_verified, true);
  assert.equal(verified.context.finance_validation.unit_cost, 4.2, "el coste unitario alimenta también la validación financiera");

  // El origen manda `String(quote.unit_price ?? "")`: sin precio llega vacío y NO debe volverse 0 ni NaN.
  const blank = buildInitialState(params({ title: "t", unit_cost: "", lead_time_days: "", supplier_verified: "false" }));
  assert.equal(blank.context.supplier_sourcing.unit_cost, DEFAULT_CONTEXT.supplier_sourcing.unit_cost);
  assert.equal(blank.context.supplier_sourcing.lead_time_days, DEFAULT_CONTEXT.supplier_sourcing.lead_time_days);
  assert.equal(blank.context.supplier_sourcing.supplier_verified, false);
});

test("Economía → misión: coste, precio, costes fijos y ventas", () => {
  const state = buildInitialState(
    params({ title: "t", unit_cost: "6.50", sale_price: "24.9", monthly_fixed_costs: "800", monthly_unit_sales: "120" }),
  );
  assert.deepEqual(state.context.finance_validation, { unit_cost: 6.5, sale_price: 24.9, monthly_unit_sales: 120, monthly_fixed_costs: 800 });
});

test("Legal → misión: categoría restringida y certificaciones", () => {
  const state = buildInitialState(
    params({ title: "t", restricted_category: "true", requires_certification: "true", certification_available: "false" }),
  );
  assert.deepEqual(state.context.legal_validation, { restricted_category: true, requires_certification: true, certification_available: false });
});

test("Tienda y Marketing → misión: precio de venta y gasto", () => {
  assert.equal(buildInitialState(params({ title: "t", sale_price: "19.9" })).context.finance_validation.sale_price, 19.9);
  assert.equal(buildInitialState(params({ title: "t", spend_amount: "250" })).context.spend_amount, 250);
});

test("un número ilegible nunca llega al backend como NaN o Infinity: vale el de ejemplo", () => {
  const state = buildInitialState(
    params({ title: "t", unit_cost: "abc", sale_price: "Infinity", monthly_unit_sales: "-", spend_amount: "NaN", demand_signal: "x", lead_time_days: " " }),
  );
  const json = JSON.stringify(state.context);
  assert.doesNotMatch(json, /null|NaN|Infinity/);
  assert.equal(state.context.finance_validation.unit_cost, DEFAULT_CONTEXT.finance_validation.unit_cost);
  assert.equal(state.context.finance_validation.sale_price, DEFAULT_CONTEXT.finance_validation.sale_price);
  assert.equal(state.context.spend_amount, DEFAULT_CONTEXT.spend_amount);
  assert.equal(state.context.product_validation.estimated_monthly_searches, DEFAULT_CONTEXT.product_validation.estimated_monthly_searches);
});

test("buildInitialState no muta el contexto de ejemplo compartido", () => {
  const before = JSON.stringify(DEFAULT_CONTEXT);
  buildInitialState(params({ title: "t", unit_cost: "99", spend_amount: "1", supplier_verified: "false" }));
  assert.equal(JSON.stringify(DEFAULT_CONTEXT), before);
});
