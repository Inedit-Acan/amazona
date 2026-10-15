import assert from "node:assert/strict";
import { test } from "node:test";
import type { RevenueSummary } from "./api.ts";
import { assertRevenueSummary } from "./revenue-contract.ts";
import { NO_DATA, revenueKpis, settle, summaryView, verifiedMetricKpis, type KpiText } from "./revenue-view.ts";

// Las TARJETAS de ingresos de `/dashboard` (`revenueKpis`) y de `/cfo` (`verifiedMetricKpis`) (M47, 3A.1). Las presentaciones pueden diferir;
// los hechos económicos, no: las dos leen el núcleo `lib/revenue-figures.ts`. Pruebas A–M de la corrección compartida, a nivel de tarjeta.

const SCOPE = { is_accounting_ledger: false, basis: "verified payment facts", excludes: ["costs"] };
type Origin = "mock" | "sandbox" | "real";

const row = (origin: Origin, currency: string, revenue: string, over: Partial<RevenueSummary["verified"][number]> = {}) => ({
  provider_kind: origin,
  currency,
  revenue,
  refunds: "0.0000",
  net: revenue,
  captures: 1,
  refund_count: 0,
  ...over,
});

const review = (origin: Origin, currency: string, outstanding: string, classification = "DUPLICATE_RECEIPT") => ({
  provider_kind: origin,
  currency,
  classification,
  received: outstanding,
  refunded: "0.0000",
  outstanding,
  receipts: 1,
  refund_count: 0,
});

const summary = (over: Partial<RevenueSummary> = {}): RevenueSummary => ({
  period: {},
  entries: 0,
  entries_by_provider_kind: [],
  verified: [],
  under_review: [],
  pending_evidence: { count: 0, by_currency: [] },
  consolidated_eur_by_origin: [],
  non_aggregable_currencies: [],
  scope: SCOPE,
  ...over,
});

function panel(data: RevenueSummary) {
  const kpis = revenueKpis(data);
  assert.equal(kpis.kind, "ok");
  return kpis as Extract<ReturnType<typeof revenueKpis>, { kind: "ok" }>;
}

function cfo(data: RevenueSummary) {
  const kpis = verifiedMetricKpis(data);
  assert.equal(kpis.kind, "ok");
  return kpis as Extract<ReturnType<typeof verifiedMetricKpis>, { kind: "ok" }>;
}

const REVIEW_ONLY_EUR = summary({
  entries: 1,
  under_review: [review("mock", "EUR", "40.0000")],
  consolidated_eur_by_origin: [{ provider_kind: "mock", currency: "EUR", revenue: "0.0000", refunds: "0.0000", net: "0.0000", under_review_outstanding: "40.0000" }],
});
const USD_ONLY = summary({ entries: 1, verified: [row("mock", "USD", "50.0000")], non_aggregable_currencies: [{ currency: "USD", reason: "x" }] });
const EUR_ONLY = summary({ entries: 3, verified: [row("mock", "EUR", "100.0000", { refunds: "10.0000", net: "90.0000", captures: 2, refund_count: 1 })] });
const EUR_AND_USD = summary({ entries: 3, verified: [row("mock", "USD", "30.0000"), row("mock", "EUR", "100.0000")], non_aggregable_currencies: [{ currency: "USD", reason: "x" }] });
const TWO_ORIGINS = summary({ entries: 2, verified: [row("sandbox", "EUR", "30.0000"), row("mock", "EUR", "50.0000")] });
const TWO_BY_TWO = summary({
  entries: 4,
  verified: [row("sandbox", "USD", "4.0000"), row("mock", "USD", "3.0000"), row("sandbox", "EUR", "2.0000"), row("mock", "EUR", "1.0000")],
});

const verifiedCards = (data: RevenueSummary): KpiText[] => {
  const k = cfo(data);
  return [k.revenue, k.refunds, k.net];
};

// --- /dashboard: Ingresos verificados ---------------------------------------------------------------------------------------------

