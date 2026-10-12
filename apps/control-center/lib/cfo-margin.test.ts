import assert from "node:assert/strict";
import { test } from "node:test";
import type { MoneyAmount, Order, OrderItem, RevenueEntry } from "./api.ts";
import { BLOCKED_TEXT, coverageText, declaredCost, marginSummary, type MarginSummary, type OriginMargin } from "./cfo-margin.ts";
import { toText } from "./decimal.ts";
import type { Origin } from "./provenance.ts";

// Coste declarado y margen de contribución declarado (M45, Commit 10), POR ORIGEN (M46, Commit 4, ADR 0031 A6).
//
//   margen = ingreso verificado − reembolsos verificados − coste declarado,
//
// SÓLO con cobertura del 100 % y SIEMPRE dentro de UN origen: no existe un margen que cruce `mock`, `sandbox` y `real`.
// Todo lo demás de este fichero es comprobar que, cuando falta algo (un coste, un pedido, un origen conocido), el
// resultado es `null` y no un número inventado, y que ninguna cifra es la suma de dos orígenes ni de dos monedas.

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
    id: `${orderId}-${kind}-${amount}-${over.provider_kind ?? "mock"}`,
    kind,
    provider_kind: "mock",
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

/** El margen de un origen, que tiene que existir. */
function of(summary: MarginSummary, origin: Origin): OriginMargin {
  const found = summary.origins.find((candidate) => candidate.origin === origin);
  assert.ok(found, `no hay margen del origen ${origin}`);
  return found;
}

/** Todos los textos de importe que la vista podría enseñar de un resumen. */
function amounts(summary: MarginSummary): string[] {
  return summary.origins.flatMap((origin) =>
    [origin.revenue, origin.refunds, origin.net, origin.cost, origin.margin]
      .filter((value) => value !== null)
      .map((value) => toText(value!.value))
      .concat(origin.orders.flatMap((row) => [toText(row.net.value), toText(row.revenue.value)])),
  );
}

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
  const mock = of(summary, "mock");
  assert.equal(mock.coverage.complete, true);
  assert.equal(mock.coverage.percent, 100);
  assert.equal(toText(mock.revenue!.value), "100.0000");
  assert.equal(toText(mock.refunds!.value), "10.0000");
  assert.equal(toText(mock.net!.value), "90.0000");
  assert.equal(toText(mock.cost!.value), "60.0000");
  assert.equal(toText(mock.margin!.value), "30.0000");
  assert.equal(mock.blockedBy, null);
  assert.equal(summary.blockedBy, null);
});

test("el margen es un dato DECLARADO, no verificado: no puede ser más fiable que su peor ingrediente", () => {
  const mock = of(marginSummary([entry("o1", "CAPTURE", "100.0000")], [order("o1", [item()])], complete), "mock");
  assert.equal(mock.margin!.provenance, "declared");
  assert.equal(mock.cost!.provenance, "declared");
  // El ingreso y el neto siguen siendo hechos del registro, y llevan su origen en el tipo.
  assert.equal(mock.revenue!.provenance, "verified");
  assert.equal(mock.net!.provenance, "verified");
  assert.equal(mock.net!.origin, "mock");
  assert.equal(mock.orders[0].margin!.provenance, "declared");
  assert.equal(mock.orders[0].cost!.provenance, "declared");
  assert.equal(mock.orders[0].revenue.provenance, "verified");
  assert.equal(mock.orders[0].net.origin, "mock");
});

test("una sola línea sin coste y NO hay margen, ni del pedido ni del origen", () => {
  const summary = marginSummary(
    [entry("o1", "CAPTURE", "100.0000"), entry("o2", "CAPTURE", "50.0000")],
    [order("o1", [item()]), order("o2", [item(), item({ line_number: 2, unit_cost: null, cost_provenance: null })])],
    complete,
  );
  const mock = of(summary, "mock");
  assert.equal(mock.margin, null);
  assert.equal(mock.cost, null);
  assert.equal(mock.net, null, "sin cobertura no se agrega ninguna magnitud derivada");
  assert.equal(mock.blockedBy, "missing_costs");
  assert.equal(mock.coverage.linesWithCost, 2);
  assert.equal(mock.coverage.lines, 3);
  assert.equal(mock.coverage.percent, 67);
  // El pedido que sí tiene cobertura conserva su margen en el detalle; el otro no.
  const [first, second] = [...mock.orders].sort((a, b) => a.orderId.localeCompare(b.orderId));
  assert.notEqual(first.margin, null);
  assert.equal(second.margin, null);
});

