import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { test } from "node:test";
import type { MoneyAmount, Order, OrderPage, OrderPayment } from "./api.ts";
import {
  PERIODS,
  PARTIAL_FIGURE_NOTE,
  appendPage,
  countText,
  formatTotals,
  loadedFromPage,
  loadedSummary,
  newestFirst,
  orderKpis,
  ordersInPeriod,
  pageErrorText,
  periodCoverage,
  type OrdersLoaded,
} from "./orders-view.ts";

// Paginación de Operaciones (M45, P2-2): lo cargado frente a lo que existe. Nada aleatorio.

const money = (amount: string, currency = "EUR"): MoneyAmount => ({ amount, currency });

function payment(captured: string, currency = "EUR"): OrderPayment {
  return {
    id: `pay-${captured}-${currency}`,
    attempt_number: 1,
    provider: "mock",
    status: "SUCCEEDED",
    amount: money(captured, currency),
    captured_amount: money(captured, currency),
    refund_committed_amount: money("0.0000", currency),
    refunded_amount: money("0.0000", currency),
    provider_payment_ref: null,
    duplicate_of_payment_id: null,
    last_failure_code: null,
    opened_at: null,
    succeeded_at: "2026-10-03T09:00:00Z",
    closed_at: null,
    created_at: "2026-10-03T09:00:00Z",
  };
}

function order(id: string, createdAt: string, overrides: Partial<Order> = {}): Order {
  return {
    id,
    customer_ref: "sim_customer",
    market: "eu",
    status: "PAID",
    is_simulated: true,
    amount_due: money("50.0000"),
    items: [],
    payments: [],
    refunds: [],
    fulfillments: [],
    created_at: createdAt,
    paid_at: null,
    completed_at: null,
    cancelled_at: null,
    correlation_id: `corr-${id}`,
    attention_required: false,
    attention_reasons: [],
    ...overrides,
  };
}

function page(items: Order[], hasMore: boolean, cursor: string | null = hasMore ? "next" : null): OrderPage {
  return { items, limit: 100, count: items.length, has_more: hasMore, next_cursor: cursor };
}

const TODAY = "2026-10-03";

// --- Vacío, una página completa, una página truncada -----------------------------------------------------------------

test("sin pedidos y sin más: todo está cargado, la cifra es completa y la frase no inventa un total", () => {
  const loaded = loadedFromPage(page([], false));

  assert.deepEqual(loaded, { orders: [], hasMore: false, nextCursor: null });
  assert.equal(periodCoverage(loaded, TODAY, null), "complete");
  assert.equal(loadedSummary(0, false), "0 pedidos · son todos los que existen");
});

test("una página completa sin más pedidos es el total: contadores sin «+» y todos los periodos completos", () => {
  const loaded = loadedFromPage(page([order("a", "2026-10-03T08:00:00Z"), order("b", "2026-10-01T08:00:00Z")], false));

  for (const period of PERIODS) assert.equal(periodCoverage(loaded, TODAY, period.days), "complete", period.value);
  assert.equal(countText("2", "complete"), "2");
  assert.equal(loadedSummary(2, false), "2 pedidos · son todos los que existen");
  assert.equal(loadedSummary(1, false), "1 pedido · son todos los que existen");
});

test("con más pedidos sin cargar, «todo el historial» es parcial y la frase dice «hay más», nunca «X de Y»", () => {
  const loaded = loadedFromPage(page([order("a", "2026-10-03T08:00:00Z")], true));

  assert.equal(periodCoverage(loaded, TODAY, null), "partial");
  assert.equal(countText("100", "partial"), "100+", "a lower bound, not a total");
  const text = loadedSummary(100, true);
  assert.match(text, /hay más/);
  assert.doesNotMatch(text, /\bde\b\s*\d|\bde\b\s*total|todos/, "no total is claimed");
});

test("un contador parcial se muestra como un mínimo y uno completo, tal cual", () => {
  assert.equal(countText("0", "partial"), "0+");
  assert.equal(countText("1.250", "partial"), "1.250+");
  assert.equal(countText("1.250", "complete"), "1.250");
});

