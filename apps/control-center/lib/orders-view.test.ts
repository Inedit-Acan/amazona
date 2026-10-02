import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { test } from "node:test";
import type { MoneyAmount, Order, OrderFulfillment, OrderPayment, OrderRefund } from "./api.ts";
import {
  ABSENT,
  FULFILLMENT_STATUS,
  ORDER_STATUS,
  PERIODS,
  TABS,
  addTo,
  attentionList,
  attentionText,
  describe,
  formatAmount,
  formatMinor,
  formatTotals,
  fulfilmentPipeline,
  fulfilmentTotal,
  newestFirst,
  orderEvents,
  orderKpis,
  ordersInPeriod,
  toMinor,
  type MoneyTotals,
} from "./orders-view.ts";

// --- Datos de ejemplo: lo que devolvería `GET /api/orders` (nada aleatorio) ---------------------------------------------

const eur = (amount: string): MoneyAmount => ({ amount, currency: "EUR" });

function payment(overrides: Partial<OrderPayment> = {}): OrderPayment {
  return {
    id: "pay-1",
    attempt_number: 1,
    provider: "mock",
    status: "SUCCEEDED",
    amount: eur("50.0000"),
    captured_amount: eur("50.0000"),
    refund_committed_amount: eur("0.0000"),
    refunded_amount: eur("0.0000"),
    provider_payment_ref: "simpay_1",
    duplicate_of_payment_id: null,
    last_failure_code: null,
    opened_at: "2026-10-02T10:00:05Z",
    succeeded_at: "2026-10-02T10:00:09Z",
    closed_at: "2026-10-02T10:00:09Z",
    created_at: "2026-10-02T10:00:01Z",
    ...overrides,
  };
}

function refund(overrides: Partial<OrderRefund> = {}): OrderRefund {
  return {
    id: "ref-1",
    payment_id: "pay-1",
    origin: "OPERATOR",
    status: "SUCCEEDED",
    amount: eur("10.0000"),
    reason: "customer_request",
    provider_refund_ref: "simref_1",
    failure_code: null,
    requested_at: "2026-10-02T12:00:00Z",
    finished_at: "2026-10-02T12:00:30Z",
    ...overrides,
  };
}

function fulfillment(overrides: Partial<OrderFulfillment> = {}): OrderFulfillment {
  return {
    id: "ful-1",
    order_id: "ord-1",
    provider: "mock",
    supplier_id: "sup-1",
    status: "COMPLETED",
    unknown_phase: null,
    purchase_reference: "simpo_1",
    tracking_reference: "simtrk_1",
    failed_attempts: 0,
    last_failure_code: null,
    items: [{ order_item_id: "oi-1", line_number: 1, quantity: 4 }],
    created_by: "owner@amazona.local",
    completed_by: "owner@amazona.local",
    created_at: "2026-10-02T11:00:00Z",
    purchased_at: "2026-10-02T11:01:00Z",
    shipped_at: "2026-10-02T11:02:00Z",
    completed_at: "2026-10-02T11:03:00Z",
    ...overrides,
  };
}

function order(overrides: Partial<Order> = {}): Order {
  return {
    id: "ord-1",
    customer_ref: "sim_customer",
    market: "eu",
    status: "COMPLETED",
    is_simulated: true,
    amount_due: eur("50.0000"),
    items: [],
    payments: [payment()],
    refunds: [],
    fulfillments: [fulfillment()],
    created_at: "2026-10-02T10:00:00Z",
    paid_at: "2026-10-02T10:00:09Z",
    completed_at: "2026-10-02T11:03:00Z",
    cancelled_at: null,
    correlation_id: "corr-1",
    attention_required: false,
    attention_reasons: [],
    ...overrides,
  };
}

// --- Dinero exacto ---------------------------------------------------------------------------------------------

test("los importes se leen y se suman exactos: 0,1 + 0,2 es 0,3, sin error de coma flotante", () => {
  const totals: MoneyTotals = new Map();
  addTo(totals, eur("0.1"));
  addTo(totals, eur("0.2"));

  assert.equal(totals.get("EUR"), toMinor("0.3"));
  assert.equal(formatTotals(totals), formatMinor(toMinor("0.3000"), "EUR"));
  assert.equal(toMinor("50.0000"), toMinor("50"));
  assert.equal(toMinor("-12.3456") + toMinor("12.3456"), toMinor("0"));
});

test("un importe que no es decimal exacto se rechaza en lugar de adivinarse", () => {
  for (const bad of ["1e3", "1,5", "abc", "", "1.23456", "--1", "1.", ".5", "NaN", "Infinity"]) {
    assert.throws(() => toMinor(bad), TypeError, bad);
  }
});

