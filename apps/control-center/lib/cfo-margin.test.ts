import assert from "node:assert/strict";
import { test } from "node:test";
import type { MoneyAmount, Order, OrderItem, RevenueEntry } from "./api.ts";
import { BLOCKED_TEXT, coverageText, declaredCost, marginSummary } from "./cfo-margin.ts";
import { toText } from "./decimal.ts";

// Coste declarado y margen de contribución declarado (M45, Commit 10).
//
//   margen = ingreso verificado − reembolsos verificados − coste declarado,
//
// y SÓLO con cobertura del 100 %. Todo lo demás de este fichero es comprobar que, cuando falta algo, el resultado es
// `null` y no un número inventado.

const money = (amount: string, currency = "EUR"): MoneyAmount => ({ amount, currency });

function item(over: Partial<OrderItem> = {}): OrderItem {
  return {
    id: `item-${over.line_number ?? 1}`,
    line_number: over.line_number ?? 1,
    product_id: "p1",
    supplier_id: null,
    supplier_quote_id: null,
    quantity: 1,
    allocated_quantity: 0,
    unit_price: money("50.0000"),
    line_total: money("50.0000"),
    unit_cost: money("30.0000"),
    cost_provenance: "supplier_quote",
    cost_source: "supplier_quote:q1",
    ...over,
  };
}

function order(id: string, items: OrderItem[], over: Partial<Order> = {}): Order {
  return {
    id,
    customer_ref: "sim_customer",
    market: "eu",
    status: "PAID",
    is_simulated: true,
    amount_due: money("50.0000"),
    items,
    payments: [],
    refunds: [],
    fulfillments: [],
    created_at: "2026-10-01T09:00:00Z",
    paid_at: null,
    completed_at: null,
    cancelled_at: null,
    correlation_id: "c1",
    attention_required: false,
    attention_reasons: [],
    ...over,
  };
}

function entry(orderId: string, kind: "CAPTURE" | "REFUND", amount: string, over: Partial<RevenueEntry> = {}): RevenueEntry {
  return {
    id: `${orderId}-${kind}-${amount}`,
    kind,
    classification: "ORDER_PAYMENT",
    payment_event_id: "ev",
    payment_id: "pay",
    order_id: orderId,
    refund_id: kind === "REFUND" ? "r1" : null,
    capture_entry_id: null,
    amount,
    currency: "EUR",
    occurred_at: "2026-10-02T10:00:00+00:00",
    recorded_at: "2026-10-02T10:00:01+00:00",
    ...over,
  };
}

const complete = { entriesComplete: true };

// --- Coste declarado de un pedido ----------------------------------------------------------------------------------

test("el coste de un pedido es la suma de coste unitario por unidades, exacta", () => {
  const result = declaredCost(order("o1", [item({ unit_cost: money("12.3400"), quantity: 3 }), item({ line_number: 2, unit_cost: money("0.0001"), quantity: 2 })]));
  assert.equal(toText(result.cost!), "37.0202");
  assert.equal(result.withCost, 2);
  assert.equal(result.lines, 2);
  assert.deepEqual(result.provenances, ["supplier_quote"]);
});

test("una línea sin coste deja el pedido sin coste: no vale cero", () => {
  const result = declaredCost(order("o1", [item(), item({ line_number: 2, unit_cost: null, cost_provenance: null })]));
  assert.equal(result.cost, null);
  assert.equal(result.withCost, 1);
  assert.equal(result.lines, 2);
});

test("un coste sin procedencia declarada no cuenta como conocido", () => {
  const result = declaredCost(order("o1", [item({ cost_provenance: null })]));
  assert.equal(result.cost, null);
  assert.equal(result.withCost, 0);
});

test("un coste en otra moneda no se convierte: queda como desconocido", () => {
  const result = declaredCost(order("o1", [item({ unit_cost: money("30.0000", "USD") })]));
  assert.equal(result.cost, null);
});

test("un pedido sin líneas no tiene coste conocido", () => {
  assert.equal(declaredCost(order("o1", [])).cost, null);
});

// --- Margen: sólo con cobertura del 100 % ---------------------------------------------------------------------------

