import assert from "node:assert/strict";
import { test } from "node:test";
import { DEMO_SALE, DEMO_UNIT_COSTS } from "./demo/economics.ts";
import { demoQuotes, demoSupplierProfile } from "./demo/sourcing.ts";
import { quoteFixture } from "./quote-fixture.ts";
import {
  DEFAULT_SEARCH,
  averageAxes,
  compatibility,
  filterSuppliers,
  landedBreakdown,
  rankSuppliers,
  supplierRisk,
  topBadges,
  unassessedRisk,
} from "./sourcing-view.ts";

const quotes = demoQuotes("p1");

test("demoQuotes y demoSupplierProfile: deterministas y coherentes", () => {
  assert.equal(quotes.length, 5);
  assert.equal(quotes[0].total_landed_cost_per_unit, 10.86);
  assert.deepEqual(demoSupplierProfile(quotes[1]), demoSupplierProfile(quotes[1]));
  const eu = demoSupplierProfile(quotes[1]);
  assert.equal(eu.country, "Polonia");
  assert.ok(eu.delivery[0] <= 2);
});

test("demoQuotes: un proveedor de demostración no lo ha verificado nadie", () => {
  // Antes decía «verified» si su fiabilidad pasaba de 0,85. Lo escribió un
  // fichero, y eso es lo que dice ahora.
  for (const quote of quotes) {
    assert.equal(quote.supplier?.verification, "simulated");
    assert.equal(quote.provenance, "simulated");
  }
});

test("rankSuppliers: score 0–100 de los 7 ejes, de mayor a menor", () => {
  const ranked = rankSuppliers(quotes);
  assert.equal(ranked.length, 5);
  for (let k = 1; k < ranked.length; k++) {
    assert.ok((ranked[k - 1].score ?? 0) >= (ranked[k].score ?? 0));
  }
  for (const r of ranked) {
    assert.equal(Object.keys(r.axes).length, 7);
    assert.equal(r.knownAxes, 7);
    const values = Object.values(r.axes).filter((v): v is number => v !== null);
    const mean = values.reduce((a, b) => a + b, 0) / 7;
    assert.equal(r.score, Math.round(mean * 100));
  }
  const avg = averageAxes(ranked);
  assert.ok((avg.price ?? 0) > 0 && (avg.price ?? 0) <= 1);
});

test("rankSuppliers: sin un eje no hay nota, y eso NO es una nota baja", () => {
  // Promediar lo que falta como cero convertiría a un proveedor del que no se
  // sabe nada en uno malo (Milestone 39).
  const incomplete = quoteFixture({ id: "q-sin-precio", unit_price: null, moq: null });

  const [ranked] = rankSuppliers([incomplete]);

  assert.equal(ranked.score, null);
  assert.ok(ranked.knownAxes < 7);
  assert.equal(ranked.axes.price, null);
  assert.equal(ranked.axes.flexibility, null);
});

test("rankSuppliers: una fiabilidad que nadie ha valorado no vale cero", () => {
  const unrated = quoteFixture({
    supplier: { reliability_score: null, reliability_provenance: null },
  });

  const [ranked] = rankSuppliers([unrated]);

  assert.equal(ranked.axes.reliability, null);
  assert.equal(ranked.score, null);
});

test("averageAxes: un eje que nadie declara no tiene media", () => {
  const ranked = rankSuppliers([
    quoteFixture({ supplier: { reliability_score: null, reliability_provenance: null } }),
  ]);

  assert.equal(averageAxes(ranked).reliability, null);
});

test("supplierRisk: el peor nivel de las dimensiones evaluadas, no una media", () => {
  const risky = quoteFixture({
    risk: [
      { dimension: "identity", level: "low", rationale: "x", provenance: "amazona_estimate", basis: [] },
      { dimension: "fraud", level: "high", rationale: "y", provenance: "amazona_estimate", basis: [] },
      { dimension: "legal", level: "low", rationale: "z", provenance: "amazona_estimate", basis: [] },
    ],
  });

  // Una dimensión en rojo no se compensa con dos en verde.
  assert.equal(supplierRisk(risky), "Alto");
});

