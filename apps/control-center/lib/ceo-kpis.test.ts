import assert from "node:assert/strict";
import { test } from "node:test";
import type { RevenueSummary } from "./api.ts";
import { OUTSIDE_FIGURE_TEXT, UNAVAILABLE_KPIS, ingresosView, linesCountText, readIngresos, secondarySummary } from "./ceo-kpis.ts";
import { assertRevenueSummary } from "./revenue-contract.ts";
import { parseRevenueDays, revenuePath, revenueWindow, type RevenueWindow } from "./revenue-query.ts";
import { settle, type Settled } from "./revenue-view.ts";

// Ingresos del Director ejecutivo (M47, Commit 3A). La unidad de presentación es la pareja ORIGEN × MONEDA, y las cifras salen
// de `verified[]`, nunca de `consolidated_eur_by_origin`. Lo que estas pruebas fijan: una moneda distinta de EUR NO se oculta ni se
// convierte, dos orígenes NO se funden, nada se suma, lo que está en revisión o pendiente es solo información secundaria y no se
// fabrica ningún cero.

const SCOPE = { is_accounting_ledger: false, basis: "verified payment facts", excludes: ["costs", "margin"] };

type VerifiedRow = RevenueSummary["verified"][number];

const verifiedRow = (
  origin: "mock" | "sandbox" | "real",
  currency: string,
  revenue: string,
  over: Partial<VerifiedRow> = {},
): VerifiedRow => ({
  provider_kind: origin,
  currency,
  revenue,
  refunds: "0.0000",
  net: revenue,
  captures: 1,
  refund_count: 0,
  ...over,
});

function summary(over: Partial<RevenueSummary> = {}): RevenueSummary {
  return {
    period: { from: "2026-09-27T00:00:00+00:00", to: "2026-10-04T00:00:00+00:00" },
    entries: 0,
    entries_by_provider_kind: [],
    verified: [],
    under_review: [],
    pending_evidence: { count: 0, by_currency: [] },
    consolidated_eur_by_origin: [],
    non_aggregable_currencies: [],
    scope: SCOPE,
    ...over,
  };
}

const ok = (data: RevenueSummary): Settled<RevenueSummary> => ({ ok: true, data });
const view = (data: RevenueSummary, days = 30) => ingresosView(ok(data), days);

function loadedLines(data: RevenueSummary) {
  const result = view(data);
  assert.equal(result.kind, "loaded", `se esperaba «loaded» y salió «${result.kind}»`);
  return result.kind === "loaded" ? result.lines : [];
}

const duplicateEur = {
  provider_kind: "mock" as const,
  currency: "EUR",
  classification: "DUPLICATE_RECEIPT",
  received: "40.0000",
  refunded: "0.0000",
  outstanding: "40.0000",
  receipts: 1,
  refund_count: 0,
};

// --- A–E. Moneda y procedencia: dos dimensiones, ninguna se pierde -----------------------------------------------------

test("A. solo EUR verificado: loaded, con su cifra en euros, su origen y los importes exactos del backend", () => {
  const lines = loadedLines(
    summary({ entries: 3, verified: [verifiedRow("mock", "EUR", "100.0000", { refunds: "10.0000", net: "90.0000", captures: 2, refund_count: 1 })] }),
  );
  assert.equal(lines.length, 1);
  assert.deepEqual(
    { currency: lines[0].currency, origin: lines[0].origin, revenue: lines[0].revenue, refunds: lines[0].refunds, net: lines[0].net },
    { currency: "EUR", origin: "Simulado", revenue: "100,00 €", refunds: "10,00 €", net: "90,00 €" },
  );
  assert.equal(lines[0].captures, 2);
  assert.equal(lines[0].refundCount, 1);
});

