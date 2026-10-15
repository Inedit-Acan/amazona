import assert from "node:assert/strict";
import { test } from "node:test";
import type { RevenueSummary } from "./api.ts";
import { ingresosView } from "./ceo-kpis.ts";
import { formatMoney } from "./revenue-format.ts";
import { NO_DATA, revenueKpis, summaryView, verifiedMetricKpis } from "./revenue-view.ts";

// REGRESIÓN ENTRE SUPERFICIES (M47, 3A.1): `/ceo`, `/dashboard` y `/cfo` sobre el MISMO fixture. Las presentaciones pueden diferir (una tarjeta
// con líneas, tres tarjetas compactas, una tabla); los HECHOS económicos no. El oráculo es independiente del núcleo: sale de las filas crudas del
// fixture y de `formatMoney`, no de `revenueFigures`.

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

const review = (origin: Origin, currency: string, outstanding: string) => ({
  provider_kind: origin,
  currency,
  classification: "DUPLICATE_RECEIPT",
  received: outstanding,
  refunded: "0.0000",
  outstanding,
  receipts: 1,
  refund_count: 0,
});

const base = (over: Partial<RevenueSummary>): RevenueSummary => ({
  period: {},
  entries: 1,
  entries_by_provider_kind: [],
  verified: [],
  under_review: [],
  pending_evidence: { count: 0, by_currency: [] },
  consolidated_eur_by_origin: [],
  non_aggregable_currencies: [],
  scope: SCOPE,
  ...over,
});

const FIXTURES: Record<string, RevenueSummary> = {
  "solo EUR": base({ verified: [row("mock", "EUR", "100.0000", { refunds: "10.0000", net: "90.0000" })] }),
  "solo USD": base({ verified: [row("mock", "USD", "50.0000")], non_aggregable_currencies: [{ currency: "USD", reason: "x" }] }),
  "EUR + USD": base({ verified: [row("mock", "USD", "30.0000"), row("mock", "EUR", "100.0000")], non_aggregable_currencies: [{ currency: "USD", reason: "x" }] }),
  "dos procedencias EUR": base({ verified: [row("sandbox", "EUR", "30.0000"), row("mock", "EUR", "50.0000")] }),
  "procedencias × monedas": base({
    verified: [row("sandbox", "USD", "4.0000"), row("mock", "USD", "3.0000"), row("sandbox", "EUR", "2.0000"), row("mock", "EUR", "1.0000")],
    // Importes de revisión y pendiente que NO coinciden con ninguna suma de las filas verificadas (para que la comprobación de sumas sea fiable).
    under_review: [review("real", "GBP", "13.2500")],
    pending_evidence: { count: 1, by_currency: [{ provider_kind: "sandbox", currency: "EUR", event_type: "payment.succeeded", count: 1, amount: "11.5000" }] },
    non_aggregable_currencies: [{ currency: "USD", reason: "x" }, { currency: "GBP", reason: "x" }],
  }),
  "net negativo": base({ verified: [row("mock", "EUR", "0.0000", { refunds: "12.5000", net: "-12.5000", captures: 0, refund_count: 1 })] }),
  "verified vacío": base({ entries: 0 }),
  "EUR solo en revisión": base({
    under_review: [review("mock", "EUR", "40.0000")],
    consolidated_eur_by_origin: [{ provider_kind: "mock", currency: "EUR", revenue: "0.0000", refunds: "0.0000", net: "0.0000", under_review_outstanding: "40.0000" }],
  }),
};

const BROKEN: Record<string, RevenueSummary> = {
  "fila repetida": base({ verified: [row("mock", "EUR", "1.0000"), row("mock", "EUR", "2.0000")] }),
  "sin forma": { ...base({}), under_review: undefined } as unknown as RevenueSummary,
};

/** El oráculo: las líneas que DEBEN existir, a partir de las filas crudas. */
const expectedLines = (data: RevenueSummary) =>
  data.verified.map((r) => ({
    key: `${r.currency}·${r.provider_kind}`,
    revenue: formatMoney(r.revenue, r.currency),
    refunds: formatMoney(r.refunds, r.currency),
    net: formatMoney(r.net, r.currency),
  }));

const byKey = <T extends { key: string }>(items: T[]) => [...items].sort((a, b) => (a.key < b.key ? -1 : 1));