test("un pedido que no se pudo leer es coste desconocido, no coste cero", () => {
  const mock = of(marginSummary([entry("o1", "CAPTURE", "100.0000")], [], complete), "mock");
  assert.equal(mock.margin, null);
  assert.equal(mock.blockedBy, "orders_not_read");
  assert.equal(mock.coverage.orders, 1);
  assert.equal(mock.coverage.ordersRead, 0);
  assert.equal(mock.orders[0].cost, null);
  assert.match(coverageText(mock.coverage), /no se pudo leer/);
});

test("un pedido sin leer impide la cobertura total aunque otro pedido la tenga entera", () => {
  const mock = of(
    marginSummary(
      [entry("o1", "CAPTURE", "100.0000"), entry("o2", "CAPTURE", "50.0000")],
      [order("o1", [item()])], // o2 no se leyó
      complete,
    ),
    "mock",
  );
  assert.equal(mock.coverage.lines, 1);
  assert.equal(mock.coverage.linesWithCost, 1, "las líneas que sí se leyeron están completas…");
  assert.equal(mock.coverage.percent, 100, "…y aun así el porcentaje de líneas no basta");
  assert.equal(mock.coverage.complete, false, "falta un pedido entero: no hay cobertura");
  assert.equal(mock.margin, null);
  assert.equal(mock.blockedBy, "orders_not_read");
});

test("con las entradas truncadas no se calcula nada: el ingreso por pedido estaría incompleto", () => {
  const summary = marginSummary([entry("o1", "CAPTURE", "100.0000")], [order("o1", [item()])], { entriesComplete: false });
  const mock = of(summary, "mock");
  assert.equal(mock.margin, null);
  assert.equal(mock.blockedBy, "entries_incomplete");
  assert.equal(mock.coverage.complete, false);
});

test("sin entradas y con la lista truncada, el motivo es la lista y no «ningún pedido»", () => {
  const summary = marginSummary([], [], { entriesComplete: false });
  assert.deepEqual(summary.origins, []);
  assert.equal(summary.blockedBy, "entries_incomplete");
});

test("sin pedidos con ingreso verificado, no hay margen, ni origen, ni cobertura que enseñar", () => {
  const summary = marginSummary([], [], complete);
  assert.deepEqual(summary.origins, [], "ningún origen inventado");
  assert.equal(summary.blockedBy, "no_orders");
  assert.equal(coverageText({ orders: 0, ordersRead: 0, lines: 0, linesWithCost: 0, percent: 0, complete: false }), "Ningún pedido con ingreso verificado en este periodo.");
});

test("un margen de cero es un cero medido, no «sin datos»", () => {
  const mock = of(marginSummary([entry("o1", "CAPTURE", "60.0000")], [order("o1", [item({ unit_cost: money("30.0000"), quantity: 2 })])], complete), "mock");
  assert.notEqual(mock.margin, null);
  assert.equal(toText(mock.margin!.value), "0.0000");
});

test("un margen negativo se enseña: vender por debajo del coste no se oculta", () => {
  const mock = of(marginSummary([entry("o1", "CAPTURE", "10.0000")], [order("o1", [item({ unit_cost: money("30.0000") })])], complete), "mock");
  assert.equal(toText(mock.margin!.value), "-20.0000");
});

// --- Monedas --------------------------------------------------------------------------------------------------------