test("[/dashboard] A. solo EUR: su cifra, su origen y los importes del backend", () => {
  const k = panel(EUR_ONLY).verified;
  assert.equal(k.value, "100,00 €");
  assert.equal(k.isNoData, false);
  assert.match(k.caption, /Origen: Simulado\. Reembolsos 10,00 € · Neto 90,00 €/);
});

test("[/dashboard] B. solo USD: la cifra USD, NUNCA «Sin datos» ni un cero", () => {
  const k = panel(USD_ONLY).verified;
  assert.equal(k.value, "50,00 USD");
  assert.notEqual(k.value, NO_DATA);
  assert.doesNotMatch(JSON.stringify(k), /0,00 €/);
});

test("[/dashboard] C. EUR + USD: «2 cifras», ninguna elegida, ninguna suma, detalle en la tabla", () => {
  const k = panel(EUR_AND_USD).verified;
  assert.equal(k.value, "2 cifras");
  assert.equal(k.detail, true);
  assert.equal(k.isNoData, true);
  assert.doesNotMatch(JSON.stringify(k), /130,00|130\.0000|100,00|30,00/);
  assert.deepEqual(summaryView(EUR_AND_USD).verified.map((r) => [r.currency, r.revenue]), [["EUR", "100,00 €"], ["USD", "30,00 USD"]]);
});

test("[/dashboard y /cfo] con varias cifras la tarjeta lo DICE: «Por origen y moneda», sin suma ni conversión", () => {
  for (const data of [EUR_AND_USD, TWO_ORIGINS, TWO_BY_TWO]) {
    for (const card of [panel(data).verified, ...verifiedCards(data)]) {
      assert.match(card.caption, /Verificadas, por origen y moneda: sin sumar ni convertir\./);
      assert.match(card.value, /^\d+ cifras$/);
    }
  }
});

test("[/dashboard] D·E. varias procedencias y monedas: la tarjeta dice cuántas; la tabla las conserva TODAS", () => {
  assert.equal(panel(TWO_ORIGINS).verified.value, "2 cifras");
  assert.equal(panel(TWO_BY_TWO).verified.value, "4 cifras");
  assert.deepEqual(summaryView(TWO_ORIGINS).verified.map((r) => [r.providerKind, r.revenue]), [["mock", "50,00 €"], ["sandbox", "30,00 €"]]);
  assert.deepEqual(summaryView(TWO_BY_TWO).verified.map((r) => `${r.currency}·${r.providerKind}`), ["EUR·mock", "EUR·sandbox", "USD·mock", "USD·sandbox"]);
  assert.doesNotMatch(JSON.stringify(panel(TWO_ORIGINS).verified), /Varios orígenes|80,00/);
});

test("[/dashboard] F. verified vacío: «Sin datos», sin cifra", () => {
  const k = panel(summary()).verified;
  assert.equal(k.value, NO_DATA);
  assert.equal(k.isNoData, true);
  assert.doesNotMatch(k.value, /\d/);
});

test("[/dashboard] G. EUR solo en revisión: verificado «Sin datos» (NO 0,00 €); la revisión, aparte y con su importe", () => {
  const k = panel(REVIEW_ONLY_EUR);
  assert.equal(k.verified.value, NO_DATA);
  assert.doesNotMatch(JSON.stringify(k.verified), /0,00 €/);
  assert.equal(k.underReview.value, "40,00 €");
  assert.match(k.underReview.caption, /Duplicado · en revisión · Origen: Simulado\. No suma a lo verificado/);
});

test("[/dashboard] H. contrato roto: error, nunca «Sin datos»", async () => {
  for (const broken of [{ ...summary(), consolidated_eur: { revenue: "1.0000" } }, summary({ verified: [row("mock", "EUR", "1.0000"), row("mock", "EUR", "1.0000")] })] as unknown as RevenueSummary[]) {
    const settled = await settle(async () => assertRevenueSummary(broken));
    const result = settled.ok ? revenueKpis(settled.data) : ({ kind: "error", message: settled.message } as const);
    assert.equal(result.kind, "error");
    if (result.kind === "error") assert.match(result.message, /El contrato de ingresos cambió/);
  }
});

