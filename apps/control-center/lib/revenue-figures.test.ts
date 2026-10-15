import assert from "node:assert/strict";
import { test } from "node:test";
import type { RevenueSummary } from "./api.ts";
import { formatMoney } from "./revenue-format.ts";
import { revenueFigures, secondarySummary, summaryFigures, type RevenueFigures } from "./revenue-figures.ts";

// El NÚCLEO de la semántica de los ingresos (M47, 3A.1). Las pruebas A–M de la corrección compartida, a nivel de núcleo: lo que ven `/ceo`,
// `/dashboard` y `/cfo` es lo que este módulo decide. La unidad es origen × moneda.

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

const loaded = (data: RevenueSummary) => {
  const figures = revenueFigures(data);
  assert.equal(figures.kind, "loaded", `se esperaba «loaded» y salió «${figures.kind}»`);
  return figures.kind === "loaded" ? figures : { lines: [], secondary: { underReview: [], pendingCount: 0, pending: [], notes: [] } };
};

test("A. solo EUR verificado: una línea, EUR, con los importes exactos del backend", () => {
  const { lines } = loaded(summary({ entries: 2, verified: [row("mock", "EUR", "100.0000", { refunds: "10.0000", net: "90.0000" })] }));
  assert.deepEqual(lines.map((l) => [l.currency, l.providerKind, l.revenue, l.refunds, l.net]), [["EUR", "mock", "100,00 €", "10,00 €", "90,00 €"]]);
});

test("B. solo USD verificado: loaded con USD; nunca vacío ni «Sin datos»", () => {
  const data = summary({ entries: 1, verified: [row("mock", "USD", "50.0000")], non_aggregable_currencies: [{ currency: "USD", reason: "x" }] });
  assert.deepEqual(loaded(data).lines.map((l) => [l.currency, l.revenue]), [["USD", "50,00 USD"]]);
  assert.notEqual(revenueFigures(data).kind, "empty");
});

test("C. EUR + USD: dos líneas por separado, EUR primero, ningún total", () => {
  const { lines } = loaded(summary({ entries: 2, verified: [row("mock", "USD", "30.0000"), row("mock", "EUR", "100.0000")] }));
  assert.deepEqual(lines.map((l) => l.revenue), ["100,00 €", "30,00 USD"]);
});

test("D. mock EUR + sandbox EUR: se conservan las dos procedencias", () => {
  const { lines } = loaded(summary({ entries: 2, verified: [row("sandbox", "EUR", "30.0000"), row("mock", "EUR", "50.0000")] }));
  assert.deepEqual(lines.map((l) => [l.providerKind, l.origin, l.revenue]), [
    ["mock", "Simulado", "50,00 €"],
    ["sandbox", "Entorno de pruebas", "30,00 €"],
  ]);
});

test("E. procedencias × monedas: se conservan las combinaciones que existen, y solo ésas", () => {
  const four = [row("sandbox", "USD", "4.0000"), row("mock", "USD", "3.0000"), row("sandbox", "EUR", "2.0000"), row("mock", "EUR", "1.0000")];
  assert.deepEqual(loaded(summary({ verified: four })).lines.map((l) => l.key), ["EUR·mock", "EUR·sandbox", "USD·mock", "USD·sandbox"]);
  assert.deepEqual(loaded(summary({ verified: four.slice(0, 3) })).lines.map((l) => l.key), ["EUR·sandbox", "USD·mock", "USD·sandbox"]);
});

test("F. verified vacío: empty; ninguna línea, ninguna cifra", () => {
  const figures = revenueFigures(summary());
  assert.equal(figures.kind, "empty");
  assert.equal("lines" in figures, false);
});