test("un importe se muestra con dos decimales y con cuatro solo cuando hacen falta; nunca mezcla monedas", () => {
  assert.match(formatMinor(toMinor("50"), "EUR"), /^50,00\s€$/);
  assert.match(formatMinor(toMinor("1234.5"), "EUR"), /^1\.234,50\s€$/);
  assert.match(formatMinor(toMinor("0.0125"), "EUR"), /^0,0125\s€$/);
  assert.match(formatMinor(toMinor("-3"), "EUR"), /^-3,00\s€$/);
  const totals: MoneyTotals = new Map();
  addTo(totals, { amount: "20", currency: "USD" });
  addTo(totals, eur("10"));
  const text = formatTotals(totals)!;
  assert.equal(text.split(" · ").length, 2, "one amount per currency, not a sum across currencies");
  assert.match(text, /10,00\s€ · .*20,00/);
  assert.equal(formatTotals(new Map()), null, "no money at all is not zero euros");
  assert.match(formatAmount(eur("7.5")), /^7,50\s€$/);
});

// --- Cifras ----------------------------------------------------------------------------------------------------

test("los indicadores salen de los pedidos: cuántos hay en cada estado y el dinero realmente cobrado y devuelto", () => {
  const orders = [
    order({ id: "a" }),
    order({ id: "b", status: "PAID", completed_at: null, fulfillments: [], payments: [payment({ captured_amount: eur("30.0000"), refunded_amount: eur("5.0000"), refund_committed_amount: eur("12.0000") })] }),
    order({ id: "c", status: "AWAITING_PAYMENT", paid_at: null, completed_at: null, payments: [], fulfillments: [] }),
    order({ id: "d", status: "CANCELLED", cancelled_at: "2026-10-02T13:00:00Z", paid_at: null, completed_at: null, payments: [], fulfillments: [], attention_required: true, attention_reasons: ["captured_on_cancelled_order"] }),
  ];

  const kpis = orderKpis(orders);

  assert.deepEqual(
    [kpis.total, kpis.completed, kpis.paid, kpis.awaitingPayment, kpis.cancelled, kpis.attention],
    [4, 1, 1, 1, 1, 1],
  );
  assert.equal(kpis.captured.get("EUR"), toMinor("80"), "50 + 30 captured");
  assert.equal(kpis.refunded.get("EUR"), toMinor("5"), "only what a verified fact confirmed");
  assert.equal(kpis.refundInProgress.get("EUR"), toMinor("7"), "12 asked − 5 confirmed is still on its way");
});

test("sin pedidos no hay cifras inventadas: todo a cero y sin importes", () => {
  const kpis = orderKpis([]);

  assert.deepEqual([kpis.total, kpis.paid, kpis.completed, kpis.cancelled, kpis.awaitingPayment, kpis.attention], [0, 0, 0, 0, 0, 0]);
  assert.equal(formatTotals(kpis.captured), null);
  assert.equal(formatTotals(kpis.refunded), null);
  assert.equal(formatTotals(kpis.refundInProgress), null);
  assert.deepEqual(fulfilmentPipeline([]).filter((stage) => stage.count > 0), []);
  assert.deepEqual(attentionList([]), []);
});

test("un cobro duplicado cuenta como dinero cobrado: la evidencia no se descarta", () => {
  const duplicate = order({
    payments: [payment({ id: "p1" }), payment({ id: "p2", status: "DUPLICATE_CAPTURE", duplicate_of_payment_id: "p1" })],
    attention_required: true,
    attention_reasons: ["duplicate_capture"],
  });

  assert.equal(orderKpis([duplicate]).captured.get("EUR"), toMinor("100"));
});

// --- Periodos y pestañas ------------------------------------------------------------------------------------------

test("el periodo filtra por la fecha real de creación y «todo el historial» no filtra nada", () => {
  const orders = [
    order({ id: "today", created_at: "2026-10-02T09:00:00Z" }),
    order({ id: "d6", created_at: "2026-09-26T23:59:00Z" }),
    order({ id: "d7", created_at: "2026-09-25T23:59:00Z" }),
    order({ id: "old", created_at: "2026-08-01T10:00:00Z" }),
  ];

  const ids = (days: number | null) => ordersInPeriod(orders, "2026-10-02", days).map((o) => o.id);

  assert.deepEqual(ids(1), ["today"]);
  assert.deepEqual(ids(7), ["today", "d6"], "seven days ending today: 26 Sep is in, 25 Sep is out");
  assert.deepEqual(ids(30), ["today", "d6", "d7"]);
  assert.deepEqual(ids(null), ["today", "d6", "d7", "old"]);
  assert.equal(PERIODS[0].value, "all");
});