test("B. solo USD verificado: loaded con su importe en USD; NUNCA «Sin datos» ni un cero", () => {
  const data = summary({
    entries: 1,
    verified: [verifiedRow("mock", "USD", "50.0000")],
    non_aggregable_currencies: [{ currency: "USD", reason: "no valid accounting conversion exists yet" }],
  });
  const result = view(data);
  assert.equal(result.kind, "loaded");
  const lines = loadedLines(data);
  assert.deepEqual(lines.map((line) => [line.currency, line.revenue]), [["USD", "50,00 USD"]]);
  assert.doesNotMatch(JSON.stringify(result), /Sin datos|0,00 €/);
});

test("C. EUR + USD: dos líneas separadas, EUR primero, y ninguna cifra es la suma ni una conversión", () => {
  const data = summary({
    entries: 3,
    verified: [verifiedRow("mock", "USD", "30.0000"), verifiedRow("mock", "EUR", "100.0000")],
  });
  const lines = loadedLines(data);
  assert.deepEqual(lines.map((line) => [line.currency, line.revenue]), [["EUR", "100,00 €"], ["USD", "30,00 USD"]]);
  const text = JSON.stringify(view(data));
  for (const forbidden of ["130,00", "130.0000", "70,00"]) assert.ok(!text.includes(forbidden), `aparece ${forbidden}`);
});

test("D. dos procedencias en EUR: se conservan las dos líneas, cada una con su origen; ni «Varios orígenes» ni suma", () => {
  const data = summary({
    entries: 2,
    verified: [verifiedRow("sandbox", "EUR", "30.0000"), verifiedRow("mock", "EUR", "50.0000")],
  });
  const lines = loadedLines(data);
  assert.deepEqual(lines.map((line) => [line.origin, line.currency, line.revenue]), [
    ["Simulado", "EUR", "50,00 €"],
    ["Entorno de pruebas", "EUR", "30,00 €"],
  ]);
  const text = JSON.stringify(view(data));
  assert.doesNotMatch(text, /Varios orígenes|80,00/);
});

test("E. dos procedencias × dos monedas: se conservan las combinaciones que existen, y solo ésas", () => {
  const all = summary({
    entries: 4,
    verified: [
      verifiedRow("sandbox", "USD", "4.0000"),
      verifiedRow("mock", "USD", "3.0000"),
      verifiedRow("sandbox", "EUR", "2.0000"),
      verifiedRow("mock", "EUR", "1.0000"),
    ],
  });
  assert.deepEqual(loadedLines(all).map((line) => line.key), ["EUR·mock", "EUR·sandbox", "USD·mock", "USD·sandbox"]);

  const three = summary({ entries: 3, verified: [verifiedRow("mock", "EUR", "1.0000"), verifiedRow("sandbox", "EUR", "2.0000"), verifiedRow("sandbox", "USD", "4.0000")] });
  assert.deepEqual(loadedLines(three).map((line) => line.key), ["EUR·mock", "EUR·sandbox", "USD·sandbox"], "no se inventa la cuarta combinación");
});

test("las monedas distintas de EUR van por código alfabético, tras EUR, y cada origen en orden determinista", () => {
  const lines = loadedLines(
    summary({
      entries: 5,
      verified: [
        verifiedRow("real", "USD", "1.0000"),
        verifiedRow("mock", "GBP", "1.0000"),
        verifiedRow("mock", "USD", "1.0000"),
        verifiedRow("mock", "EUR", "1.0000"),
        verifiedRow("sandbox", "CHF", "1.0000"),
      ],
    }),
  );
  assert.deepEqual(lines.map((line) => line.key), ["EUR·mock", "CHF·sandbox", "GBP·mock", "USD·mock", "USD·real"]);
});

// --- F. non_aggregable_currencies: contrato informativo, no un «ocultar» ----------------------------------------------

test("F. una moneda en non_aggregable_currencies Y en verified[] se enseña en su línea, sin nota", () => {
  const result = view(
    summary({
      entries: 1,
      verified: [verifiedRow("mock", "USD", "50.0000")],
      non_aggregable_currencies: [{ currency: "USD", reason: "x" }],
    }),
  );
  assert.equal(result.kind, "loaded");
  if (result.kind === "loaded") assert.deepEqual(result.secondary.notes, []);
});