for (const [name, data] of Object.entries(FIXTURES)) {
  test(`mismos hechos en las tres superficies · ${name}`, () => {
    const want = byKey(expectedLines(data));

    // /ceo: la tarjeta de Ingresos.
    const ceo = ingresosView({ ok: true, data }, 30);
    const ceoLines = ceo.kind === "loaded" ? byKey(ceo.lines.map((l) => ({ key: l.key, revenue: l.revenue, refunds: l.refunds, net: l.net }))) : [];

    // /dashboard y /cfo: la tabla de la misma página (mismas filas) y las tarjetas.
    const table = summaryView(data).verified;
    const tableLines = byKey(table.map((r) => ({ key: `${r.currency}·${r.providerKind}`, revenue: r.revenue, refunds: r.refunds, net: r.net })));
    const dash = revenueKpis(data);
    const cfo = verifiedMetricKpis(data);
    assert.equal(dash.kind, "ok");
    assert.equal(cfo.kind, "ok");
    if (dash.kind !== "ok" || cfo.kind !== "ok") return;

    // 1 · las tres superficies enseñan las MISMAS líneas, cada una con los MISMOS importes que el oráculo.
    assert.deepEqual(ceoLines, want);
    assert.deepEqual(tableLines, want);

    // 2 · el veredicto es el mismo: vacío ⇔ vacío ⇔ «Sin datos»; una línea ⇔ la cifra; varias ⇔ «N cifras» y ninguna elegida.
    const verdict = want.length === 0 ? "empty" : want.length === 1 ? "one" : "many";
    assert.equal(ceo.kind, want.length === 0 ? "empty" : "loaded");
    assert.equal(dash.verified.value === NO_DATA ? "empty" : dash.verified.detail ? "many" : "one", verdict);
    for (const card of [cfo.revenue, cfo.refunds, cfo.net]) assert.equal(card.value === NO_DATA ? "empty" : card.detail ? "many" : "one", verdict);
    if (verdict === "one") {
      assert.equal(dash.verified.value, want[0].revenue);
      assert.deepEqual([cfo.revenue.value, cfo.refunds.value, cfo.net.value], [want[0].revenue, want[0].refunds, want[0].net]);
    }
    if (verdict === "many") {
      for (const text of [dash.verified.value, cfo.revenue.value, cfo.refunds.value, cfo.net.value]) assert.equal(text, `${want.length} cifras`);
    }

    // 3 · la revisión es secundaria en las tres y nunca entra en lo verificado.
    const reviewAmounts = data.under_review.map((r) => formatMoney(r.outstanding, r.currency));
    for (const amount of reviewAmounts) {
      assert.ok(!want.some((l) => [l.revenue, l.refunds, l.net].includes(amount)) || data.verified.length > 0);
      for (const text of [dash.verified.value, dash.verified.caption, cfo.revenue.value, cfo.net.value]) {
        assert.ok(!text.includes(amount), `la partida en revisión ${amount} aparece como verificada: «${text}»`);
      }
    }
    if (data.under_review.length === 1 && data.verified.length === 0) assert.equal(dash.underReview.value, reviewAmounts[0]);

    // 4 · ninguna suma entre monedas ni procedencias, en ninguna superficie.
    const everything = JSON.stringify([ceo, table, dash, cfo]);
    const raw = data.verified.map((r) => ({ n: Number(r.revenue), currency: r.currency }));
    for (let i = 0; i < raw.length; i++) {
      for (let j = i + 1; j < raw.length; j++) {
        const sum = (raw[i].n + raw[j].n).toFixed(2).replace(".", ",");
        if (raw.some((x) => x.n.toFixed(2).replace(".", ",") === sum)) continue;
        assert.ok(!everything.includes(`"${sum} €"`) && !everything.includes(`"${sum} USD"`), `aparece la suma ${sum}`);
      }
    }

    // 5 · ninguna pérdida de procedencia: cada origen de las filas crudas sale en las líneas de /ceo y en la tabla.
    for (const r of data.verified) {
      assert.ok(ceoLines.some((l) => l.key === `${r.currency}·${r.provider_kind}`));
      assert.ok(table.some((t) => t.providerKind === r.provider_kind && t.currency === r.currency));
    }
  });
}

for (const [name, data] of Object.entries(BROKEN)) {
  test(`contrato roto · ${name}: error en las tres superficies, nunca «Sin datos»`, () => {
    assert.equal(ingresosView({ ok: true, data }, 30).kind, "error");
    assert.equal(revenueKpis(data).kind, "error");
    assert.equal(verifiedMetricKpis(data).kind, "error");
  });
}

test("una lectura fallida es error en /ceo; en las otras dos lo gestiona su página (nunca vacío)", () => {
  assert.equal(ingresosView({ ok: false, message: "No se pudieron cargar los ingresos." }, 30).kind, "error");
});