test("un pedido con ingreso en otra moneda queda fuera y no se convierte", () => {
  const summary = marginSummary(
    [entry("o1", "CAPTURE", "100.0000"), entry("o2", "CAPTURE", "50.0000", { currency: "USD" })],
    [order("o1", [item()]), order("o2", [item()])],
    complete,
  );
  const mock = of(summary, "mock");
  assert.deepEqual(summary.otherCurrencies, ["USD"]);
  assert.equal(mock.coverage.orders, 1, "sólo cuenta el pedido en la moneda contable");
  assert.equal(toText(mock.revenue!.value), "100.0000");
  // 150 sería la suma de monedas distintas: no puede aparecer en ninguna cifra, ni agregada ni por pedido.
  assert.ok(!amounts(summary).some((text) => text.startsWith("150")), amounts(summary).join(" "));
});

test("un pedido con entradas en dos monedas no se agrega: no se elige una por nosotros", () => {
  const summary = marginSummary(
    [entry("o1", "CAPTURE", "100.0000"), entry("o1", "CAPTURE", "50.0000", { currency: "USD" })],
    [order("o1", [item()])],
    complete,
  );
  assert.deepEqual(summary.origins, []);
  assert.equal(summary.blockedBy, "no_orders");
});

test("las monedas se separan dentro de cada origen: el USD de uno no entra en el EUR de otro", () => {
  const summary = marginSummary(
    [
      entry("o1", "CAPTURE", "100.0000", { provider_kind: "sandbox" }),
      entry("o2", "CAPTURE", "70.0000", { provider_kind: "sandbox", currency: "USD" }),
      entry("o3", "CAPTURE", "40.0000", { provider_kind: "real" }),
    ],
    [order("o1", [item()]), order("o2", [item()]), order("o3", [item()])],
    complete,
  );
  assert.deepEqual(summary.origins.map((origin) => origin.origin), ["real", "sandbox"]);
  assert.equal(toText(of(summary, "sandbox").revenue!.value), "100.0000");
  assert.equal(toText(of(summary, "real").revenue!.value), "40.0000");
  assert.deepEqual(summary.otherCurrencies, ["USD"]);
  assert.ok(!amounts(summary).some((text) => /^(140|170|210)/.test(text)), "ninguna suma cruzada");
});

// --- Qué entra y qué no ----------------------------------------------------------------------------------------------

test("un duplicado o una discrepancia nunca entra en el ingreso del margen", () => {
  const mock = of(
    marginSummary(
      [
        entry("o1", "CAPTURE", "100.0000"),
        entry("o1", "CAPTURE", "40.0000", { classification: "DUPLICATE_RECEIPT", id: "dup" }),
        entry("o1", "CAPTURE", "5.0000", { classification: "MISMATCH_RECEIPT", id: "mis" }),
      ],
      [order("o1", [item()])],
      complete,
    ),
    "mock",
  );
  assert.equal(toText(mock.revenue!.value), "100.0000");
  assert.equal(toText(mock.margin!.value), "70.0000");
});

test("un duplicado de un origen no entra en el margen de otro ni crea un origen", () => {
  const summary = marginSummary(
    [
      entry("o1", "CAPTURE", "100.0000"),
      entry("o9", "CAPTURE", "999.0000", { provider_kind: "real", classification: "DUPLICATE_RECEIPT", id: "dup-real" }),
    ],
    [order("o1", [item()])],
    complete,
  );
  assert.deepEqual(summary.origins.map((origin) => origin.origin), ["mock"], "el duplicado de real no abre el origen real");
});

test("un importe que no es decimal no se adivina: esa entrada no entra", () => {
  const mock = of(marginSummary([entry("o1", "CAPTURE", "100.0000"), entry("o1", "CAPTURE", "cien", { id: "x" })], [order("o1", [item()])], complete), "mock");
  assert.equal(toText(mock.revenue!.value), "100.0000");
});

test("cada motivo de bloqueo tiene su texto, y ninguno es un número", () => {
  for (const [key, text] of Object.entries(BLOCKED_TEXT)) {
    assert.ok(text.length > 20, key);
    assert.ok(!/^\d/.test(text));
  }
  assert.ok("mixed_origins" in BLOCKED_TEXT && "unknown_origin" in BLOCKED_TEXT);
});