test("F. una moneda SOLO en non_aggregable_currencies no inventa un importe: sale una nota que no parece ingreso", () => {
  const result = view(
    summary({
      entries: 1,
      verified: [verifiedRow("mock", "EUR", "10.0000")],
      non_aggregable_currencies: [{ currency: "GBP", reason: "x" }],
    }),
  );
  assert.equal(result.kind, "loaded");
  if (result.kind !== "loaded") return;
  assert.deepEqual(result.secondary.notes, ["GBP: sin conversión contable disponible"]);
  assert.deepEqual(result.lines.map((line) => line.currency), ["EUR"], "GBP no tiene una línea de ingresos");
});

test("F. ninguna moneda del contrato desaparece: cada moneda de verified, under_review, pending_evidence y non_aggregable sale en la vista", () => {
  const data = summary({
    entries: 5,
    verified: [verifiedRow("mock", "EUR", "1.0000"), verifiedRow("mock", "USD", "2.0000")],
    under_review: [{ ...duplicateEur, currency: "CHF", received: "5.0000", outstanding: "5.0000" }],
    pending_evidence: { count: 2, by_currency: [{ provider_kind: "mock", currency: "SEK", event_type: "payment.succeeded", count: 2, amount: "9.0000" }] },
    non_aggregable_currencies: [
      { currency: "CHF", reason: "x" },
      { currency: "JPY", reason: "x" },
      { currency: "SEK", reason: "x" },
      { currency: "USD", reason: "x" },
    ],
  });
  const text = JSON.stringify(view(data));
  for (const currency of ["EUR", "USD", "CHF", "SEK", "JPY"]) assert.ok(text.includes(currency), `la moneda ${currency} desapareció de la vista`);
});

// --- G, K. Vacío ------------------------------------------------------------------------------------------------------

test("G. verified[] vacío (respuesta vacía): empty, sin líneas, sin ninguna cifra", () => {
  const result = view(summary());
  assert.equal(result.kind, "empty");
  assert.doesNotMatch(JSON.stringify(result), /"revenue"|\d+,\d\d/);
});

test("K. EUR solo en revisión, sin verificado: empty, y NO aparece «0,00 €» como ingreso (aunque consolidated_eur_by_origin traiga un cero)", () => {
  const data = summary({
    entries: 1,
    under_review: [duplicateEur],
    consolidated_eur_by_origin: [
      { provider_kind: "mock", currency: "EUR", revenue: "0.0000", refunds: "0.0000", net: "0.0000", under_review_outstanding: "40.0000" },
    ],
  });
  const result = view(data);
  assert.equal(result.kind, "empty", "para Ingresos verificados sigue siendo vacío");
  if (result.kind !== "empty") return;
  assert.equal(result.secondary.underReview.length, 1);
  assert.equal(result.secondary.underReview[0].amount, "40,00 €");
  assert.doesNotMatch(JSON.stringify(result), /"revenue"|"lines"/);
  assert.equal(JSON.stringify(result).match(/(^|[^\d,.])0,00 €/g), null, "ningún «0,00 €» fabricado");
});

test("G. con verified[] vacío pero evidencia pendiente: sigue siendo empty y la evidencia es solo secundaria", () => {
  const result = view(
    summary({
      pending_evidence: { count: 1, by_currency: [{ provider_kind: "sandbox", currency: "USD", event_type: "refund.succeeded", count: 1, amount: "5.0000" }] },
      non_aggregable_currencies: [{ currency: "USD", reason: "x" }],
    }),
  );
  assert.equal(result.kind, "empty");
  if (result.kind !== "empty") return;
  assert.equal(result.secondary.pendingCount, 1);
  assert.deepEqual(result.secondary.pending.map((line) => [line.origin, line.currency, line.amount]), [["Entorno de pruebas", "USD", "5,00 USD"]]);
});

// --- H. Error: nunca vacío ---------------------------------------------------------------------------------------------