test("con cobertura total: margen = ingreso − reembolsos − coste", () => {
  const summary = marginSummary(
    [entry("o1", "CAPTURE", "100.0000"), entry("o1", "REFUND", "10.0000")],
    [order("o1", [item({ unit_cost: money("30.0000"), quantity: 2 })])],
    complete,
  );
  assert.equal(summary.coverage.complete, true);
  assert.equal(summary.coverage.percent, 100);
  assert.equal(toText(summary.revenue!.value), "100.0000");
  assert.equal(toText(summary.refunds!.value), "10.0000");
  assert.equal(toText(summary.net!.value), "90.0000");
  assert.equal(toText(summary.cost!.value), "60.0000");
  assert.equal(toText(summary.margin!.value), "30.0000");
  assert.equal(summary.blockedBy, null);
});

test("el margen es un dato DECLARADO, no verificado: no puede ser más fiable que su peor ingrediente", () => {
  const summary = marginSummary([entry("o1", "CAPTURE", "100.0000")], [order("o1", [item()])], complete);
  assert.equal(summary.margin!.provenance, "declared");
  assert.equal(summary.cost!.provenance, "declared");
  // El ingreso y el neto siguen siendo hechos del registro.
  assert.equal(summary.revenue!.provenance, "verified");
  assert.equal(summary.net!.provenance, "verified");
  assert.equal(summary.orders[0].margin!.provenance, "declared");
  assert.equal(summary.orders[0].cost!.provenance, "declared");
  assert.equal(summary.orders[0].revenue.provenance, "verified");
  assert.equal(summary.orders[0].net.provenance, "verified");
});

test("una sola línea sin coste y NO hay margen, ni del pedido ni del total", () => {
  const summary = marginSummary(
    [entry("o1", "CAPTURE", "100.0000"), entry("o2", "CAPTURE", "50.0000")],
    [order("o1", [item()]), order("o2", [item(), item({ line_number: 2, unit_cost: null, cost_provenance: null })])],
    complete,
  );
  assert.equal(summary.margin, null);
  assert.equal(summary.cost, null);
  assert.equal(summary.net, null, "sin cobertura no se agrega ninguna magnitud derivada");
  assert.equal(summary.blockedBy, "missing_costs");
  assert.equal(summary.coverage.linesWithCost, 2);
  assert.equal(summary.coverage.lines, 3);
  assert.equal(summary.coverage.percent, 67);
  // El pedido que sí tiene cobertura conserva su margen en el detalle; el otro no.
  const [first, second] = summary.orders.sort((a, b) => a.orderId.localeCompare(b.orderId));
  assert.notEqual(first.margin, null);
  assert.equal(second.margin, null);
});

test("un pedido que no se pudo leer es coste desconocido, no coste cero", () => {
  const summary = marginSummary([entry("o1", "CAPTURE", "100.0000")], [], complete);
  assert.equal(summary.margin, null);
  assert.equal(summary.blockedBy, "orders_not_read");
  assert.equal(summary.coverage.orders, 1);
  assert.equal(summary.coverage.ordersRead, 0);
  assert.equal(summary.orders[0].cost, null);
  assert.match(coverageText(summary.coverage), /no se pudo leer/);
});

test("un pedido sin leer impide la cobertura total aunque otro pedido la tenga entera", () => {
  const summary = marginSummary(
    [entry("o1", "CAPTURE", "100.0000"), entry("o2", "CAPTURE", "50.0000")],
    [order("o1", [item()])], // o2 no se leyó
    complete,
  );
  assert.equal(summary.coverage.lines, 1);
  assert.equal(summary.coverage.linesWithCost, 1, "las líneas que sí se leyeron están completas…");
  assert.equal(summary.coverage.percent, 100, "…y aun así el porcentaje de líneas no basta");
  assert.equal(summary.coverage.complete, false, "falta un pedido entero: no hay cobertura");
  assert.equal(summary.margin, null);
  assert.equal(summary.blockedBy, "orders_not_read");
});

test("con las entradas truncadas no se calcula nada: el ingreso por pedido estaría incompleto", () => {
  const summary = marginSummary([entry("o1", "CAPTURE", "100.0000")], [order("o1", [item()])], { entriesComplete: false });
  assert.equal(summary.margin, null);
  assert.equal(summary.blockedBy, "entries_incomplete");
  assert.equal(summary.coverage.complete, false);
});

test("sin pedidos con ingreso verificado, no hay margen ni cobertura que enseñar", () => {
  const summary = marginSummary([], [], complete);
  assert.equal(summary.margin, null);
  assert.equal(summary.blockedBy, "no_orders");
  assert.equal(summary.coverage.orders, 0);
  assert.equal(coverageText(summary.coverage), "Ningún pedido con ingreso verificado en este periodo.");
});