test("supplierRisk: sin ninguna dimensión evaluada es «Sin evaluar», no «Bajo»", () => {
  const unassessed = quoteFixture({
    risk: [
      { dimension: "identity", level: "unknown", rationale: "nadie lo ha mirado", provenance: "unknown", basis: [] },
    ],
  });

  assert.equal(supplierRisk(unassessed), "Sin evaluar");
  assert.deepEqual(unassessedRisk(unassessed), ["identity"]);
  assert.equal(supplierRisk(quoteFixture({ risk: [] })), "Sin evaluar");
});

test("topBadges: recomendado, mejor opción UE y mejor precio sin repetir", () => {
  const ranked = rankSuppliers(quotes);
  const badges = topBadges(ranked, "eu");
  assert.equal(badges.get(ranked[0].quote.id), "Proveedor recomendado");
  assert.ok([...badges.values()].includes("Mejor precio"));
  assert.equal(new Set(badges.values()).size, badges.size);
});

test("topBadges: un proveedor sin precio no puede ser «mejor precio»", () => {
  const ranked = rankSuppliers([
    quoteFixture({ id: "a", supplier_id: "s-a", unit_price: 5 }),
    quoteFixture({ id: "b", supplier_id: "s-b", unit_price: 9 }),
    quoteFixture({ id: "c", supplier_id: "s-c", unit_price: null, total_landed_cost_per_unit: null }),
  ]);

  const badges = topBadges(ranked, "eu");

  assert.ok(!badges.get("c")?.includes("precio"));
});

test("landedBreakdown: suma coherente con los supuestos de Economía", () => {
  const lines = landedBreakdown(quotes[0])!;
  const total = lines.find((l) => l.total)!;
  const parts = lines.filter((l) => !l.total).reduce((s, l) => s + l.amount, 0);
  assert.ok(Math.abs(total.amount - parts) < 1e-9);
  const payment = lines.find((l) => l.key === "payment")!.amount;
  assert.ok(Math.abs(payment - (DEMO_SALE.salePrice * DEMO_UNIT_COSTS.paymentFeePct) / 100) < 1e-9);
  assert.ok(Math.abs(lines[1].amount + lines[2].amount - (quotes[0].logistics_cost_per_unit ?? 0)) < 1e-9);
});

test("landedBreakdown: sin precio o sin logística no hay desglose, y no se rellena con ceros", () => {
  assert.equal(landedBreakdown(quoteFixture({ unit_price: null })), null);
  assert.equal(landedBreakdown(quoteFixture({ logistics_cost_per_unit: null })), null);
});

test("compatibility: el MOQ sale de la cotización y las capacidades, de lo declarado", () => {
  const items = compatibility(quotes[2]);
  assert.equal(items.length, 9);
  assert.equal(items.find((i) => i.label === "MOQ bajo (≤ 10)")!.ok, false);
  assert.equal(compatibility(quotes[0]).find((i) => i.label === "MOQ bajo (≤ 10)")!.ok, true);
});

test("compatibility: lo que nadie ha declarado es null, nunca false", () => {
  // La confusión que el Milestone 39 quitó del backend no se recomete aquí.
  const items = compatibility(quoteFixture({ capabilities: [] }));

  for (const item of items.filter((i) => i.label !== "MOQ bajo (≤ 10)")) {
    assert.equal(item.ok, null, item.label);
    assert.equal(item.provenance, "unknown");
  }
});

test("compatibility: un MOQ no declarado tampoco es «no cumple»", () => {
  const items = compatibility(quoteFixture({ moq: null }));

  assert.equal(items.find((i) => i.label === "MOQ bajo (≤ 10)")!.ok, null);
});

test("compatibility: una capacidad declarada trae su procedencia y su nota", () => {
  const items = compatibility(
    quoteFixture({
      capabilities: [
        {
          capability: "dropshipping",
          supported: true,
          provenance: "supplier_claim",
          source: null,
          note: "desde 20 unidades",
          observed_at: null,
          product_specific: false,
        },
      ],
    }),
  );

  const dropshipping = items.find((i) => i.label.startsWith("Dropshipping"))!;
  assert.equal(dropshipping.ok, true);
  assert.equal(dropshipping.provenance, "supplier_claim");
  assert.equal(dropshipping.note, "desde 20 unidades");
});

