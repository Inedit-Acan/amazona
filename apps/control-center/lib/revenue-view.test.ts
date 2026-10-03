import assert from "node:assert/strict";
import { test } from "node:test";
import type {
  RevenueEntriesPage,
  RevenueEntry,
  RevenueSeries,
  RevenueSeriesBucket,
  RevenueSummary,
} from "./api.ts";
import {
  NO_DATA,
  appendEntries,
  classificationLabel,
  entriesFromPage,
  entriesSummaryText,
  entryRow,
  formatMoney,
  revenueErrorText,
  revenueKpis,
  seriesView,
  settle,
  summaryView,
} from "./revenue-view.ts";

// Vista de los ingresos del Panel (M45, ADR 0030). Lo que se enseña, y lo que NO se enseña como si fuera un dato.

const SCOPE = { is_accounting_ledger: false, basis: "verified payment facts", excludes: ["costs", "margin"] };

function summary(over: Partial<RevenueSummary> = {}): RevenueSummary {
  return {
    period: { from: "2026-09-27T00:00:00+00:00", to: "2026-10-04T00:00:00+00:00" },
    entries: 0,
    verified: [],
    under_review: [],
    pending_evidence: { count: 0, by_currency: [] },
    consolidated_eur: null,
    non_aggregable_currencies: [],
    scope: SCOPE,
    ...over,
  };
}

const EUR_SUMMARY = summary({
  entries: 3,
  verified: [{ currency: "EUR", revenue: "100.0000", refunds: "10.0000", net: "90.0000", captures: 2, refund_count: 1 }],
  consolidated_eur: { currency: "EUR", revenue: "100.0000", refunds: "10.0000", net: "90.0000", under_review_outstanding: "0.0000" },
});

// --- Importes: texto exacto, nunca float --------------------------------------------------------------------------

test("formatMoney: euros con separador de miles y coma, sin pasar por un número", () => {
  assert.equal(formatMoney("1234.5600", "EUR"), "1.234,56 €");
  assert.equal(formatMoney("0.0000", "EUR"), "0,00 €");
  assert.equal(formatMoney("1000000.0000", "EUR"), "1.000.000,00 €");
  assert.equal(formatMoney("999.0000", "EUR"), "999,00 €");
});

test("formatMoney: un importe de 17 dígitos sale exacto (un float lo corrompería)", () => {
  assert.equal(formatMoney("12345678901234567.8900", "EUR"), "12.345.678.901.234.567,89 €");
  assert.notEqual(String(Number("12345678901234567.89")), "12345678901234567.89");
});

test("formatMoney: otra moneda lleva su código, no el símbolo del euro", () => {
  assert.equal(formatMoney("50.0000", "USD"), "50,00 USD");
  assert.equal(formatMoney("1234.5000", "GBP"), "1.234,50 GBP");
});

test("formatMoney: un neto negativo se enseña, con signo; un cero negativo no", () => {
  assert.equal(formatMoney("-12.5000", "EUR"), "−12,50 €");
  assert.equal(formatMoney("-0.0000", "EUR"), "0,00 €");
});

test("formatMoney: nada se redondea en silencio; un texto roto se ve tal cual", () => {
  assert.equal(formatMoney("10.1234", "EUR"), "10,1234 €");
  assert.equal(formatMoney("10.1200", "EUR"), "10,12 €");
  assert.equal(formatMoney("12abc", "EUR"), "12abc EUR");
  assert.equal(formatMoney("", "EUR"), " EUR");
});

// --- Sin datos ---------------------------------------------------------------------------------------------------

test("sin datos: consolidated_eur nulo se dice «Sin datos», nunca 0", () => {
  const kpis = revenueKpis(summary());
  assert.equal(kpis.verified.value, NO_DATA);
  assert.equal(kpis.verified.isNoData, true);
  assert.equal(kpis.underReview.value, NO_DATA);
  assert.equal(kpis.underReview.isNoData, true);
  for (const text of [kpis.verified.value, kpis.underReview.value]) {
    assert.ok(!/\d/.test(text), `«${text}» no debe parecer una cifra`);
  }
  const view = summaryView(summary());
  assert.equal(view.eur, null);
  assert.equal(view.hasAnyData, false);
  assert.deepEqual(view.verified, []);
});