test("H. contrato roto (consolidated_eur presente): error visible; nunca empty ni «Sin datos»", async () => {
  const broken = { ...summary(), consolidated_eur: { revenue: "1.0000" } } as unknown as RevenueSummary;
  const settled = await settle(async () => assertRevenueSummary(broken));
  const result = ingresosView(settled, 30);
  assert.equal(result.kind, "error");
  if (result.kind === "error") assert.match(result.message, /El contrato de ingresos cambió/);
  assert.doesNotMatch(JSON.stringify(result), /Sin datos/);
});

test("H. un origen desconocido en verified[] es un error de contrato, no una línea con otro origen", async () => {
  const broken = summary({ entries: 1, verified: [{ ...verifiedRow("mock", "EUR", "1.0000"), provider_kind: "bank" as never }] });
  const result = ingresosView(await settle(async () => assertRevenueSummary(broken)), 30);
  assert.equal(result.kind, "error");
});

test("H. lectura fallida (HTTP 500, backend caído, 403): error sin repetir el estado HTTP ni el detalle", async () => {
  for (const failure of [{ status: 500, detail: "ECONNREFUSED stack" }, { status: 403, detail: "forbidden" }, new Error("fetch failed")]) {
    const result = ingresosView(
      await settle(async () => {
        throw failure;
      }),
      30,
    );
    assert.equal(result.kind, "error");
    if (result.kind === "error") assert.doesNotMatch(result.message, /500|ECONNREFUSED|stack|fetch failed/);
  }
});

test("H. una respuesta sin forma de resumen (verified no es una lista) es un error, no un vacío", () => {
  const malformed = { ...summary(), verified: undefined } as unknown as RevenueSummary;
  assert.equal(view(malformed).kind, "error");
  const noPending = { ...summary(), pending_evidence: undefined } as unknown as RevenueSummary;
  assert.equal(view(noPending).kind, "error");
});

// --- I. En revisión y evidencia pendiente: secundarias --------------------------------------------------------------

const BASE = summary({ entries: 2, verified: [verifiedRow("mock", "EUR", "100.0000"), verifiedRow("mock", "USD", "20.0000")] });
const WITH_SECONDARY = summary({
  ...BASE,
  entries: 5,
  under_review: [duplicateEur, { ...duplicateEur, currency: "USD", classification: "MISMATCH_RECEIPT", outstanding: "12.5000" }],
  pending_evidence: { count: 3, by_currency: [{ provider_kind: "mock", currency: "EUR", event_type: "payment.succeeded", count: 3, amount: "999.0000" }] },
});

test("I. el dinero en revisión y la evidencia pendiente no cambian NI UNA línea de ingresos verificados", () => {
  assert.deepEqual(loadedLines(WITH_SECONDARY), loadedLines(BASE));
  const text = JSON.stringify(loadedLines(WITH_SECONDARY));
  for (const forbidden of ["140,00", "1.099,00", "999,00", "40,00", "12,50"]) assert.ok(!text.includes(forbidden), `aparece ${forbidden} en lo verificado`);
});

test("I. lo que está fuera de lo verificado se enseña aparte, por origen y moneda, con su etiqueta y sin sumar", () => {
  const result = view(WITH_SECONDARY);
  assert.equal(result.kind, "loaded");
  if (result.kind !== "loaded") return;
  assert.deepEqual(
    result.secondary.underReview.map((line) => [line.currency, line.label, line.amount]),
    [["EUR", "Duplicado · en revisión", "40,00 €"], ["USD", "Discrepancia · en revisión", "12,50 USD"]],
  );
  assert.equal(result.secondary.pendingCount, 3);
  assert.deepEqual(result.secondary.pending.map((line) => [line.label, line.count, line.amount]), [["Cobro sin asentar", 3, "999,00 €"]]);
  assert.match(OUTSIDE_FIGURE_TEXT, /Fuera de esta cifra/);
});

// --- L, P, Q. Importes -------------------------------------------------------------------------------------------------