test("[/dashboard] I. net negativo: el signo se conserva", () => {
  const data = summary({ entries: 1, verified: [row("mock", "EUR", "0.0000", { refunds: "12.5000", net: "-12.5000", captures: 0, refund_count: 1 })] });
  assert.match(panel(data).verified.caption, /Neto −12,50 €/);
  assert.equal(cfo(data).net.value, "−12,50 €");
});

test("[/dashboard] J. evidencia pendiente: moneda, origen, recuento e importe por línea; nunca dos orígenes bajo una cifra", () => {
  const data = summary({
    entries: 0,
    pending_evidence: {
      count: 3,
      by_currency: [
        { provider_kind: "sandbox", currency: "USD", event_type: "refund.succeeded", count: 1, amount: "5.0000" },
        { provider_kind: "mock", currency: "EUR", event_type: "payment.succeeded", count: 2, amount: "999.0000" },
      ],
    },
  });
  const k = panel(data).pending;
  assert.equal(k.value, "3", "el recuento de eventos (no dinero)");
  // Cada línea conserva clase, ORIGEN, recuento e importe; la moneda va en el importe (`€` o el código), nunca sumada con otra.
  assert.match(k.caption, /Cobro sin asentar · Simulado · 2 eventos · 999,00 €/);
  assert.match(k.caption, /Reembolso sin asentar · Entorno de pruebas · 1 evento · 5,00 USD/);
  assert.doesNotMatch(k.caption, /1\.004|1\.004,00|1004/, "ninguna suma entre monedas ni orígenes");
  assert.equal(panel(summary()).pending.value, "0", "cero eventos medidos es un cero verdadero");
});

test("[/dashboard] K. non_aggregable: la moneda con línea se enseña; la que solo está declarada sale como nota, no como ingreso", () => {
  const withNote = summary({ entries: 1, verified: [row("mock", "EUR", "1.0000")], non_aggregable_currencies: [{ currency: "GBP", reason: "x" }] });
  assert.match(panel(withNote).verified.caption, /GBP: sin conversión contable disponible/);
  assert.equal(panel(withNote).verified.value, "1,00 €");
  assert.equal(panel(USD_ONLY).verified.value, "50,00 USD");
});

test("[/dashboard] L. ninguna suma entre monedas ni procedencias en ninguna tarjeta", () => {
  const text = JSON.stringify([panel(TWO_BY_TWO), panel(EUR_AND_USD), panel(TWO_ORIGINS)]);
  for (const sum of ["130,00", "80,00", "10,00 €", "3,00 €", "7,00", "5,00"]) assert.ok(!text.includes(`"${sum}"`), `aparece ${sum}`);
});

test("[/dashboard] M. «En revisión»: una partida enseña su importe y origen; varias, «N partidas» sin elegir ninguna; nada se suma", () => {
  const three = summary({ under_review: [review("mock", "EUR", "1.0000"), review("real", "EUR", "2.0000"), review("sandbox", "USD", "3.0000")] });
  const k = panel(three).underReview;
  assert.equal(k.value, "3 partidas");
  assert.equal(k.detail, true);
  assert.doesNotMatch(JSON.stringify(k), /6,00/);
  assert.equal(panel(summary()).underReview.value, NO_DATA);
});

// --- /cfo: Ingresos, Reembolsos y Neto verificado ------------------------------------------------------------------------------------

test("[/cfo] solo USD: las tres tarjetas enseñan USD y NINGUNA dice «Sin datos»", () => {
  const k = cfo(USD_ONLY);
  assert.deepEqual([k.revenue.value, k.refunds.value, k.net.value], ["50,00 USD", "0,00 USD", "50,00 USD"]);
  for (const card of verifiedCards(USD_ONLY)) assert.notEqual(card.value, NO_DATA);
});