test("la cobertura se cuenta en líneas y se dice tal cual", () => {
  const mock = of(
    marginSummary(
      [entry("o1", "CAPTURE", "100.0000")],
      [order("o1", [item(), item({ line_number: 2 }), item({ line_number: 3, unit_cost: null, cost_provenance: null })])],
      complete,
    ),
    "mock",
  );
  assert.match(coverageText(mock.coverage), /Costes conocidos: 2 \/ 3 líneas · Cobertura: 67 %/);
});

// --- Origen (M46, Commit 4) ------------------------------------------------------------------------------------------

const ORIGINS: Origin[] = ["mock", "sandbox", "real"];

test("cada origen solo tiene su propio margen, con su origen en el tipo", () => {
  for (const origin of ORIGINS) {
    const summary = marginSummary([entry("o1", "CAPTURE", "100.0000", { provider_kind: origin })], [order("o1", [item()])], complete);
    assert.deepEqual(summary.origins.map((candidate) => candidate.origin), [origin]);
    const margin = of(summary, origin);
    assert.equal(margin.net!.origin, origin);
    assert.equal(toText(margin.margin!.value), "70.0000");
  }
});

const COMBINATIONS: Origin[][] = [
  ["mock", "sandbox"],
  ["mock", "real"],
  ["sandbox", "real"],
  ["mock", "sandbox", "real"],
];

for (const combination of COMBINATIONS) {
  test(`pedidos de ${combination.join(" + ")}: un margen por origen y ninguna cifra combinada`, () => {
    // Un pedido por origen, con ingreso distinto por origen (100, 200, 400): una suma no se parece a nadie.
    const revenue: Record<Origin, string> = { mock: "100.0000", sandbox: "200.0000", real: "400.0000" };
    const entries = combination.map((origin, index) => entry(`o${index}`, "CAPTURE", revenue[origin], { provider_kind: origin }));
    const orders = combination.map((_, index) => order(`o${index}`, [item({ unit_cost: money("30.0000") })]));

    const summary = marginSummary(entries, orders, complete);

    assert.deepEqual(summary.origins.map((candidate) => candidate.origin), [...combination].sort());
    for (const origin of combination) {
      const margin = of(summary, origin);
      assert.equal(toText(margin.revenue!.value), revenue[origin]);
      assert.equal(margin.coverage.orders, 1, "cada origen cuenta solo sus pedidos");
      assert.equal(margin.blockedBy, null);
      assert.equal(margin.margin!.provenance, "declared");
    }
    // No existe una cifra de margen, ingreso, neto o coste a nivel de resumen: solo por origen.
    for (const key of ["margin", "revenue", "refunds", "net", "cost", "coverage"]) {
      assert.ok(!(key in summary), `el resumen tiene «${key}», una cifra que cruzaría orígenes`);
    }
    const sums = combination.length === 2 ? ["300", "500", "600"] : ["300", "500", "600", "700"];
    assert.ok(!amounts(summary).some((text) => sums.some((sum) => text.startsWith(sum))), amounts(summary).join(" "));
  });
}