test("filterSuppliers: origen, precio, plazo, MOQ, certificación y verificados", () => {
  const ranked = rankSuppliers(quotes);
  const base = { ...DEFAULT_SEARCH, logistics: "any" };
  assert.equal(filterSuppliers(ranked, base).length, 5);
  assert.ok(filterSuppliers(ranked, { ...base, origin: "eu" }).every((r) => r.quote.supplier?.region === "eu"));
  assert.ok(filterSuppliers(ranked, { ...base, maxPrice: "9" }).every((r) => (r.quote.unit_price ?? 0) <= 9));
  assert.ok(filterSuppliers(ranked, { ...base, minPrice: "9" }).every((r) => (r.quote.unit_price ?? 0) >= 9));
  assert.ok(filterSuppliers(ranked, { ...base, maxLeadTime: "7" }).every((r) => (r.quote.lead_time_days ?? 0) <= 7));
  assert.ok(filterSuppliers(ranked, { ...base, maxMoq: "10" }).every((r) => (r.quote.moq ?? 0) <= 10));
  assert.ok(
    filterSuppliers(ranked, { ...base, requireCertification: true }).every((r) => !r.profile.certificationPending),
  );
});

test("filterSuppliers: un dato desconocido no pasa un filtro numérico", () => {
  // Quien pide «MOQ ≤ 10» no está pidiendo «MOQ ≤ 10 o que no se sepa».
  const ranked = rankSuppliers([quoteFixture({ moq: null, unit_price: null })]);

  assert.equal(filterSuppliers(ranked, { ...DEFAULT_SEARCH, maxMoq: "10" }).length, 0);
  assert.equal(filterSuppliers(ranked, { ...DEFAULT_SEARCH, maxPrice: "100" }).length, 0);
  // Sin filtro, sigue estando: no saber no es motivo para ocultarlo.
  assert.equal(filterSuppliers(ranked, DEFAULT_SEARCH).length, 1);
});

test("filterSuppliers: «verificados» significa verificados por un tercero", () => {
  const ranked = rankSuppliers([
    quoteFixture({ id: "audited", supplier_id: "s-a" }),
    quoteFixture({
      id: "claimed",
      supplier_id: "s-b",
      supplier: { verification: "supplier_claim", verified_by: null },
    }),
  ]);

  const verified = filterSuppliers(ranked, { ...DEFAULT_SEARCH, verifiedOnly: true });

  assert.deepEqual(
    verified.map((r) => r.quote.id),
    ["audited"],
  );
});

test("filterSuppliers: «declara envío directo» exige una declaración, no un supuesto", () => {
  const ranked = rankSuppliers([
    quoteFixture({
      id: "declares",
      supplier_id: "s-a",
      capabilities: [
        {
          capability: "direct_shipping",
          supported: true,
          provenance: "supplier_claim",
          source: null,
          note: null,
          observed_at: null,
          product_specific: false,
        },
      ],
    }),
    quoteFixture({ id: "silent", supplier_id: "s-b", capabilities: [] }),
  ]);

  const direct = filterSuppliers(ranked, { ...DEFAULT_SEARCH, logistics: "direct" });

  assert.deepEqual(
    direct.map((r) => r.quote.id),
    ["declares"],
  );
});

test("DEFAULT_SEARCH arranca en «cualquiera»: filtrar por envío directo vaciaría la pantalla", () => {
  // Parecería que no hay proveedores, cuando lo que no hay son respuestas.
  assert.equal(DEFAULT_SEARCH.logistics, "any");
});

test("landedBreakdown: un precio en otra moneda no se suma a costes en euros", () => {
  // Daría un total con símbolo de euro que no es euros, que es la misma mentira
  // que el backend se niega a contar cuando no hay tipo de cambio.
  assert.equal(landedBreakdown(quoteFixture({ currency: "USD" })), null);
  assert.equal(landedBreakdown(quoteFixture({ currency: null })), null);
  assert.notEqual(landedBreakdown(quoteFixture({ currency: "EUR" })), null);
});