test("[/cfo] varias procedencias o monedas: las tres tarjetas dicen cuántas cifras hay, sin elegir ni sumar, con el detalle en «Por moneda»", () => {
  for (const [data, n] of [[TWO_ORIGINS, 2], [EUR_AND_USD, 2], [TWO_BY_TWO, 4]] as const) {
    for (const card of verifiedCards(data)) {
      assert.equal(card.value, `${n} cifras`);
      assert.equal(card.detail, true);
      assert.doesNotMatch(JSON.stringify(card), /Varios orígenes/);
    }
    assert.equal(summaryView(data).verified.length, n, "la tabla de la misma página tiene todas las filas");
  }
});

test("[/cfo] solo dinero en revisión: ninguna tarjeta verificada fabrica 0,00 €; las tres dicen «Sin datos»", () => {
  for (const card of verifiedCards(REVIEW_ONLY_EUR)) {
    assert.equal(card.value, NO_DATA);
    assert.doesNotMatch(JSON.stringify(card), /0,00 €/);
  }
});

test("[/cfo] Ingresos, Reembolsos y Neto son coherentes entre sí: mismas líneas, mismo veredicto, mismo recuento", () => {
  for (const data of [summary(), EUR_ONLY, USD_ONLY, EUR_AND_USD, TWO_ORIGINS, TWO_BY_TWO, REVIEW_ONLY_EUR]) {
    const cards = verifiedCards(data);
    const kinds = new Set(cards.map((c) => (c.value === NO_DATA ? "empty" : c.detail ? `many:${c.value}` : "one")));
    assert.equal(kinds.size, 1, `las tres tarjetas discrepan: ${cards.map((c) => c.value).join(" | ")}`);
    assert.equal(new Set(cards.map((c) => c.isNoData)).size, 1);
    assert.equal(new Set(cards.map((c) => Boolean(c.detail))).size, 1);
  }
  const one = cfo(EUR_ONLY);
  assert.deepEqual([one.revenue.value, one.refunds.value, one.net.value], ["100,00 €", "10,00 €", "90,00 €"], "el neto es el del backend");
});

test("[/cfo] contrato roto: error, nunca «Sin datos»", () => {
  const broken = summary({ verified: [row("mock", "EUR", "1.0000"), row("mock", "EUR", "1.0000")] });
  const result = verifiedMetricKpis(broken);
  assert.equal(result.kind, "error");
  assert.equal(verifiedMetricKpis({ ...summary(), verified: undefined } as unknown as RevenueSummary).kind, "error");
});

test("[/cfo] ningún otro bloque financiero cambia: las tablas «Por moneda» y «Fuera de lo verificado» siguen siendo las mismas filas", () => {
  const data = summary({
    entries: 3,
    verified: [row("mock", "EUR", "100.0000", { refunds: "10.0000", net: "90.0000", captures: 2, refund_count: 1 })],
    under_review: [review("mock", "EUR", "40.0000")],
    pending_evidence: { count: 1, by_currency: [{ provider_kind: "mock", currency: "EUR", event_type: "payment.succeeded", count: 1, amount: "5.0000" }] },
  });
  const view = summaryView(data);
  assert.deepEqual(view.verified, [{ providerKind: "mock", currency: "EUR", revenue: "100,00 €", refunds: "10,00 €", net: "90,00 €", captures: "2", refundCount: "1" }]);
  assert.deepEqual(view.underReview.map((r) => [r.providerKind, r.label, r.outstanding]), [["mock", "Duplicado · en revisión", "40,00 €"]]);
  assert.deepEqual(view.pendingEvidence, { count: 1, lines: [{ providerKind: "mock", currency: "EUR", label: "Cobro sin asentar", count: "1", amount: "5,00 €" }] });
  assert.equal(view.hasAnyData, true);
});