test("L. un neto negativo se conserva con su signo; el cero medido (hay entradas) se enseña como cero, nunca se oculta", () => {
  const lines = loadedLines(
    summary({ entries: 1, verified: [verifiedRow("mock", "EUR", "0.0000", { refunds: "12.5000", net: "-12.5000", captures: 0, refund_count: 1 })] }),
  );
  assert.equal(lines[0].net, "−12,50 €");
  assert.equal(lines[0].netNegative, true);
  assert.equal(lines[0].revenue, "0,00 €");
  assert.equal(lines[0].refunds, "12,50 €");
});

test("L. un neto cero negativo (-0.0000) no se pinta como negativo", () => {
  const lines = loadedLines(summary({ entries: 2, verified: [verifiedRow("mock", "EUR", "5.0000", { refunds: "5.0000", net: "-0.0000", refund_count: 1 })] }));
  assert.equal(lines[0].net, "0,00 €");
  assert.equal(lines[0].netNegative, false);
});

test("P. el neto es el del backend: no se recalcula como ingresos − reembolsos", () => {
  const lines = loadedLines(summary({ entries: 2, verified: [verifiedRow("mock", "EUR", "100.0000", { refunds: "10.0000", net: "85.0000" })] }));
  assert.equal(lines[0].net, "85,00 €", "se enseña lo que dijo el backend, aunque no cuadre");
  assert.notEqual(lines[0].net, "90,00 €");
});

test("Q. los importes son texto decimal exacto: 17 dígitos sin pérdida, y un texto roto se ve tal cual", () => {
  const lines = loadedLines(summary({ entries: 1, verified: [verifiedRow("mock", "EUR", "12345678901234567.8900")] }));
  assert.equal(lines[0].revenue, "12.345.678.901.234.567,89 €");
  const broken = loadedLines(summary({ entries: 1, verified: [verifiedRow("mock", "EUR", "12abc")] }));
  assert.equal(broken[0].revenue, "12abc EUR", "un contrato roto no se esconde");
});

// --- M, N, O. Ninguna suma silenciosa; orden estable -------------------------------------------------------------------

test("M. ningún importe mostrado es la suma de dos filas (ni de la misma moneda con otro origen, ni de monedas distintas)", () => {
  const amounts = ["10.0000", "20.0000", "35.5000", "7.2500"];
  const rows = [
    verifiedRow("mock", "EUR", amounts[0]),
    verifiedRow("sandbox", "EUR", amounts[1]),
    verifiedRow("real", "EUR", amounts[2]),
    verifiedRow("mock", "USD", amounts[3]),
  ];
  const text = JSON.stringify(view(summary({ entries: 4, verified: rows })));
  const values = [10, 20, 35.5, 7.25];
  for (let i = 0; i < values.length; i++) {
    for (let j = i + 1; j < values.length; j++) {
      const sum = values[i] + values[j];
      const euro = sum.toFixed(2).replace(".", ",");
      assert.ok(!text.includes(`"${euro} €"`) && !text.includes(`"${euro} USD"`), `aparece la suma ${euro}`);
    }
  }
  assert.ok(!text.includes("65,50"), "suma de las tres líneas EUR");
});

test("N. el orden de la respuesta del backend no cambia el orden de presentación", () => {
  const rows = [
    verifiedRow("sandbox", "USD", "4.0000"),
    verifiedRow("mock", "EUR", "1.0000"),
    verifiedRow("real", "EUR", "2.0000"),
    verifiedRow("mock", "GBP", "3.0000"),
  ];
  const expected = loadedLines(summary({ entries: 4, verified: rows }));
  const permutations = [[...rows].reverse(), [rows[2], rows[0], rows[3], rows[1]], [rows[3], rows[2], rows[1], rows[0]]];
  for (const permutation of permutations) assert.deepEqual(loadedLines(summary({ entries: 4, verified: permutation })), expected);
});