test("sin datos: la evidencia pendiente SÍ es una cuenta medida; cero eventos es un cero verdadero", () => {
  const kpis = revenueKpis(summary());
  assert.equal(kpis.pending.value, "0");
  assert.equal(kpis.pending.isNoData, false);
});

test("sin datos EUR pero con otra moneda: «Sin datos» en EUR y la otra moneda aparte", () => {
  const usdOnly = summary({
    entries: 1,
    verified: [{ currency: "USD", revenue: "50.0000", refunds: "0.0000", net: "50.0000", captures: 1, refund_count: 0 }],
    non_aggregable_currencies: [{ currency: "USD", reason: "no valid accounting conversion exists yet" }],
  });
  const kpis = revenueKpis(usdOnly);
  assert.equal(kpis.verified.value, NO_DATA);
  assert.match(kpis.verified.caption, /USD/);
  assert.match(kpis.verified.caption, /no se suman ni se convierten/);
  assert.equal(summaryView(usdOnly).verified[0].revenue, "50,00 USD");
});

test("serie y entradas sin datos: ninguna columna, ninguna fila, ningún cero inventado", () => {
  const empty: RevenueSeries = { granularity: "day", period: {}, buckets: [], scope: SCOPE };
  const view = seriesView(empty, "2026-09-27T00:00:00.000Z", "2026-10-04T00:00:00.000Z");
  assert.deepEqual(view.currencies, []);
  assert.equal(view.windowDays, 7);
  assert.equal(entriesSummaryText(entriesFromPage({ items: [], has_more: false, next_cursor: null })), "No hay entradas en este periodo.");
});

// --- Datos del registro -------------------------------------------------------------------------------------------

test("datos del registro: ingresos, reembolsos y neto en EUR salen tal cual los dio el registro", () => {
  const kpis = revenueKpis(EUR_SUMMARY);
  assert.equal(kpis.verified.value, "100,00 €");
  assert.match(kpis.verified.caption, /Reembolsos 10,00 €/);
  assert.match(kpis.verified.caption, /Neto 90,00 €/);
  assert.equal(kpis.verified.isNoData, false);
  const view = summaryView(EUR_SUMMARY);
  assert.deepEqual(view.eur, { revenue: "100,00 €", refunds: "10,00 €", net: "90,00 €", underReview: "0,00 €" });
  assert.deepEqual(view.verified, [
    { currency: "EUR", revenue: "100,00 €", refunds: "10,00 €", net: "90,00 €", captures: "2", refundCount: "1" },
  ]);
});

test("datos del registro: un cero medido (hay entradas en EUR y suman cero) SÍ se enseña como cero", () => {
  const measuredZero = summary({
    entries: 2,
    verified: [{ currency: "EUR", revenue: "20.0000", refunds: "20.0000", net: "0.0000", captures: 1, refund_count: 1 }],
    consolidated_eur: { currency: "EUR", revenue: "20.0000", refunds: "20.0000", net: "0.0000", under_review_outstanding: "0.0000" },
  });
  assert.equal(revenueKpis(measuredZero).underReview.value, "0,00 €");
  assert.equal(revenueKpis(measuredZero).underReview.isNoData, false);
});

// --- Monedas: ni se suman ni se convierten ------------------------------------------------------------------------

const MIXED = summary({
  entries: 5,
  verified: [
    { currency: "USD", revenue: "50.0000", refunds: "0.0000", net: "50.0000", captures: 1, refund_count: 0 },
    { currency: "EUR", revenue: "100.0000", refunds: "0.0000", net: "100.0000", captures: 2, refund_count: 0 },
    { currency: "GBP", revenue: "7.0000", refunds: "0.0000", net: "7.0000", captures: 1, refund_count: 0 },
  ],
  consolidated_eur: { currency: "EUR", revenue: "100.0000", refunds: "0.0000", net: "100.0000", under_review_outstanding: "0.0000" },
  non_aggregable_currencies: [
    { currency: "USD", reason: "x" },
    { currency: "GBP", reason: "x" },
  ],
});

test("monedas distintas: cada una en su línea, EUR primero, y el KPI es solo EUR", () => {
  const view = summaryView(MIXED);
  assert.deepEqual(view.verified.map((row) => row.currency), ["EUR", "GBP", "USD"]);
  assert.deepEqual(view.otherCurrencies, ["GBP", "USD"]);
  assert.equal(revenueKpis(MIXED).verified.value, "100,00 €");
});