test("un pedido con ingreso de varios orígenes enseña cada parte aparte y NO tiene margen, ni el de ningún origen implicado", () => {
  const summary = marginSummary(
    [
      entry("o1", "CAPTURE", "60.0000", { provider_kind: "mock" }),
      entry("o1", "CAPTURE", "40.0000", { provider_kind: "sandbox" }),
      entry("o2", "CAPTURE", "100.0000", { provider_kind: "mock" }),
    ],
    [order("o1", [item({ unit_cost: money("30.0000") })]), order("o2", [item({ unit_cost: money("30.0000") })])],
    complete,
  );
  const mock = of(summary, "mock");
  const sandbox = of(summary, "sandbox");
  assert.equal(mock.blockedBy, "mixed_origins");
  assert.equal(sandbox.blockedBy, "mixed_origins");
  assert.equal(mock.margin, null);
  assert.equal(sandbox.margin, null);
  assert.equal(mock.net, null, "sin margen no se agrega ninguna cifra derivada del origen");
  // Cada parte del pedido mixto queda en su origen, y ninguna lleva margen (el coste es del pedido, no se reparte).
  const mixedMock = mock.orders.find((row) => row.orderId === "o1")!;
  const mixedSandbox = sandbox.orders.find((row) => row.orderId === "o1")!;
  assert.equal(toText(mixedMock.net.value), "60.0000");
  assert.equal(toText(mixedSandbox.net.value), "40.0000");
  assert.deepEqual(mixedMock.orderOrigins, ["mock", "sandbox"]);
  assert.equal(mixedMock.margin, null);
  assert.equal(mixedSandbox.margin, null);
  // El pedido que es de un solo origen sí conserva su margen en el detalle.
  assert.notEqual(mock.orders.find((row) => row.orderId === "o2")!.margin, null);
  // Ningún reparto proporcional ni suma: ni 30/70 de un coste repartido, ni 100 (60 + 40) como cifra del pedido mixto.
  assert.ok(!amounts(summary).some((text) => text === "30.0000" || text === "-30.0000"), amounts(summary).join(" "));
});

test("un reembolso de un origen reduce solo el neto de ese origen", () => {
  const summary = marginSummary(
    [
      entry("o1", "CAPTURE", "100.0000", { provider_kind: "mock" }),
      entry("o1", "REFUND", "10.0000", { provider_kind: "mock" }),
      entry("o2", "CAPTURE", "100.0000", { provider_kind: "sandbox" }),
    ],
    [order("o1", [item()]), order("o2", [item()])],
    complete,
  );
  assert.equal(toText(of(summary, "mock").net!.value), "90.0000");
  assert.equal(toText(of(summary, "sandbox").net!.value), "100.0000", "el reembolso de mock no toca sandbox");
});

test("el coste parcial de un origen bloquea ese origen y no a los demás", () => {
  const summary = marginSummary(
    [entry("o1", "CAPTURE", "100.0000", { provider_kind: "mock" }), entry("o2", "CAPTURE", "100.0000", { provider_kind: "real" })],
    [order("o1", [item(), item({ line_number: 2, unit_cost: null, cost_provenance: null })]), order("o2", [item()])],
    complete,
  );
  assert.equal(of(summary, "mock").margin, null);
  assert.equal(of(summary, "mock").blockedBy, "missing_costs");
  assert.equal(of(summary, "real").blockedBy, null);
  assert.equal(toText(of(summary, "real").margin!.value), "70.0000");
});

test("sin ningún coste no hay margen en ningún origen, y no se enseña un cero", () => {
  const summary = marginSummary(
    ORIGINS.map((origin) => entry(`o-${origin}`, "CAPTURE", "100.0000", { provider_kind: origin })),
    ORIGINS.map((origin) => order(`o-${origin}`, [item({ unit_cost: null, cost_provenance: null })])),
    complete,
  );
  for (const origin of summary.origins) {
    assert.equal(origin.margin, null);
    assert.equal(origin.cost, null);
    assert.equal(origin.blockedBy, "missing_costs");
    assert.equal(origin.coverage.percent, 0);
  }
  assert.deepEqual(amounts(summary).filter((text) => text.startsWith("0.")), [], "ningún cero inventado");
});

test("una entrada con un origen desconocido no se asigna a ninguno y bloquea los márgenes", () => {
  const summary = marginSummary(
    [
      entry("o1", "CAPTURE", "100.0000", { provider_kind: "mock" }),
      entry("o2", "CAPTURE", "100.0000", { provider_kind: "composite" as never }),
      entry("o3", "CAPTURE", "100.0000", { provider_kind: undefined as never, id: "no-origin" }),
    ],
    [order("o1", [item()]), order("o2", [item()]), order("o3", [item()])],
    complete,
  );
  assert.equal(summary.unknownOrigin, 2);
  assert.deepEqual(summary.origins.map((origin) => origin.origin), ["mock"], "ni mock, ni sandbox, ni real se completan");
  assert.equal(of(summary, "mock").blockedBy, "unknown_origin");
  assert.equal(of(summary, "mock").margin, null);
});