// --- Un periodo es completo cuando lo cargado lo cubre ------------------------------------------------------------------

test("un periodo es completo si el pedido más antiguo cargado es anterior a su comienzo, aunque haya más pedidos viejos", () => {
  // Cargados: de hoy a hace 40 días. Hay más (más antiguos) sin cargar.
  const loaded = loadedFromPage(
    page([order("a", "2026-10-03T08:00:00Z"), order("b", "2026-09-20T08:00:00Z"), order("c", "2026-08-24T08:00:00Z")], true),
  );

  assert.equal(periodCoverage(loaded, TODAY, 1), "complete", "all of today is loaded: something older is already here");
  assert.equal(periodCoverage(loaded, TODAY, 7), "complete");
  assert.equal(periodCoverage(loaded, TODAY, 30), "complete");
  assert.equal(periodCoverage(loaded, TODAY, null), "partial", "the whole history is not loaded");
});

test("un periodo es parcial si lo cargado no llega a su comienzo: faltarían pedidos de dentro", () => {
  const loaded = loadedFromPage(
    page([order("a", "2026-10-03T08:00:00Z"), order("b", "2026-10-02T08:00:00Z")], true),
  );

  assert.equal(periodCoverage(loaded, TODAY, 7), "partial");
  assert.equal(periodCoverage(loaded, TODAY, 30), "partial");
});

test("el límite del periodo es estricto: un pedido justo en el borde no prueba que se haya cargado todo el periodo", () => {
  // La ventana de 7 días empieza el 2026-09-27 a las 00:00 UTC. A igual instante podría haber otro sin cargar.
  const atEdge = loadedFromPage(page([order("a", "2026-10-03T08:00:00Z"), order("b", "2026-09-27T00:00:00Z")], true));
  const before = loadedFromPage(page([order("a", "2026-10-03T08:00:00Z"), order("b", "2026-09-26T23:59:59Z")], true));

  assert.equal(periodCoverage(atEdge, TODAY, 7), "partial");
  assert.equal(periodCoverage(before, TODAY, 7), "complete");
});

test("con más pedidos y ninguno cargado, ningún periodo se da por completo", () => {
  const loaded: OrdersLoaded = { orders: [], hasMore: true, nextCursor: "x" };

  assert.equal(periodCoverage(loaded, TODAY, 7), "partial");
});

// --- Cargar la siguiente página ------------------------------------------------------------------------------------------

test("cargar la siguiente página añade sus pedidos, conserva el orden y toma el «hay más» de la última página", () => {
  const first = loadedFromPage(page([order("c", "2026-10-03T09:00:00Z"), order("b", "2026-10-03T08:00:00Z")], true, "p2"));

  const second = appendPage(first, page([order("a", "2026-10-03T07:00:00Z")], false));

  assert.deepEqual(
    second.orders.map((o) => o.id),
    ["c", "b", "a"],
  );
  assert.equal(second.hasMore, false);
  assert.equal(second.nextCursor, null);
});

test("un pedido que llega dos veces no se cuenta dos veces, ni siquiera en una página repetida", () => {
  const first = loadedFromPage(page([order("b", "2026-10-03T08:00:00Z"), order("a", "2026-10-03T07:00:00Z")], true, "p2"));

  const again = appendPage(first, page([order("a", "2026-10-03T07:00:00Z"), order("z", "2026-10-03T06:00:00Z")], true, "p3"));
  const repeated = appendPage(again, page([order("a", "2026-10-03T07:00:00Z"), order("z", "2026-10-03T06:00:00Z")], true, "p3"));

  assert.deepEqual(
    again.orders.map((o) => o.id),
    ["b", "a", "z"],
  );
  assert.deepEqual(repeated.orders.map((o) => o.id), again.orders.map((o) => o.id));
  assert.equal(repeated.hasMore, true);
  assert.equal(repeated.nextCursor, "p3");
});

