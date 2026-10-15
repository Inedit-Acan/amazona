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
  type RevenueKpisResult,
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
    entries_by_provider_kind: [],
    consolidated_eur_by_origin: [],
    non_aggregable_currencies: [],
    scope: SCOPE,
    ...over,
  };
}

const EUR_SUMMARY = summary({
  entries: 3,
  verified: [{ provider_kind: "mock", currency: "EUR", revenue: "100.0000", refunds: "10.0000", net: "90.0000", captures: 2, refund_count: 1 }],
  consolidated_eur_by_origin: [{ provider_kind: "mock", currency: "EUR", revenue: "100.0000", refunds: "10.0000", net: "90.0000", under_review_outstanding: "0.0000" }],
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

/** El Panel lee las tres cifras del núcleo; un `error` aquí sería un contrato roto (lo cubre `revenue-kpis.test.ts`). */
function panel(data: RevenueSummary): Extract<RevenueKpisResult, { kind: "ok" }> {
  const kpis = revenueKpis(data);
  assert.equal(kpis.kind, "ok", "la respuesta de la prueba cumple el contrato");
  return kpis as Extract<RevenueKpisResult, { kind: "ok" }>;
}

test("sin datos: sin ninguna fila verificada se dice «Sin datos», nunca 0", () => {
  const kpis = panel(summary());
  assert.equal(kpis.verified.value, NO_DATA);
  assert.equal(kpis.verified.isNoData, true);
  assert.equal(kpis.underReview.value, NO_DATA);
  assert.equal(kpis.underReview.isNoData, true);
  for (const text of [kpis.verified.value, kpis.underReview.value]) {
    assert.ok(!/\d/.test(text), `«${text}» no debe parecer una cifra`);
  }
  const view = summaryView(summary());
  assert.equal(view.hasAnyData, false);
  assert.deepEqual(view.verified, []);
});

test("sin datos: la evidencia pendiente SÍ es una cuenta medida; cero eventos es un cero verdadero", () => {
  const kpis = panel(summary());
  assert.equal(kpis.pending.value, "0");
  assert.equal(kpis.pending.isNoData, false);
});

test("solo otra moneda (USD verificado): se enseña su importe, NUNCA «Sin datos»; la moneda no se convierte ni se oculta", () => {
  const usdOnly = summary({
    entries: 1,
    verified: [{ provider_kind: "mock", currency: "USD", revenue: "50.0000", refunds: "0.0000", net: "50.0000", captures: 1, refund_count: 0 }],
    non_aggregable_currencies: [{ currency: "USD", reason: "no valid accounting conversion exists yet" }],
  });
  const kpis = panel(usdOnly);
  assert.equal(kpis.verified.value, "50,00 USD");
  assert.equal(kpis.verified.isNoData, false);
  assert.notEqual(kpis.verified.value, NO_DATA);
  assert.match(kpis.verified.caption, /Origen: Simulado/);
  assert.equal(summaryView(usdOnly).verified[0].revenue, "50,00 USD");
});

test("serie y entradas sin datos: ninguna columna, ninguna fila, ningún cero inventado", () => {
  const empty: RevenueSeries = { granularity: "day", period: {}, buckets: [], scope: SCOPE };
  const view = seriesView(empty, "2026-09-27T00:00:00.000Z", "2026-10-04T00:00:00.000Z");
  assert.deepEqual(view.keys, []);
  assert.equal(view.windowDays, 7);
  assert.equal(entriesSummaryText(entriesFromPage({ items: [], has_more: false, next_cursor: null })), "No hay entradas en este periodo.");
});

// --- Datos del registro -------------------------------------------------------------------------------------------

test("datos del registro: ingresos, reembolsos y neto en EUR salen tal cual los dio el registro", () => {
  const kpis = panel(EUR_SUMMARY);
  assert.equal(kpis.verified.value, "100,00 €");
  assert.match(kpis.verified.caption, /Reembolsos 10,00 €/);
  assert.match(kpis.verified.caption, /Neto 90,00 €/);
  assert.equal(kpis.verified.isNoData, false);
  const view = summaryView(EUR_SUMMARY);
  assert.deepEqual(view.verified, [
    { providerKind: "mock", currency: "EUR", revenue: "100,00 €", refunds: "10,00 €", net: "90,00 €", captures: "2", refundCount: "1" },
  ]);
});

test("datos del registro: una partida en revisión medida con importe cero SÍ se enseña como cero (hay una fila); sin fila no hay cifra", () => {
  const measuredZero = summary({
    entries: 2,
    under_review: [
      { provider_kind: "mock", currency: "EUR", classification: "DUPLICATE_RECEIPT", received: "20.0000", refunded: "20.0000", outstanding: "0.0000", receipts: 1, refund_count: 1 },
    ],
  });
  assert.equal(panel(measuredZero).underReview.value, "0,00 €");
  assert.equal(panel(measuredZero).underReview.isNoData, false);
  assert.equal(panel(summary()).underReview.value, NO_DATA, "sin ninguna partida en revisión no hay cifra");
});

// --- Monedas: ni se suman ni se convierten ni se ocultan ----------------------------------------------------------

const MIXED = summary({
  entries: 5,
  verified: [
    { provider_kind: "mock", currency: "USD", revenue: "50.0000", refunds: "0.0000", net: "50.0000", captures: 1, refund_count: 0 },
    { provider_kind: "mock", currency: "EUR", revenue: "100.0000", refunds: "0.0000", net: "100.0000", captures: 2, refund_count: 0 },
    { provider_kind: "mock", currency: "GBP", revenue: "7.0000", refunds: "0.0000", net: "7.0000", captures: 1, refund_count: 0 },
  ],
  non_aggregable_currencies: [
    { currency: "USD", reason: "x" },
    { currency: "GBP", reason: "x" },
  ],
});

test("monedas distintas: cada una en su línea, EUR primero; el KPI no elige ninguna como total y dice cuántas cifras hay", () => {
  const view = summaryView(MIXED);
  assert.deepEqual(view.verified.map((row) => row.currency), ["EUR", "GBP", "USD"]);
  assert.deepEqual(view.otherCurrencies, ["GBP", "USD"]);
  const kpis = panel(MIXED);
  assert.equal(kpis.verified.value, "3 cifras");
  assert.equal(kpis.verified.isNoData, true);
  assert.equal(kpis.verified.detail, true, "la tarjeta enlaza a la tabla que las enseña todas");
  assert.doesNotMatch(kpis.verified.value, /100,00|50,00|7,00/, "ninguna cifra se elige como la de la tarjeta");
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
    { provider_kind: "mock", currency: "EUR", classification: "DUPLICATE_RECEIPT", received: "40.0000", refunded: "0.0000", outstanding: "40.0000", receipts: 1, refund_count: 0 },
  ],
});

test("en revisión: no aumenta lo verificado ni se muestra sumado a ello", () => {
  const kpis = panel(REVIEWED);
  assert.equal(kpis.verified.value, "100,00 €");
  assert.equal(kpis.underReview.value, "40,00 €");
  const everything = JSON.stringify([summaryView(REVIEWED), kpis]);
  assert.ok(!everything.includes("140,00"), "100 verificados + 40 en revisión no son 140 verificados");
  assert.ok(!everything.includes("130,00"));
});

test("en revisión: cambiar lo que está en revisión no cambia NI UNA cifra verificada", () => {
  const without = panel(EUR_SUMMARY);
  const withReview = panel(REVIEWED);
  assert.deepEqual(withReview.verified.value, without.verified.value);
  assert.deepEqual(withReview.verified.caption, without.verified.caption);
  assert.deepEqual(summaryView(REVIEWED).verified, summaryView(EUR_SUMMARY).verified);
});

test("en revisión: cada clase lleva su etiqueta y no se funden", () => {
  const both = summary({
    ...REVIEWED,
    under_review: [
      ...REVIEWED.under_review,
      { provider_kind: "mock", currency: "EUR", classification: "MISMATCH_RECEIPT", received: "5.0000", refunded: "0.0000", outstanding: "5.0000", receipts: 1, refund_count: 0 },
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
      by_currency: [{ provider_kind: "mock", currency: "EUR", event_type: "payment.succeeded", count: 3, amount: "999.0000" }],
    },
  });
  const before = panel(EUR_SUMMARY);
  const after = panel(withEvidence);
  assert.equal(after.verified.value, before.verified.value);
  assert.equal(after.verified.caption, before.verified.caption);
  assert.equal(after.underReview.value, before.underReview.value);
  assert.deepEqual(summaryView(withEvidence).verified, summaryView(EUR_SUMMARY).verified);
  // Y se enseña aparte, con su propia etiqueta.
  assert.equal(after.pending.value, "3");
  assert.match(after.pending.caption, /No son ingreso ni reembolso/);
  assert.deepEqual(summaryView(withEvidence).pendingEvidence.lines, [
    { providerKind: "mock", currency: "EUR", label: "Cobro sin asentar", count: "3", amount: "999,00 €" },
  ]);
});

test("evidencia pendiente sola cuenta como dato (no es 'sin datos'), pero no crea ingreso", () => {
  const onlyEvidence = summary({
    pending_evidence: { count: 1, by_currency: [{ provider_kind: "mock", currency: "EUR", event_type: "refund.succeeded", count: 1, amount: "5.0000" }] },
    non_aggregable_currencies: [],
  });
  assert.equal(summaryView(onlyEvidence).hasAnyData, true);
  assert.equal(panel(onlyEvidence).verified.value, NO_DATA);
});

// --- Serie por día ------------------------------------------------------------------------------------------------

const bucket = (day: string, currency: string, revenue: string, over: Partial<RevenueSeriesBucket> = {}): RevenueSeriesBucket => ({
  bucket: day,
  provider_kind: "mock",
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
  const eur = view.bySeries["mock·EUR"];
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
  assert.deepEqual(view.keys, ["mock·EUR", "mock·USD"]);
  assert.equal(view.bySeries["mock·EUR"].rows[0].revenue, "10,00 €");
  assert.equal(view.bySeries["mock·USD"].rows[0].revenue, "50,00 USD");
  assert.equal(view.bySeries["mock·EUR"].columns.length, 1);
});

test("serie: fuera de la ventana o en cubos mensuales no se dibuja nada", () => {
  const series: RevenueSeries = {
    granularity: "day",
    period: {},
    buckets: [bucket("2026-09-01", "EUR", "10.0000"), bucket("2026-10-04", "EUR", "10.0000"), bucket("2026-09", "EUR", "10.0000")],
    scope: SCOPE,
  };
  assert.deepEqual(seriesView(series, ...WINDOW).keys, []);
});

test("serie: el importe del tooltip es el texto exacto; solo la altura de la barra pasa por número", () => {
  const series: RevenueSeries = { granularity: "day", period: {}, buckets: [bucket("2026-09-28", "EUR", "12345678901234567.8900")], scope: SCOPE };
  const column = seriesView(series, ...WINDOW).bySeries["mock·EUR"].columns[0];
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
  const eur = seriesView(series, ...WINDOW).bySeries["mock·EUR"];
  assert.equal(eur.rows[0].net, "−8,00 €");
  assert.equal(eur.columns[0].plot, 0);
});

// --- Entradas por cursor ------------------------------------------------------------------------------------------

const entry = (id: string, over: Partial<RevenueEntry> = {}): RevenueEntry => ({
  id,
  kind: "CAPTURE",
  provider_kind: "mock",
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

test("settle: un error del backend sale como error visible, sin su estado ni su detalle (M46, Commit 6)", async () => {
  const failure = Object.assign(new Error("{}"), { status: 500, detail: "database unavailable" });
  const result = await settle(async () => {
    throw failure;
  });
  assert.equal(result.ok, false);
  if (!result.ok) {
    assert.match(result.message, /no están disponibles/);
    assert.doesNotMatch(result.message, /500|database unavailable/);
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
  // Un fallo de red no se traga, pero tampoco se enseña como `fetch failed` (M46, Commit 6).
  assert.ok(!offline.ok && offline.message === "No se pudieron cargar los ingresos.");
});

test("settle: nunca devuelve datos cuando la lectura falla", async () => {
  const result = await settle(async () => {
    throw new Error("boom");
  });
  assert.equal(result.ok, false);
  assert.ok(!("data" in result));
});

test("revenueErrorText: un 422 y un 5xx dicen qué pasó, sin enseñar el estado HTTP ni el detalle del backend", async () => {
  assert.match(revenueErrorText(422), /rechazó/);
  assert.match(revenueErrorText(503), /no están disponibles/);
  assert.equal(revenueErrorText(undefined), "No se pudieron cargar los ingresos.");

  // M46, Commit 6: nada técnico llega al usuario, venga del estado o del detalle que el backend devuelva.
  for (const [status, detail] of [
    [422, "bad window"],
    [500, "Traceback (most recent call last)"],
    [503, "ECONNREFUSED 127.0.0.1:8000"],
    [undefined, "fetch failed"],
  ] as const) {
    const settled = await settle(async () => {
      throw Object.assign(new Error(detail), { status, detail });
    });
    assert.equal(settled.ok, false);
    const message = settled.ok ? "" : settled.message;
    assert.doesNotMatch(message, /\b(?:4\d\d|5\d\d)\b|ECONNREFUSED|fetch failed|Traceback|HTTP/i);
    assert.ok(!message.includes(detail), `el texto repite el detalle: ${message}`);
  }
});

test("settle: el texto del error lo da quien llama y nunca se pierde el estado", async () => {
  const failing = async () => {
    throw Object.assign(new Error("boom"), { status: 503, detail: "ECONNREFUSED 127.0.0.1" });
  };

  const byDefault = await settle(failing);
  const custom = await settle(failing, (status) => `custom ${status}`);
  const ok = await settle(async () => [1, 2]);

  assert.deepEqual(byDefault, { ok: false, message: "Los ingresos no están disponibles en este momento." });
  assert.deepEqual(custom, { ok: false, message: "custom 503" });
  assert.deepEqual(ok, { ok: true, data: [1, 2] });
});

// --- Procedencia (M46, ADR 0031): cada cifra es de UN origen y la vista nunca los suma -----------------------------

const EUR_ROW = (provider_kind: "mock" | "sandbox" | "real", revenue: string) => ({
  provider_kind,
  currency: "EUR",
  revenue,
  refunds: "5.0000",
  net: revenue,
  captures: 1,
  refund_count: 1,
});
const EUR_CONSOLIDATED = (provider_kind: "mock" | "sandbox" | "real", revenue: string) => ({
  provider_kind,
  currency: "EUR",
  revenue,
  refunds: "5.0000",
  net: revenue,
  under_review_outstanding: "0.0000",
});

const TWO_ORIGINS = summary({
  entries: 4,
  entries_by_provider_kind: [
    { provider_kind: "mock", entries: 2 },
    { provider_kind: "sandbox", entries: 2 },
  ],
  verified: [EUR_ROW("sandbox", "40.0000"), EUR_ROW("mock", "20.0000")],
  // El bloque consolidado sigue en el contrato, pero ninguna cifra sale de él: se deja aquí para que la prueba lo demuestre.
  consolidated_eur_by_origin: [EUR_CONSOLIDATED("sandbox", "40.0000"), EUR_CONSOLIDATED("mock", "20.0000")],
});

test("origen: la vista conserva el provider_kind de cada línea, sin completarlo ni deducirlo", () => {
  const view = summaryView(TWO_ORIGINS);
  assert.deepEqual(view.verified.map((line) => [line.providerKind, line.revenue]), [
    ["mock", "20,00 €"],
    ["sandbox", "40,00 €"],
  ]);
  assert.deepEqual(view.origins, ["mock", "sandbox"]);
});

test("origen: con varios orígenes la tarjeta NO elige una cifra: dice cuántas hay, no se suma nada y el detalle está en la tabla", () => {
  const kpis = panel(TWO_ORIGINS);
  assert.equal(kpis.verified.value, "2 cifras");
  assert.equal(kpis.verified.isNoData, true);
  assert.equal(kpis.verified.detail, true);
  const everything = JSON.stringify([summaryView(TWO_ORIGINS), kpis]);
  for (const sum of ["60,00", "60.0000", "70,00"]) {
    assert.ok(!everything.includes(sum), `aparece ${sum}: se han sumado orígenes distintos`);
  }
  // Y NINGUNA procedencia se pierde: la tabla (misma página) las lleva las dos, con sus importes.
  assert.deepEqual(summaryView(TWO_ORIGINS).verified.map((line) => [line.providerKind, line.revenue]), [
    ["mock", "20,00 €"],
    ["sandbox", "40,00 €"],
  ]);
});

test("origen: con un solo origen se enseña su cifra y se dice de qué origen es", () => {
  const kpis = panel(EUR_SUMMARY);
  assert.equal(kpis.verified.value, "100,00 €");
  assert.match(kpis.verified.caption, /Origen: Simulado\./);
  const reviewed = panel(REVIEWED);
  assert.match(reviewed.underReview.caption, /Origen: Simulado\./);
});

test("origen: tres orígenes en revisión tampoco se suman: «3 partidas» y ninguna cifra elegida", () => {
  const review = (provider_kind: "mock" | "real" | "sandbox", outstanding: string) => ({
    provider_kind,
    currency: "EUR",
    classification: "DUPLICATE_RECEIPT",
    received: outstanding,
    refunded: "0.0000",
    outstanding,
    receipts: 1,
    refund_count: 0,
  });
  const three = summary({ ...TWO_ORIGINS, under_review: [review("mock", "1.0000"), review("real", "2.0000"), review("sandbox", "3.0000")] });
  const kpis = panel(three);
  assert.equal(kpis.underReview.value, "3 partidas");
  assert.equal(kpis.underReview.detail, true);
  assert.ok(!JSON.stringify(kpis).includes("6,00"), "1 + 2 + 3 no es la cifra de nadie");
  assert.deepEqual(summaryView(three).underReview.map((row) => [row.providerKind, row.outstanding]), [
    ["mock", "1,00 €"],
    ["real", "2,00 €"],
    ["sandbox", "3,00 €"],
  ]);
});

test("origen: la evidencia pendiente y el dinero en revisión se quedan en su origen", () => {
  const data = summary({
    entries: 1,
    entries_by_provider_kind: [{ provider_kind: "real", entries: 1 }],
    under_review: [
      { provider_kind: "real", currency: "EUR", classification: "DUPLICATE_RECEIPT", received: "9.0000", refunded: "0.0000", outstanding: "9.0000", receipts: 1, refund_count: 0 },
    ],
    pending_evidence: {
      count: 2,
      by_currency: [
        { provider_kind: "sandbox", currency: "EUR", event_type: "payment.succeeded", count: 1, amount: "3.0000" },
        { provider_kind: "mock", currency: "EUR", event_type: "payment.succeeded", count: 1, amount: "4.0000" },
      ],
    },
  });
  const view = summaryView(data);
  assert.deepEqual(view.underReview.map((line) => line.providerKind), ["real"]);
  assert.deepEqual(view.pendingEvidence.lines.map((line) => [line.providerKind, line.amount]), [
    ["mock", "4,00 €"],
    ["sandbox", "3,00 €"],
  ]);
  assert.ok(!JSON.stringify(view).includes("7,00"), "3 + 4 no es la cifra de nadie");
});

test("origen: una serie es de un origen y una moneda, y dos orígenes no comparten barras", () => {
  const series: RevenueSeries = {
    granularity: "day",
    period: {},
    buckets: [
      bucket("2026-09-28", "EUR", "10.0000", { provider_kind: "sandbox" }),
      bucket("2026-09-28", "EUR", "20.0000"),
      bucket("2026-09-28", "USD", "50.0000", { provider_kind: "sandbox" }),
    ],
    scope: SCOPE,
  };
  const view = seriesView(series, ...WINDOW);
  assert.deepEqual(view.keys, ["mock·EUR", "sandbox·EUR", "sandbox·USD"]);
  assert.equal(view.bySeries["mock·EUR"].columns.length, 1);
  assert.equal(view.bySeries["sandbox·EUR"].columns.length, 1);
  assert.equal(view.bySeries["mock·EUR"].rows[0].revenue, "20,00 €");
  assert.equal(view.bySeries["sandbox·EUR"].rows[0].revenue, "10,00 €");
  assert.ok(!JSON.stringify(view).includes("30,00"), "10 + 20 no es la cifra de nadie");
});

test("origen: cada entrada enseña el provider_kind que guardó el backend", () => {
  assert.equal(entryRow(entry("a")).providerKind, "mock");
  assert.equal(entryRow(entry("b", { provider_kind: "real" })).providerKind, "real");
});