test("O. una fila repetida (mismo origen y moneda) no se suma en silencio: es un error de contrato visible", () => {
  const result = view(summary({ entries: 2, verified: [verifiedRow("mock", "EUR", "10.0000"), verifiedRow("mock", "EUR", "10.0000")] }));
  assert.equal(result.kind, "error");
  if (result.kind === "error") assert.match(result.message, /El contrato de ingresos cambió/);
  assert.doesNotMatch(JSON.stringify(result), /20,00/);
});

// --- Selector 7 / 14 / 30: efecto real sobre la consulta ---------------------------------------------------------------

const NOW = Date.UTC(2026, 9, 14, 15, 30, 0);

test("selector: 7, 14 y 30 días piden ventanas distintas y exactas (hoy incluido, `to` exclusivo, UTC)", () => {
  const windows = [7, 14, 30].map((days) => revenueWindow(NOW, days));
  assert.deepEqual(windows, [
    { from: "2026-10-08T00:00:00.000Z", to: "2026-10-15T00:00:00.000Z" },
    { from: "2026-10-01T00:00:00.000Z", to: "2026-10-15T00:00:00.000Z" },
    { from: "2026-09-15T00:00:00.000Z", to: "2026-10-15T00:00:00.000Z" },
  ]);
  const paths = windows.map((window) => revenuePath("summary", { ...window }));
  assert.equal(new Set(paths).size, 3, "tres peticiones distintas");
  assert.equal(paths[0], "/api/revenue/summary?from=2026-10-08T00%3A00%3A00.000Z&to=2026-10-15T00%3A00%3A00.000Z");
});

test("selector: un parámetro inválido, ausente o repetido vuelve a 30 días", () => {
  for (const bad of [undefined, "", "0", "9", "31", "abc", "7.5", "-7"]) assert.equal(parseRevenueDays(bad), 30);
  assert.equal(parseRevenueDays(["14", "7"]), 14, "repetido: se toma el primero, que es un periodo válido");
  assert.equal(parseRevenueDays(["9", "7"]), 30, "repetido y el primero no vale: 30");
});

test("selector: readIngresos pide la ventana elegida; el contenido cambia SOLO si cambian los datos de esa ventana", async () => {
  const asked: RevenueWindow[] = [];
  const byFrom = new Map<string, RevenueSummary>();
  const w7 = revenueWindow(NOW, 7);
  const w14 = revenueWindow(NOW, 14);
  const w30 = revenueWindow(NOW, 30);
  byFrom.set(w7.from, summary({ entries: 1, verified: [verifiedRow("mock", "EUR", "10.0000")] }));
  byFrom.set(w14.from, summary({ entries: 2, verified: [verifiedRow("mock", "EUR", "10.0000"), verifiedRow("mock", "USD", "5.0000")] }));
  byFrom.set(w30.from, summary({ entries: 1, verified: [verifiedRow("mock", "EUR", "10.0000")] }));
  const source = {
    revenueSummary: async (window?: RevenueWindow) => {
      asked.push(window as RevenueWindow);
      return byFrom.get((window as RevenueWindow).from) as RevenueSummary;
    },
  };

  const v7 = await readIngresos(source, w7, 7);
  const v14 = await readIngresos(source, w14, 14);
  const v30 = await readIngresos(source, w30, 30);
  assert.deepEqual(asked, [w7, w14, w30], "cada selección hace una petición con su ventana");

  const keys = (result: typeof v7) => (result.kind === "loaded" ? result.lines.map((line) => line.key) : []);
  assert.deepEqual(keys(v7), ["EUR·mock"]);
  assert.deepEqual(keys(v14), ["EUR·mock", "USD·mock"], "la ventana de 14 días tiene un dato más");
  assert.deepEqual(keys(v30), keys(v7), "mismos datos en la ventana ⇒ mismo contenido");
  assert.deepEqual([v7, v14, v30].map((result) => (result.kind === "loaded" ? result.periodText : "")), ["últimos 7 días (UTC)", "últimos 14 días (UTC)", "últimos 30 días (UTC)"]);
});