test("monedas distintas: ninguna cifra de la vista es la suma de monedas", () => {
  const text = JSON.stringify([summaryView(MIXED), revenueKpis(MIXED)]);
  for (const forbidden of ["157,00", "150,00", "107,00", "57,00", "157.0000"]) {
    assert.ok(!text.includes(forbidden), `aparece ${forbidden}: se han sumado monedas distintas`);
  }
});

// --- En revisión y evidencia pendiente: nunca mezcladas -----------------------------------------------------------

const REVIEWED = summary({
  ...EUR_SUMMARY,
  under_review: [
    { currency: "EUR", classification: "DUPLICATE_RECEIPT", received: "40.0000", refunded: "0.0000", outstanding: "40.0000", receipts: 1, refund_count: 0 },
  ],
  consolidated_eur: { currency: "EUR", revenue: "100.0000", refunds: "10.0000", net: "90.0000", under_review_outstanding: "40.0000" },
});

test("en revisión: no aumenta lo verificado ni se muestra sumado a ello", () => {
  const kpis = revenueKpis(REVIEWED);
  assert.equal(kpis.verified.value, "100,00 €");
  assert.equal(kpis.underReview.value, "40,00 €");
  const everything = JSON.stringify([summaryView(REVIEWED), kpis]);
  assert.ok(!everything.includes("140,00"), "100 verificados + 40 en revisión no son 140 verificados");
  assert.ok(!everything.includes("130,00"));
});

test("en revisión: cambiar lo que está en revisión no cambia NI UNA cifra verificada", () => {
  const without = revenueKpis(EUR_SUMMARY);
  const withReview = revenueKpis(REVIEWED);
  assert.deepEqual(withReview.verified.value, without.verified.value);
  assert.deepEqual(summaryView(REVIEWED).verified, summaryView(EUR_SUMMARY).verified);
  assert.equal(summaryView(REVIEWED).eur?.revenue, summaryView(EUR_SUMMARY).eur?.revenue);
  assert.equal(summaryView(REVIEWED).eur?.net, summaryView(EUR_SUMMARY).eur?.net);
});

test("en revisión: cada clase lleva su etiqueta y no se funden", () => {
  const both = summary({
    ...REVIEWED,
    under_review: [
      ...REVIEWED.under_review,
      { currency: "EUR", classification: "MISMATCH_RECEIPT", received: "5.0000", refunded: "0.0000", outstanding: "5.0000", receipts: 1, refund_count: 0 },
    ],
  });
  assert.deepEqual(summaryView(both).underReview.map((row) => row.label), ["Duplicado · en revisión", "Discrepancia · en revisión"]);
  assert.equal(classificationLabel("ORDER_PAYMENT"), "Verificado");
});

test("evidencia pendiente: no aumenta ningún total", () => {
  const withEvidence = summary({
    ...EUR_SUMMARY,
    pending_evidence: {
      count: 3,
      by_currency: [{ currency: "EUR", event_type: "payment.succeeded", count: 3, amount: "999.0000" }],
    },
  });
  const before = revenueKpis(EUR_SUMMARY);
  const after = revenueKpis(withEvidence);
  assert.equal(after.verified.value, before.verified.value);
  assert.equal(after.verified.caption, before.verified.caption);
  assert.equal(after.underReview.value, before.underReview.value);
  assert.deepEqual(summaryView(withEvidence).eur, summaryView(EUR_SUMMARY).eur);
  assert.deepEqual(summaryView(withEvidence).verified, summaryView(EUR_SUMMARY).verified);
  // Y se enseña aparte, con su propia etiqueta.
  assert.equal(after.pending.value, "3");
  assert.match(after.pending.caption, /No son ingreso ni reembolso/);
  assert.deepEqual(summaryView(withEvidence).pendingEvidence.lines, [
    { currency: "EUR", label: "Cobro sin asentar", count: "3", amount: "999,00 €" },
  ]);
});

test("evidencia pendiente sola cuenta como dato (no es 'sin datos'), pero no crea ingreso", () => {
  const onlyEvidence = summary({
    pending_evidence: { count: 1, by_currency: [{ currency: "EUR", event_type: "refund.succeeded", count: 1, amount: "5.0000" }] },
    non_aggregable_currencies: [],
  });
  assert.equal(summaryView(onlyEvidence).hasAnyData, true);
  assert.equal(revenueKpis(onlyEvidence).verified.value, NO_DATA);
});