test("un margen de cero es un cero medido, no «sin datos»", () => {
  const summary = marginSummary([entry("o1", "CAPTURE", "60.0000")], [order("o1", [item({ unit_cost: money("30.0000"), quantity: 2 })])], complete);
  assert.notEqual(summary.margin, null);
  assert.equal(toText(summary.margin!.value), "0.0000");
});

test("un margen negativo se enseña: vender por debajo del coste no se oculta", () => {
  const summary = marginSummary([entry("o1", "CAPTURE", "10.0000")], [order("o1", [item({ unit_cost: money("30.0000") })])], complete);
  assert.equal(toText(summary.margin!.value), "-20.0000");
});

// --- Monedas --------------------------------------------------------------------------------------------------------

test("un pedido con ingreso en otra moneda queda fuera y no se convierte", () => {
  const summary = marginSummary(
    [entry("o1", "CAPTURE", "100.0000"), entry("o2", "CAPTURE", "50.0000", { currency: "USD" })],
    [order("o1", [item()]), order("o2", [item()])],
    complete,
  );
  assert.deepEqual(summary.otherCurrencies, ["USD"]);
  assert.equal(summary.coverage.orders, 1, "sólo cuenta el pedido en la moneda contable");
  assert.equal(toText(summary.revenue!.value), "100.0000");
  // 150 sería la suma de monedas distintas: no puede aparecer en ninguna cifra, ni agregada ni por pedido.
  const amounts = [summary.revenue, summary.refunds, summary.net, summary.cost, summary.margin]
    .filter((value) => value !== null)
    .map((value) => toText(value!.value))
    .concat(summary.orders.flatMap((row) => [toText(row.net.value), toText(row.revenue.value)]));
  assert.ok(!amounts.some((text) => text.startsWith("150")), amounts.join(" "));
});

test("un pedido con entradas en dos monedas no se agrega: no se elige una por nosotros", () => {
  const summary = marginSummary(
    [entry("o1", "CAPTURE", "100.0000"), entry("o1", "CAPTURE", "50.0000", { currency: "USD" })],
    [order("o1", [item()])],
    complete,
  );
  assert.equal(summary.coverage.orders, 0);
  assert.equal(summary.margin, null);
});

// --- Qué entra y qué no ----------------------------------------------------------------------------------------------

test("un duplicado o una discrepancia nunca entra en el ingreso del margen", () => {
  const summary = marginSummary(
    [
      entry("o1", "CAPTURE", "100.0000"),
      entry("o1", "CAPTURE", "40.0000", { classification: "DUPLICATE_RECEIPT", id: "dup" }),
      entry("o1", "CAPTURE", "5.0000", { classification: "MISMATCH_RECEIPT", id: "mis" }),
    ],
    [order("o1", [item()])],
    complete,
  );
  assert.equal(toText(summary.revenue!.value), "100.0000");
  assert.equal(toText(summary.margin!.value), "70.0000");
});

test("un importe que no es decimal no se adivina: esa entrada no entra", () => {
  const summary = marginSummary([entry("o1", "CAPTURE", "100.0000"), entry("o1", "CAPTURE", "cien", { id: "x" })], [order("o1", [item()])], complete);
  assert.equal(toText(summary.revenue!.value), "100.0000");
});

test("se declara cuántos pedidos están marcados como simulados: el pedido sí lo sabe", () => {
  const summary = marginSummary(
    [entry("o1", "CAPTURE", "100.0000"), entry("o2", "CAPTURE", "100.0000")],
    [order("o1", [item()], { is_simulated: true }), order("o2", [item()], { is_simulated: false })],
    complete,
  );
  assert.equal(summary.simulated, 1);
  assert.equal(summary.orders.find((row) => row.orderId === "o1")!.isSimulated, true);
  assert.equal(summary.orders.find((row) => row.orderId === "o2")!.isSimulated, false);
});

test("cada motivo de bloqueo tiene su texto, y ninguno es un número", () => {
  for (const [key, text] of Object.entries(BLOCKED_TEXT)) {
    assert.ok(text.length > 20, key);
    assert.ok(!/^\d/.test(text));
  }
});

test("la cobertura se cuenta en líneas y se dice tal cual", () => {
  const summary = marginSummary(
    [entry("o1", "CAPTURE", "100.0000")],
    [order("o1", [item(), item({ line_number: 2 }), item({ line_number: 3, unit_cost: null, cost_provenance: null })])],
    complete,
  );
  assert.match(coverageText(summary.coverage), /Costes conocidos: 2 \/ 3 líneas · Cobertura: 67 %/);
});