test("G. EUR solo en revisión: empty, y la revisión es solo secundaria (aunque el bloque consolidado traiga un cero)", () => {
  const data = summary({
    entries: 1,
    under_review: [review("mock", "EUR", "40.0000")],
    consolidated_eur_by_origin: [{ provider_kind: "mock", currency: "EUR", revenue: "0.0000", refunds: "0.0000", net: "0.0000", under_review_outstanding: "40.0000" }],
  });
  const figures = revenueFigures(data);
  assert.equal(figures.kind, "empty");
  if (figures.kind !== "empty") return;
  assert.deepEqual(figures.secondary.underReview.map((r) => [r.currency, r.amount]), [["EUR", "40,00 €"]]);
});

test("H. contrato roto: error visible, nunca empty", () => {
  for (const broken of [
    { ...summary(), verified: undefined },
    { ...summary(), under_review: undefined },
    { ...summary(), pending_evidence: undefined },
    { ...summary(), non_aggregable_currencies: undefined },
    summary({ verified: [row("mock", "EUR", "1.0000"), row("mock", "EUR", "1.0000")] }),
  ] as unknown as RevenueSummary[]) {
    const figures = revenueFigures(broken);
    assert.equal(figures.kind, "error");
    if (figures.kind === "error") assert.match(figures.message, /El contrato de ingresos cambió/);
  }
});

test("I. net negativo: signo conservado, y el neto es el del backend (no se recalcula)", () => {
  const { lines } = loaded(summary({ entries: 1, verified: [row("mock", "EUR", "0.0000", { refunds: "12.5000", net: "-12.5000", captures: 0, refund_count: 1 })] }));
  assert.equal(lines[0].net, "−12,50 €");
  assert.equal(lines[0].netNegative, true);
  const inconsistent = loaded(summary({ entries: 1, verified: [row("mock", "EUR", "100.0000", { refunds: "10.0000", net: "85.0000" })] }));
  assert.equal(inconsistent.lines[0].net, "85,00 €", "se enseña lo que dijo el backend, aunque no cuadre");
});

test("J. non_aggregable_currencies: una moneda con línea no genera nota; una sola ahí, una nota sin importe; ninguna desaparece", () => {
  const data = summary({
    entries: 2,
    verified: [row("mock", "EUR", "1.0000"), row("mock", "USD", "2.0000")],
    under_review: [review("mock", "CHF", "5.0000")],
    pending_evidence: { count: 1, by_currency: [{ provider_kind: "sandbox", currency: "SEK", event_type: "payment.succeeded", count: 1, amount: "9.0000" }] },
    non_aggregable_currencies: [
      { currency: "USD", reason: "x" },
      { currency: "GBP", reason: "x" },
      { currency: "CHF", reason: "x" },
      { currency: "SEK", reason: "x" },
    ],
  });
  const figures = loaded(data);
  assert.deepEqual(figures.secondary.notes, ["CHF: sin conversión contable disponible", "GBP: sin conversión contable disponible", "SEK: sin conversión contable disponible"]);
  const everything = JSON.stringify(figures);
  for (const currency of ["EUR", "USD", "GBP", "CHF", "SEK"]) assert.ok(everything.includes(currency), `la moneda ${currency} desapareció`);
  assert.deepEqual(summaryFigures(data).nonAggregable, ["CHF", "GBP", "SEK", "USD"]);
});

test("K. ninguna cifra fabricada: todo importe que sale del núcleo procede de una fila de la respuesta", () => {
  const data = summary({
    entries: 3,
    verified: [row("mock", "EUR", "10.0000"), row("sandbox", "USD", "7.0000")],
    under_review: [review("real", "EUR", "3.0000")],
    pending_evidence: { count: 1, by_currency: [{ provider_kind: "mock", currency: "EUR", event_type: "refund.succeeded", count: 1, amount: "2.0000" }] },
  });
  const allowed = new Set([
    ...data.verified.flatMap((r) => [r.revenue, r.refunds, r.net].map((a) => formatMoney(a, r.currency))),
    ...data.under_review.flatMap((r) => [r.received, r.refunded, r.outstanding].map((a) => formatMoney(a, r.currency))),
    ...data.pending_evidence.by_currency.map((r) => formatMoney(r.amount, r.currency)),
  ]);
  const amounts = JSON.stringify(revenueFigures(data)).match(/\d[\d.]*,\d{2,4} (?:€|[A-Z]{3})/g) ?? [];
  assert.ok(amounts.length > 0);
  for (const amount of amounts) assert.ok(allowed.has(amount), `el importe ${amount} no sale de ninguna fila`);
});