// --- Serie por día ------------------------------------------------------------------------------------------------

const bucket = (day: string, currency: string, revenue: string, over: Partial<RevenueSeriesBucket> = {}): RevenueSeriesBucket => ({
  bucket: day,
  currency,
  revenue,
  refunds: "0.0000",
  net: revenue,
  under_review_received: "0.0000",
  under_review_refunded: "0.0000",
  entries: 1,
  ...over,
});

const WINDOW = ["2026-09-27T00:00:00.000Z", "2026-10-04T00:00:00.000Z"] as const;

test("serie: los días sin entradas NO tienen columna (sin datos, no cero)", () => {
  const series: RevenueSeries = {
    granularity: "day",
    period: {},
    buckets: [bucket("2026-09-28", "EUR", "10.0000"), bucket("2026-10-01", "EUR", "20.0000")],
    scope: SCOPE,
  };
  const view = seriesView(series, ...WINDOW);
  const eur = view.byCurrency.EUR;
  assert.equal(view.windowDays, 7);
  assert.deepEqual(eur.columns.map((column) => column.x), [1, 4]);
  assert.equal(eur.columns.length, 2, "5 de los 7 días no existen en el registro y no se dibujan");
  assert.deepEqual(eur.rows.map((row) => row.bucket), ["2026-10-01", "2026-09-28"]);
});

test("serie: cada moneda tiene su propia serie y nunca se mezclan", () => {
  const series: RevenueSeries = {
    granularity: "day",
    period: {},
    buckets: [bucket("2026-09-28", "USD", "50.0000"), bucket("2026-09-28", "EUR", "10.0000")],
    scope: SCOPE,
  };
  const view = seriesView(series, ...WINDOW);
  assert.deepEqual(view.currencies, ["EUR", "USD"]);
  assert.equal(view.byCurrency.EUR.rows[0].revenue, "10,00 €");
  assert.equal(view.byCurrency.USD.rows[0].revenue, "50,00 USD");
  assert.equal(view.byCurrency.EUR.columns.length, 1);
});

test("serie: fuera de la ventana o en cubos mensuales no se dibuja nada", () => {
  const series: RevenueSeries = {
    granularity: "day",
    period: {},
    buckets: [bucket("2026-09-01", "EUR", "10.0000"), bucket("2026-10-04", "EUR", "10.0000"), bucket("2026-09", "EUR", "10.0000")],
    scope: SCOPE,
  };
  assert.deepEqual(seriesView(series, ...WINDOW).currencies, []);
});

test("serie: el importe del tooltip es el texto exacto; solo la altura de la barra pasa por número", () => {
  const series: RevenueSeries = { granularity: "day", period: {}, buckets: [bucket("2026-09-28", "EUR", "12345678901234567.8900")], scope: SCOPE };
  const column = seriesView(series, ...WINDOW).byCurrency.EUR.columns[0];
  assert.equal(column.revenueText, "12.345.678.901.234.567,89 €");
  assert.equal(typeof column.plot, "number");
});

test("serie: un día con solo reembolsos (neto negativo) se ve en la tabla y su barra no es negativa", () => {
  const series: RevenueSeries = {
    granularity: "day",
    period: {},
    buckets: [bucket("2026-09-29", "EUR", "0.0000", { refunds: "8.0000", net: "-8.0000" })],
    scope: SCOPE,
  };
  const eur = seriesView(series, ...WINDOW).byCurrency.EUR;
  assert.equal(eur.rows[0].net, "−8,00 €");
  assert.equal(eur.columns[0].plot, 0);
});

// --- Entradas por cursor ------------------------------------------------------------------------------------------

const entry = (id: string, over: Partial<RevenueEntry> = {}): RevenueEntry => ({
  id,
  kind: "CAPTURE",
  classification: "ORDER_PAYMENT",
  payment_event_id: `ev-${id}`,
  payment_id: `pay-${id}`,
  order_id: `order-${id}`,
  refund_id: null,
  capture_entry_id: null,
  amount: "10.0000",
  currency: "EUR",
  occurred_at: "2026-10-03T10:00:00+00:00",
  recorded_at: "2026-10-03T10:00:01+00:00",
  ...over,
});