test("a igual instante, el id desempata igual que en el backend (el menor primero)", () => {
  const loaded = appendPage(
    loadedFromPage(page([order("m", "2026-10-03T08:00:00Z")], true)),
    page([order("a", "2026-10-03T08:00:00Z"), order("z", "2026-10-03T08:00:00Z")], false),
  );

  assert.deepEqual(
    loaded.orders.map((o) => o.id),
    newestFirst(loaded.orders).map((o) => o.id),
  );
  assert.deepEqual(
    loaded.orders.map((o) => o.id),
    ["a", "m", "z"],
  );
});

test("una página vacía al final es válida: termina el recorrido sin quitar nada de lo cargado", () => {
  const first = loadedFromPage(page([order("a", "2026-10-03T08:00:00Z")], true, "p2"));

  const end = appendPage(first, page([], false));

  assert.deepEqual(end.orders.map((o) => o.id), ["a"]);
  assert.equal(end.hasMore, false);
});

// --- Las cifras siguen siendo exactas ----------------------------------------------------------------------------------

test("el dinero sumado a través de varias páginas es exacto y no mezcla monedas", () => {
  const first = loadedFromPage(
    page([order("a", "2026-10-03T09:00:00Z", { payments: [payment("0.1000")] }), order("b", "2026-10-03T08:00:00Z", { payments: [payment("20.0000", "USD")] })], true),
  );
  const loaded = appendPage(first, page([order("c", "2026-10-03T07:00:00Z", { payments: [payment("0.2000")] })], false));

  const kpis = orderKpis(loaded.orders);

  const shown = formatTotals(kpis.captured) ?? "";
  assert.match(shown, /0,30/);
  assert.match(shown, /20,00/);
  assert.equal(shown.split(" · ").length, 2, "one figure per currency");
  assert.equal(kpis.captured.get("EUR"), BigInt(3000), "0,1 + 0,2 is exactly 0,3 across pages");
  assert.equal(kpis.captured.get("USD"), BigInt(200000));
  assert.equal(kpis.captured.size, 2, "two currencies, two figures");
});

test("el periodo se calcula sobre lo cargado y respeta el orden más reciente primero", () => {
  const loaded = appendPage(
    loadedFromPage(page([order("a", "2026-10-03T09:00:00Z"), order("b", "2026-09-01T09:00:00Z")], true)),
    page([order("c", "2026-10-02T09:00:00Z")], false),
  );

  const week = ordersInPeriod(loaded.orders, TODAY, 7);

  assert.deepEqual(week.map((o) => o.id).sort(), ["a", "c"]);
});

// --- Errores: cada causa con sus palabras -------------------------------------------------------------------------------

test("un 422 no es un fallo del backend, un 5xx no es una petición inválida, y ninguno es una página vacía", () => {
  const invalid = pageErrorText(422, "cursor");
  const server = pageErrorText(500, "boom");
  const offline = pageErrorText(undefined, "fetch failed");
  const forbidden = pageErrorText(403, "no");

  assert.match(invalid, /no ser válida/);
  assert.match(server, /falló/);
  assert.match(server, /HTTP 500/);
  assert.match(offline, /No se pudo contactar/);
  assert.match(forbidden, /permiso/);
  assert.equal(new Set([invalid, server, offline, forbidden]).size, 4, "four different messages");
  for (const text of [invalid, server, offline, forbidden]) assert.doesNotMatch(text, /vacía|sin pedidos|no hay pedidos/i);
});

test("un fallo al cargar no pierde lo ya cargado: el error no forma parte del estado de pedidos", () => {
  const loaded = loadedFromPage(page([order("a", "2026-10-03T08:00:00Z")], true));

  // `appendPage` solo se llama con una página recibida: un error nunca la toca.
  assert.deepEqual(loaded.orders.map((o) => o.id), ["a"]);
  assert.equal(loaded.hasMore, true);
  assert.ok(PARTIAL_FIGURE_NOTE.length > 10);
});

