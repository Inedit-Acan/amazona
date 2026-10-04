import assert from "node:assert/strict";
import { test } from "node:test";
import type { CFOReport, EconomicAnalysis, Product } from "./api.ts";
import { PLAN_BLOCKED_TEXT, PLAN_NOTE, planView } from "./cfo-plan.ts";
import { verdictView, NO_VERDICT_TEXT } from "./cfo-verdict.ts";
import { toText } from "./decimal.ts";

// La zona PLAN y la evaluación del agente (M45, Commit 10): proyecciones y veredictos, nunca hechos.

const product = (id: string, name: string): Product => ({
  id,
  name,
  category: "home",
  status: "ACTIVE",
  created_by: "agent",
  source: "research",
});

function analysis(over: Partial<EconomicAnalysis> = {}): EconomicAnalysis {
  return {
    correlation_id: "c1",
    product_id: "p1",
    supplier_quote_id: "q1",
    sale_price: 50,
    monthly_fixed_costs: 100,
    margin_percent: 0.4,
    recommendation: "GO",
    confidence: 0.8,
    channel: "own_store",
    currency: "EUR",
    units_per_order: 2,
    units_per_order_provenance: null,
    margin_evaluability: "evaluable",
    cac_evaluability: "evaluable",
    missing_inputs: null,
    contribution_margin_per_unit: "12.5000",
    contribution_margin_per_order: "25.0000",
    allocated_fixed_cost_per_order: null,
    max_breakeven_cac: null,
    fx_conversions: null,
    data: null,
    ...over,
  };
}

test("la proyección usa los importes exactos del backend, no el modelo del navegador", () => {
  const view = planView([product("p1", "Lámpara")], new Map([["p1", analysis()]]));
  assert.equal(toText(view.rows[0].perUnit!.value), "12.5000");
  assert.equal(toText(view.rows[0].perOrder!.value), "25.0000");
  assert.equal(view.rows[0].perUnit!.provenance, "planned");
  assert.equal(toText(view.totalPerOrder!.value), "25.0000");
});

test("lo que el backend no pudo evaluar no se rellena: se enseña lo que falta", () => {
  const view = planView(
    [product("p1", "Lámpara")],
    new Map([["p1", analysis({ margin_evaluability: "not_evaluable", missing_inputs: ["unit_cost", "units_per_order"] })]]),
  );
  assert.equal(view.rows[0].perUnit, null);
  assert.equal(view.rows[0].perOrder, null);
  assert.deepEqual(view.rows[0].missing, ["unit_cost", "units_per_order"]);
  assert.equal(view.totalPerOrder, null);
  assert.equal(view.blockedBy, "not_evaluable");
});

test("no se totaliza una proyección con huecos, y se dice por qué", () => {
  const view = planView(
    [product("p1", "A"), product("p2", "B")],
    new Map([
      ["p1", analysis()],
      ["p2", analysis({ product_id: "p2", margin_evaluability: "not_evaluable", contribution_margin_per_order: null })],
    ]),
  );
  assert.equal(view.totalPerOrder, null);
  assert.equal(view.evaluable, 1);
  assert.equal(view.analysed, 2);
  assert.match(PLAN_BLOCKED_TEXT[view.blockedBy!], /sumaría huecos/);
});

test("análisis en monedas distintas no se suman ni se convierten", () => {
  const view = planView(
    [product("p1", "A"), product("p2", "B")],
    new Map([
      ["p1", analysis()],
      ["p2", analysis({ product_id: "p2", currency: "USD" })],
    ]),
  );
  assert.equal(view.totalPerOrder, null);
  assert.equal(view.blockedBy, "mixed_currencies");
  assert.equal(view.currency, null);
});

test("sin análisis no hay proyección inventada", () => {
  const view = planView([product("p1", "A")], new Map());
  assert.deepEqual(view.rows, []);
  assert.equal(view.totalPerOrder, null);
  assert.equal(view.blockedBy, "no_analyses");
});

test("la nota de la zona dice que es contribución, no beneficio", () => {
  assert.match(PLAN_NOTE, /no ha ocurrido/i);
  assert.match(PLAN_NOTE, /no incluye costes fijos, impuestos/);
  assert.ok(!/\bbeneficio neto\b/.test(PLAN_NOTE.replace("no beneficio", "")));
});

// --- Evaluación del agente -------------------------------------------------------------------------------------------

const report = (over: Partial<CFOReport> = {}): CFOReport => ({
  correlation_id: "r1",
  financial_health_status: "HEALTHY",
  recommendation: "GO",
  confidence: 0.75,
  data: {
    no_go_ratio: 0.1,
    budget_utilization: 0.42,
    total_products_analyzed: 10,
    go_count: 7,
    review_count: 2,
    no_go_count: 1,
    total_campaigns: 3,
    active_campaigns: 2,
    total_daily_budget: 0,
    total_budget_hard_limit: 0,
    total_reserved: 0,
    total_committed: 0,
    total_spent: 0,
  },
  ...over,
});

test("el veredicto nunca se presenta como información completa: el agente no ve el registro de pagos", () => {
  const view = verdictView(report());
  assert.equal(view.level, "partial");
  assert.equal(view.title, "Evaluación CFO — información parcial");
  assert.ok(view.missing.some((item) => /registro de pagos/.test(item)));
  assert.ok(view.missing.some((item) => /costes efectivamente pagados/.test(item)));
});

test("el veredicto dice de dónde sale y que no confirma rentabilidad", () => {
  const view = verdictView(report());
  assert.match(view.source, /No procede del registro financiero/);
  assert.match(view.source, /no confirma rentabilidad/);
  assert.ok(!/rentabilidad confirmada/i.test(view.title + view.detail + view.source));
});

test("sin productos analizados la información es insuficiente, y se dice", () => {
  const view = verdictView(report({ financial_health_status: "NEEDS_REVIEW", data: { ...report().data!, total_products_analyzed: 0 } }));
  assert.equal(view.level, "insufficient");
  assert.match(view.title, /información insuficiente/);
  assert.ok(view.missing.some((item) => /Ningún producto analizado/.test(item)));
});

test("un informe sin datos de apoyo no inventa ninguno", () => {
  const view = verdictView(report({ data: null }));
  assert.deepEqual(view.inputs, []);
  assert.equal(view.level, "insufficient");
  assert.ok(view.missing.some((item) => /ningún dato de apoyo/.test(item)));
});

test("los datos que usó se enseñan tal como los dio", () => {
  const view = verdictView(report());
  const inputs = new Map(view.inputs.map((input) => [input.label, input.value]));
  assert.equal(inputs.get("Productos analizados"), "10");
  assert.equal(inputs.get("GO / REVIEW / NO_GO"), "7 / 2 / 1");
  assert.equal(inputs.get("Proporción NO_GO"), "10 %");
  assert.equal(inputs.get("Uso del presupuesto"), "42 %");
});

test("sin informe no hay veredicto neutro inventado", () => {
  assert.match(NO_VERDICT_TEXT, /no ha emitido/);
});