const page = (ids: string[], hasMore: boolean, next: string | null): RevenueEntriesPage => ({
  items: ids.map((id) => entry(id)),
  has_more: hasMore,
  next_cursor: next,
});

test("entradas: una página no se toma por el total; el resumen dice si hay más", () => {
  const first = entriesFromPage(page(["e3", "e2"], true, "cursor-1"));
  assert.equal(first.hasMore, true);
  assert.equal(first.nextCursor, "cursor-1");
  assert.match(entriesSummaryText(first), /2 entradas cargadas; hay más antiguas sin cargar/);
});

test("entradas: «Cargar más» añade la página siguiente sin repetir ni saltar y en el mismo orden", () => {
  const first = entriesFromPage(page(["e5", "e4"], true, "cursor-1"));
  const second = appendEntries(first, page(["e3", "e2"], true, "cursor-2"));
  const third = appendEntries(second, page(["e1"], false, null));
  assert.deepEqual(third.items.map((item) => item.id), ["e5", "e4", "e3", "e2", "e1"]);
  assert.equal(third.hasMore, false);
  assert.equal(third.nextCursor, null);
  assert.match(entriesSummaryText(third), /5 entradas cargadas: son todas las del periodo/);
});

test("entradas: si el backend repitiera una entrada, no se duplica en pantalla", () => {
  const first = entriesFromPage(page(["e3", "e2"], true, "cursor-1"));
  const next = appendEntries(first, page(["e2", "e1"], false, null));
  assert.deepEqual(next.items.map((item) => item.id), ["e3", "e2", "e1"]);
});

test("entradas: la clase y el tipo se etiquetan; solo ORDER_PAYMENT es verificado", () => {
  const verified = entryRow(entry("a"));
  assert.equal(verified.verified, true);
  assert.equal(verified.kindLabel, "Cobro");
  const duplicate = entryRow(entry("b", { classification: "DUPLICATE_RECEIPT", kind: "REFUND", refund_id: "r1", amount: "4.0000" }));
  assert.equal(duplicate.verified, false);
  assert.equal(duplicate.kindLabel, "Reembolso");
  assert.equal(duplicate.classificationLabel, "Duplicado · en revisión");
  assert.equal(duplicate.amount, "4,00 €");
  assert.equal(entryRow(entry("c", { classification: "MISMATCH_RECEIPT" })).verified, false);
  assert.equal(entryRow(entry("d", { classification: "SOMETHING_NEW" })).verified, false, "una clase desconocida nunca cuenta como verificada");
});

// --- Errores: visibles, nunca sustituidos -------------------------------------------------------------------------

test("settle: un dato sale como dato", async () => {
  assert.deepEqual(await settle(async () => 42), { ok: true, data: 42 });
});

test("settle: un error del backend sale como error visible, con su estado", async () => {
  const failure = Object.assign(new Error("{}"), { status: 500, detail: "database unavailable" });
  const result = await settle(async () => {
    throw failure;
  });
  assert.equal(result.ok, false);
  if (!result.ok) {
    assert.match(result.message, /500/);
    assert.match(result.message, /database unavailable/);
  }
});

test("settle: sin permiso o sin sesión, el texto lo dice; y un fallo de red no se traga", async () => {
  const forbidden = await settle(async () => {
    throw Object.assign(new Error("x"), { status: 403, detail: "forbidden" });
  });
  assert.ok(!forbidden.ok && /permiso/.test(forbidden.message));
  const unauthorised = await settle(async () => {
    throw Object.assign(new Error("x"), { status: 401, detail: "no" });
  });
  assert.ok(!unauthorised.ok && /sesión/.test(unauthorised.message));
  const offline = await settle(async () => {
    throw new TypeError("fetch failed");
  });
  assert.ok(!offline.ok && offline.message === "fetch failed");
});

test("settle: nunca devuelve datos cuando la lectura falla", async () => {
  const result = await settle(async () => {
    throw new Error("boom");
  });
  assert.equal(result.ok, false);
  assert.ok(!("data" in result));
});

test("revenueErrorText: un 422 y un 5xx dicen qué pasó", () => {
  assert.match(revenueErrorText(422, "bad window"), /rechazó/);
  assert.match(revenueErrorText(503, "down"), /503/);
  assert.equal(revenueErrorText(undefined, ""), "Error desconocido");
});