test("L. ninguna suma entre monedas ni entre procedencias", () => {
  const values = ["10.0000", "20.0000", "35.5000", "7.2500"];
  const data = summary({
    entries: 4,
    verified: [row("mock", "EUR", values[0]), row("sandbox", "EUR", values[1]), row("real", "EUR", values[2]), row("mock", "USD", values[3])],
  });
  const text = JSON.stringify(revenueFigures(data));
  const numbers = [10, 20, 35.5, 7.25];
  for (let i = 0; i < numbers.length; i++) {
    for (let j = i + 1; j < numbers.length; j++) {
      const sum = (numbers[i] + numbers[j]).toFixed(2).replace(".", ",");
      assert.ok(!text.includes(`"${sum} €"`) && !text.includes(`"${sum} USD"`), `aparece la suma ${sum}`);
    }
  }
  assert.ok(!text.includes("65,50"));
});

test("M. ninguna pérdida de procedencia: las filas de verified, under_review y pending_evidence conservan su origen", () => {
  const data = summary({
    entries: 5,
    verified: [row("mock", "EUR", "1.0000"), row("sandbox", "EUR", "2.0000")],
    under_review: [review("real", "EUR", "3.0000"), review("mock", "EUR", "4.0000", "MISMATCH_RECEIPT")],
    pending_evidence: {
      count: 2,
      by_currency: [
        { provider_kind: "sandbox", currency: "EUR", event_type: "payment.succeeded", count: 1, amount: "5.0000" },
        { provider_kind: "mock", currency: "EUR", event_type: "payment.succeeded", count: 1, amount: "6.0000" },
      ],
    },
  });
  const figures = loaded(data);
  assert.deepEqual(figures.lines.map((l) => l.providerKind), ["mock", "sandbox"]);
  assert.deepEqual(figures.secondary.underReview.map((r) => r.providerKind), ["mock", "real"]);
  assert.deepEqual(figures.secondary.pending.map((r) => [r.providerKind, r.origin, r.amount]), [
    ["mock", "Simulado", "6,00 €"],
    ["sandbox", "Entorno de pruebas", "5,00 €"],
  ]);
});

test("el orden no depende del de la respuesta, y las tablas (`summaryFigures`) son las mismas líneas que las tarjetas", () => {
  const rows = [row("sandbox", "USD", "4.0000"), row("mock", "EUR", "1.0000"), row("real", "EUR", "2.0000"), row("mock", "GBP", "3.0000")];
  const expected = loaded(summary({ entries: 4, verified: rows })).lines;
  for (const permutation of [[...rows].reverse(), [rows[2], rows[0], rows[3], rows[1]]]) {
    assert.deepEqual(loaded(summary({ entries: 4, verified: permutation })).lines, expected);
    assert.deepEqual(summaryFigures(summary({ entries: 4, verified: permutation })).verified, expected);
  }
});

test("el resumen compacto de lo que queda fuera cuenta cosas reales, sin importes", () => {
  const data = summary({ entries: 2, verified: [row("mock", "EUR", "1.0000")], under_review: [review("mock", "EUR", "9.0000")], pending_evidence: { count: 2, by_currency: [] } });
  const figures: RevenueFigures = revenueFigures(data);
  assert.equal(figures.kind === "loaded" ? secondarySummary(figures.secondary) : "", "Fuera de esta cifra: 1 en revisión · 2 sin asentar");
});
