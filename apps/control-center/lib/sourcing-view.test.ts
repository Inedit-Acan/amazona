import assert from "node:assert/strict";
import { test } from "node:test";
import { DEMO_SALE, DEMO_UNIT_COSTS } from "./demo/economics.ts";
import { demoQuotes, demoSupplierProfile } from "./demo/sourcing.ts";
import {
  DEFAULT_SEARCH,
  averageAxes,
  compatibility,
  filterSuppliers,
  landedBreakdown,
  rankSuppliers,
  supplierRisk,
  topBadges,
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

test("rankSuppliers: score 0–100 de los 7 ejes, de mayor a menor", () => {
  const ranked = rankSuppliers(quotes);
  assert.equal(ranked.length, 5);
  for (let k = 1; k < ranked.length; k++) assert.ok(ranked[k - 1].score >= ranked[k].score);
  for (const r of ranked) {
    assert.equal(Object.keys(r.axes).length, 7);
    const mean = Object.values(r.axes).reduce((a, b) => a + b, 0) / 7;
    assert.equal(r.score, Math.round(mean * 100));
  }
  const avg = averageAxes(ranked);
  assert.ok(avg.price > 0 && avg.price <= 1);
});

test("supplierRisk: fiabilidad baja es Alto; sin verificar, Medio", () => {
  const [q] = quotes;
  const profile = demoSupplierProfile(q);
  assert.equal(supplierRisk({ ...q, reliability_score: 0.7 }, profile), "Alto");
  assert.equal(supplierRisk({ ...q, verified: false }, profile), "Medio");
  assert.equal(supplierRisk(q, { ...profile, compliance: 0.95 }), "Bajo");
});

test("topBadges: recomendado, mejor opción UE y mejor precio sin repetir", () => {
  const ranked = rankSuppliers(quotes);
  const badges = topBadges(ranked, "eu");
  assert.equal(badges.get(ranked[0].quote.id), "Proveedor recomendado");
  assert.ok([...badges.values()].includes("Mejor precio"));
  assert.equal(new Set(badges.values()).size, badges.size);
});

test("landedBreakdown: suma coherente con los supuestos de Economía", () => {
  const lines = landedBreakdown(quotes[0]);
  const total = lines.find((l) => l.total)!;
  const parts = lines.filter((l) => !l.total).reduce((s, l) => s + l.amount, 0);
  assert.ok(Math.abs(total.amount - parts) < 1e-9);
  const payment = lines.find((l) => l.key === "payment")!.amount;
  assert.ok(Math.abs(payment - (DEMO_SALE.salePrice * DEMO_UNIT_COSTS.paymentFeePct) / 100) < 1e-9);
  assert.ok(Math.abs(lines[1].amount + lines[2].amount - quotes[0].logistics_cost_per_unit) < 1e-9);
});

test("compatibility: el MOQ bajo sale de la cotización", () => {
  const profile = demoSupplierProfile(quotes[2]);
  const items = compatibility(quotes[2], profile);
  assert.equal(items.length, 8);
  assert.equal(items.find((i) => i.label === "MOQ bajo (≤ 10)")!.ok, false);
  assert.equal(compatibility(quotes[0], demoSupplierProfile(quotes[0])).find((i) => i.label === "MOQ bajo (≤ 10)")!.ok, true);
});

test("filterSuppliers: origen, precio, plazo, MOQ, certificación y verificados", () => {
  const ranked = rankSuppliers(quotes);
  const base = { ...DEFAULT_SEARCH, logistics: "any" };
  assert.equal(filterSuppliers(ranked, base).length, 5);
  assert.ok(filterSuppliers(ranked, { ...base, origin: "eu" }).every((r) => r.quote.data?.region === "eu"));
  assert.ok(filterSuppliers(ranked, { ...base, maxPrice: "9" }).every((r) => r.quote.unit_price <= 9));
  assert.ok(filterSuppliers(ranked, { ...base, minPrice: "9" }).every((r) => r.quote.unit_price >= 9));
  assert.ok(filterSuppliers(ranked, { ...base, maxLeadTime: "7" }).every((r) => r.quote.lead_time_days <= 7));
  assert.ok(filterSuppliers(ranked, { ...base, maxMoq: "10" }).every((r) => r.quote.moq <= 10));
  assert.ok(filterSuppliers(ranked, { ...base, verifiedOnly: true }).every((r) => r.quote.verified));
  assert.ok(filterSuppliers(ranked, { ...base, requireCertification: true }).every((r) => !r.profile.certificationPending));
  assert.ok(filterSuppliers(ranked, { ...base, logistics: "direct" }).every((r) => r.profile.directShipping));
});