test("cada pestaña separa los pedidos por su estado real, y «requieren atención» por lo que calcula el backend", () => {
  const orders = [
    order({ id: "a" }),
    order({ id: "b", status: "PAID", attention_required: true, attention_reasons: ["fulfilment_ship_failed"] }),
    order({ id: "c", status: "AWAITING_PAYMENT" }),
    order({ id: "d", status: "CANCELLED" }),
  ];

  const inTab = (key: string) => orders.filter(TABS.find((t) => t.key === key)!.match).map((o) => o.id);

  assert.deepEqual(inTab("todos"), ["a", "b", "c", "d"]);
  assert.deepEqual(inTab("completados"), ["a"]);
  assert.deepEqual(inTab("pagados"), ["b"]);
  assert.deepEqual(inTab("cobro"), ["c"]);
  assert.deepEqual(inTab("cancelados"), ["d"]);
  assert.deepEqual(inTab("atencion"), ["b"]);
});

test("los pedidos van del más reciente al más antiguo, y a igual instante por id", () => {
  const sorted = newestFirst([
    order({ id: "b", created_at: "2026-10-02T10:00:00Z" }),
    order({ id: "c", created_at: "2026-10-03T10:00:00Z" }),
    order({ id: "a", created_at: "2026-10-02T10:00:00Z" }),
  ]);

  assert.deepEqual(sorted.map((o) => o.id), ["c", "a", "b"]);
});

// --- Fulfillment y atención ------------------------------------------------------------------------------------

test("el pipeline cuenta fulfillments reales por estado, incluidos los que salen del recorrido y los que no se conocen", () => {
  const orders = [
    order({ fulfillments: [fulfillment({ status: "READY" }), fulfillment({ id: "f2", status: "PURCHASED" })] }),
    order({ id: "o2", fulfillments: [fulfillment({ id: "f3", status: "UNKNOWN_OUTCOME", unknown_phase: "purchase" }), fulfillment({ id: "f4", status: "QUARANTINED" as never })] }),
  ];

  const stages = fulfilmentPipeline(orders);
  const count = (status: string) => stages.find((s) => s.status === status)?.count;

  assert.equal(count("READY"), 1);
  assert.equal(count("PURCHASED"), 1);
  assert.equal(count("UNKNOWN_OUTCOME"), 1);
  assert.equal(count("COMPLETED"), 0);
  assert.equal(count("QUARANTINED"), 1, "a state this screen does not know is shown, not hidden");
  assert.equal(fulfilmentTotal(orders), 4);
  assert.deepEqual(stages.slice(0, 3).map((s) => s.status), ["READY", "PURCHASING", "PURCHASED"], "journey order");
});

test("los motivos de atención se explican en claro y uno desconocido se muestra tal cual", () => {
  assert.match(attentionText("duplicate_capture"), /segundo cobro/);
  assert.match(attentionText("fulfilment_outcome_unknown"), /No se sabe/);
  assert.equal(attentionText("some_new_reason"), "some_new_reason");
  assert.deepEqual(describe(ORDER_STATUS, "PAID"), { label: "Pagado", tone: "ok" });
  assert.deepEqual(describe(ORDER_STATUS, "SOMETHING_NEW"), { label: "SOMETHING_NEW", tone: "neutral" });
  assert.equal(describe(FULFILLMENT_STATUS, "UNKNOWN_OUTCOME").tone, "bad", "an unknown outcome is never presented as calm");
});

test("la lista de atención pone primero los pedidos con más motivos", () => {
  const list = attentionList([
    order({ id: "ok" }),
    order({ id: "one", attention_required: true, attention_reasons: ["refund_unconfirmed"], created_at: "2026-10-03T00:00:00Z" }),
    order({ id: "two", attention_required: true, attention_reasons: ["duplicate_capture", "capture_mismatch"], created_at: "2026-10-01T00:00:00Z" }),
  ]);

  assert.deepEqual(list.map((o) => o.id), ["two", "one"]);
});

// --- La historia de un pedido ------------------------------------------------------------------------------------