test("solo hay un origen desconocido: el motivo es ése, no «ningún pedido»", () => {
  const summary = marginSummary([entry("o1", "CAPTURE", "100.0000", { provider_kind: "composite" as never })], [order("o1", [item()])], complete);
  assert.deepEqual(summary.origins, []);
  assert.equal(summary.blockedBy, "unknown_origin");
});

test("Order.is_simulated invertido no cambia ninguna cifra, ningún origen ni ningún motivo", () => {
  const entries = [entry("o1", "CAPTURE", "100.0000", { provider_kind: "sandbox" }), entry("o2", "CAPTURE", "50.0000", { provider_kind: "mock" })];
  const asSimulation = marginSummary(entries, [order("o1", [item()], { is_simulated: true }), order("o2", [item()], { is_simulated: true })], complete);
  const outsideSimulation = marginSummary(entries, [order("o1", [item()], { is_simulated: false }), order("o2", [item()], { is_simulated: false })], complete);
  assert.deepEqual(outsideSimulation, asSimulation);
  assert.deepEqual(outsideSimulation.origins.map((origin) => origin.origin), ["mock", "sandbox"]);
});

test("el origen sale de las entradas del registro, no de los cobros que cuenta el pedido ni de su proveedor", () => {
  const paid = (kind: "mock" | "sandbox" | "real", provider: string) =>
    ({ provider, provider_kind: kind, captured_amount: money("100.0000") }) as unknown as Order["payments"][number];
  const summary = marginSummary(
    [entry("o1", "CAPTURE", "100.0000", { provider_kind: "sandbox" })],
    [order("o1", [item()], { payments: [paid("real", "simulated-payments")] })],
    complete,
  );
  assert.deepEqual(summary.origins.map((origin) => origin.origin), ["sandbox"], "los cobros del pedido no deciden el origen del margen");
});

test("cada cifra de un origen lleva ese origen en su tipo", () => {
  const summary = marginSummary(
    [entry("o1", "CAPTURE", "100.0000", { provider_kind: "mock" }), entry("o2", "CAPTURE", "100.0000", { provider_kind: "real" })],
    [order("o1", [item()]), order("o2", [item()])],
    complete,
  );
  for (const origin of summary.origins) {
    assert.equal(origin.revenue!.origin, origin.origin);
    assert.ok(origin.orders.every((row) => row.net.origin === origin.origin));
  }
});

test("el neto y el margen de cada pedido restan sus reembolsos, no solo los del total del origen", () => {
  const mock = of(
    marginSummary(
      [entry("o1", "CAPTURE", "100.0000"), entry("o1", "REFUND", "10.0000")],
      [order("o1", [item({ unit_cost: money("30.0000"), quantity: 2 })])],
      complete,
    ),
    "mock",
  );
  const [row] = mock.orders;
  assert.equal(toText(row.revenue.value), "100.0000");
  assert.equal(toText(row.refunds.value), "10.0000");
  assert.equal(toText(row.net.value), "90.0000", "el neto de la fila es ingreso − reembolsos");
  assert.equal(toText(row.margin!.value), "30.0000", "el margen de la fila parte de ese neto: 90 − 60");
  assert.equal(row.net.origin, "mock");
});

test("el reembolso de un pedido de otro origen no resta al neto de la fila de este origen", () => {
  const summary = marginSummary(
    [
      entry("o1", "CAPTURE", "100.0000", { provider_kind: "sandbox" }),
      entry("o2", "CAPTURE", "100.0000", { provider_kind: "real" }),
      entry("o2", "REFUND", "40.0000", { provider_kind: "real" }),
    ],
    [order("o1", [item()]), order("o2", [item()])],
    complete,
  );
  assert.equal(toText(of(summary, "sandbox").orders[0].net.value), "100.0000");
  assert.equal(toText(of(summary, "real").orders[0].net.value), "60.0000");
});