// --- Guardas de arquitectura: ninguna cifra «global» desde una colección paginada ------------------------------------------

const OPERATIONS_DIR = new URL("../app/operations/", import.meta.url);

function operationsSources(): { file: string; source: string }[] {
  return readdirSync(OPERATIONS_DIR)
    .filter((file) => /\.tsx?$/.test(file))
    .map((file) => ({ file, source: readFileSync(new URL(file, OPERATIONS_DIR), "utf8") }));
}

test("la pantalla pide la primera página, no pasa offset y no trata una página como el total", () => {
  const page = operationsSources().find((f) => f.file === "page.tsx")!.source;

  assert.match(page, /api\.listOrders\(\{ limit: PAGE_SIZE \}\)/, "one page, of a size the screen chose");
  assert.match(page, /initialHasMore=\{firstPage\.has_more\}/, "the server page passes has_more on");
  assert.match(page, /initialNextCursor=\{firstPage\.next_cursor\}/);
  assert.doesNotMatch(page, /offset|ORDERS_LIMIT|limit:\s*500/, "no silent truncation constant, no offset");
});

test("toda cifra calculada sobre pedidos cargados vive donde se conoce la cobertura", () => {
  const computing = /\b(orderKpis|fulfilmentPipeline|attentionList|fulfilmentTotal)\(/;
  const files = operationsSources().filter((f) => computing.test(f.source));

  assert.ok(files.length >= 1, "the workspace computes figures");
  for (const { file, source } of files) {
    assert.match(source, /periodCoverage\(/, `${file} computes figures without knowing what they cover`);
    assert.match(source, /hasMore/, `${file} computes figures without knowing whether there is more`);
    assert.match(source, /countText\(/, `${file} shows counts as totals even when they are minimums`);
  }
});

test("las tarjetas que cuentan pedidos saben si son parciales", () => {
  const panels = operationsSources().find((f) => f.file === "operations-panels.tsx")!.source;

  for (const card of ["PipelineCard", "AttentionCard"]) {
    const block = panels.slice(panels.indexOf(`export function ${card}`));
    assert.match(block.slice(0, 700), /partial/, `${card} cannot say it is partial`);
  }
});

test("ningún texto de la pantalla afirma un total que no se conoce", () => {
  for (const { file, source } of operationsSources()) {
    assert.doesNotMatch(source, /Mostrando[^`"\n]*\$\{[^}]+\}\s+de\s+\$\{/, `${file} says «X de Y»`);
    assert.doesNotMatch(source, /Mostrando \d+ de \d+/, `${file} says «X de Y»`);
    assert.doesNotMatch(source, /total hist[oó]rico|todos los pedidos\b/i, `${file} claims a historic total`);
  }
  const workspace = operationsSources().find((f) => f.file === "operations-workspace.tsx")!.source;
  assert.match(workspace, /Todo lo cargado/, "«todo el historial» is renamed while there is more to load");
});

test("la pantalla pagina con el cursor del backend y no inventa pedidos al paginar", () => {
  const workspace = operationsSources().find((f) => f.file === "operations-workspace.tsx")!.source;

  assert.match(workspace, /api\.listOrders\(\{ limit: pageSize, cursor: loaded\.nextCursor \}\)/);
  assert.match(workspace, /appendPage\(/, "a page is merged, never replaces what was loaded");
  for (const { file, source } of operationsSources()) {
    assert.doesNotMatch(source, /buildOrders|demoRandom|Math\.random|lib\/demo|operations-view/, `${file} synthesises orders`);
  }
});

test("el cliente de la API ya no tiene offset y devuelve una página", () => {
  const api = readFileSync(new URL("./api.ts", import.meta.url), "utf8");
  const block = api.slice(api.indexOf("listOrders:"), api.indexOf("getOrder:"));

  assert.match(block, /cursor\?: string/);
  assert.match(block, /request<OrderPage>\(/);
  assert.doesNotMatch(block, /offset/);
  assert.doesNotMatch(block, /request<Order\[\]>/);
});