test("la historia de un pedido son sus hechos con fecha, en orden, y nada más", () => {
  const events = orderEvents(
    order({
      refunds: [refund(), refund({ id: "ref-2", status: "SENDING", finished_at: null, requested_at: "2026-10-02T14:00:00Z", amount: eur("3.0000") })],
      payments: [payment(), payment({ id: "pay-0", attempt_number: 0, status: "FAILED", succeeded_at: null, opened_at: null, closed_at: "2026-10-02T09:59:00Z", created_at: "2026-10-02T09:58:00Z" })],
    }),
  );

  const times = events.map((e) => Date.parse(e.at));
  assert.deepEqual(times, [...times].sort((a, b) => a - b), "chronological");
  const labels = events.map((e) => e.label);
  assert.ok(labels.includes("Pedido creado") && labels.includes("Pedido pagado") && labels.includes("Pedido completado"));
  assert.ok(labels.includes("Fulfillment 1: comprado al proveedor") && labels.includes("Fulfillment 1: enviado"));
  assert.ok(labels.includes("Fulfillment 1: entrega confirmada"));
  assert.equal(labels.filter((l) => l === "Reembolso solicitado").length, 2);
  assert.ok(labels.some((l) => l.startsWith("Reembolso devuelto")), "a confirmed refund says so");
  assert.ok(!labels.some((l) => l.toLowerCase().includes("cancelado")), "no cancellation was recorded, none is shown");
});

test("un pedido sin fulfillment ni cobro solo cuenta lo que ocurrió: que se creó", () => {
  const events = orderEvents(order({ status: "AWAITING_PAYMENT", payments: [], fulfillments: [], refunds: [], paid_at: null, completed_at: null }));

  assert.deepEqual(events.map((e) => e.label), ["Pedido creado"]);
});

test("una compra o un envío sin fecha no genera un hito: no hay hecho que contar", () => {
  const events = orderEvents(order({ completed_at: null, fulfillments: [fulfillment({ status: "PURCHASING", purchased_at: null, shipped_at: null, completed_at: null, completed_by: null })] }));

  assert.deepEqual(events.filter((e) => e.label.startsWith("Fulfillment")).map((e) => e.label), ["Fulfillment 1 creado"]);
});

// --- Lo que no existe se dice -----------------------------------------------------------------------------------

test("lo que M44 no tiene se declara como ausente, con su razón, y no lleva ninguna cifra", () => {
  assert.deepEqual(
    ABSENT.map((item) => item.key),
    ["carriers", "returns", "sla", "suppliers", "customers", "automations"],
  );
  for (const item of ABSENT) {
    assert.deepEqual(Object.keys(item).sort(), ["key", "title", "why"], "text only: no figure can hide here");
    assert.ok(item.why.length > 20);
    assert.doesNotMatch(item.why, /\d+\s*%/, "no invented percentage");
  }
});

// --- La frontera real / demo --------------------------------------------------------------------------------------

const OPERATIONS_DIR = new URL("../app/operations/", import.meta.url);

/** Falla con un mensaje corto: `assert.doesNotMatch` volcaría el fichero entero. */
function assertAbsent(source: string, pattern: RegExp, message: string): void {
  assert.ok(!pattern.test(source), message);
}

function assertPresent(source: string, pattern: RegExp, message: string): void {
  assert.ok(pattern.test(source), message);
}

function operationsSources(): { file: string; source: string }[] {
  return readdirSync(OPERATIONS_DIR)
    .filter((file) => /\.tsx?$/.test(file))
    .map((file) => ({ file, source: readFileSync(new URL(file, OPERATIONS_DIR), "utf8") }));
}

test("el panel Operaciones no depende de nada de demostración ni de datos generados", () => {
  const files = [...operationsSources(), { file: "lib/orders-view.ts", source: readFileSync(new URL("./orders-view.ts", import.meta.url), "utf8") }];

  assert.ok(files.length >= 5);
  for (const { file, source } of files) {
    assertAbsent(source, /lib\/demo|\.\/demo\//, `${file} imports demo data`);
    assertAbsent(source, /operations-view/, `${file} uses the generator of invented orders`);
    assertAbsent(source, /buildOrders|demoRandom|Math\.random|DEMO_[A-Z_]+/, `${file} generates or imports invented data`);
    assertAbsent(source, /DataProvenanceBadge[^>]*status="demo"/, `${file} labels something as demo: nothing here is`);
  }
});

test("el panel lee los pedidos del backend y no escribe nada desde esta pantalla", () => {
  const page = operationsSources().find((f) => f.file === "page.tsx")!.source;

  assertPresent(page, /api\.listOrders\(/, "real orders come from GET /api/orders");
  for (const { file, source } of operationsSources()) {
    assertAbsent(source, /method:\s*"(POST|PUT|PATCH|DELETE)"/, `${file} writes`);
    assertAbsent(source, /api\.(create|open|request|purchase|ship|complete|cancel|fail)\w*\(/, `${file} calls an effectful operation`);
  }
});