test("selector: si la lectura de una ventana falla, el resultado es error (nunca datos de otra ventana ni vacío)", async () => {
  const failing = {
    revenueSummary: async () => {
      throw { status: 503, detail: "down" };
    },
  };
  const result = await readIngresos(failing, revenueWindow(NOW, 14), 14);
  assert.equal(result.kind, "error");
});

// --- Modo compacto: el resumen de «fuera de esta cifra» y el recuento de líneas ----------------------------------------------

test("el resumen compacto de lo que está fuera de la cifra lleva recuentos reales, sin importes ni sumas", () => {
  const result = view(WITH_SECONDARY);
  assert.equal(result.kind, "loaded");
  if (result.kind !== "loaded") return;
  assert.equal(secondarySummary(result.secondary), "Fuera de esta cifra: 2 en revisión · 3 sin asentar");
  assert.doesNotMatch(secondarySummary(result.secondary) ?? "", /€|USD|\d+,\d\d/, "un resumen no lleva importes: no hay nada que sumar");
});

test("el resumen compacto cuenta también las monedas sin conversión y es null si no hay nada fuera de la cifra", () => {
  const withNote = view(
    summary({ entries: 1, verified: [verifiedRow("mock", "EUR", "1.0000")], non_aggregable_currencies: [{ currency: "GBP", reason: "x" }, { currency: "CHF", reason: "x" }] }),
  );
  assert.equal(withNote.kind === "loaded" ? secondarySummary(withNote.secondary) : "", "Fuera de esta cifra: 2 sin conversión");
  const single = view(summary({ entries: 1, verified: [verifiedRow("mock", "EUR", "1.0000")] }));
  assert.equal(single.kind === "loaded" ? secondarySummary(single.secondary) : "x", null);
  const one = view(summary({ under_review: [duplicateEur] }));
  assert.equal(one.kind === "empty" ? secondarySummary(one.secondary) : "", "Fuera de esta cifra: 1 en revisión");
});

test("el recuento de líneas dice cuántas cifras hay (origen × moneda) y no elige ninguna", () => {
  assert.equal(linesCountText(4), "4 cifras · origen × moneda");
  assert.doesNotMatch(linesCountText(2), /\d+,\d\d|€/);
});

test("todo lo que sale fuera de la cifra sigue en el modelo completo (el resumen es solo una vista): nada desaparece", () => {
  const result = view(WITH_SECONDARY);
  assert.equal(result.kind, "loaded");
  if (result.kind !== "loaded") return;
  assert.equal(result.secondary.underReview.length, 2);
  assert.equal(result.secondary.pending.length, 1);
  assert.equal(result.secondary.pending[0].amount, "999,00 €");
});

// --- Los otros tres KPI: no disponibles ------------------------------------------------------------------------------------

test("Beneficio, Margen neto y Cash disponible: «no disponible», sin una sola cifra, sin derivarse de Ingresos", () => {
  assert.deepEqual(UNAVAILABLE_KPIS.map((kpi) => kpi.key), ["beneficio", "margen", "cash"]);
  assert.deepEqual(UNAVAILABLE_KPIS.map((kpi) => kpi.label), ["Beneficio", "Margen neto", "Cash disponible"]);
  for (const kpi of UNAVAILABLE_KPIS) {
    assert.equal(kpi.state.kind, "unavailable");
    assert.ok(kpi.state.kind === "unavailable" && kpi.state.reason.length > 20, "dice por qué");
    assert.doesNotMatch(`${kpi.label} ${kpi.caption} ${kpi.state.reason}`, /\d|€|%/, `${kpi.key} lleva una cifra`);
  }
});

test("el enlace a Finanzas solo está en Beneficio, y no sugiere que la cifra exista", () => {
  const links = UNAVAILABLE_KPIS.filter((kpi) => kpi.link);
  assert.deepEqual(links.map((kpi) => kpi.key), ["beneficio"]);
  assert.equal(links[0].link?.href, "/cfo");
  assert.match(links[0].link?.label ?? "", /no es (el )?beneficio/i);
});
