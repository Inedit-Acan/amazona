import assert from "node:assert/strict";
import { test } from "node:test";
import { DEMO_CHANNELS, DEMO_EU_MARKETS } from "./demo/storefront.ts";
import { channelCards, marketConfig, purchaseFunnel, readinessRatio, storeQuality } from "./storefront-view.ts";

test("readinessRatio: cuenta solo lo cumplido", () => {
  assert.equal(
    readinessRatio([
      { key: "a", label: "A", state: "done", detail: "" },
      { key: "b", label: "B", state: "todo", detail: "" },
      { key: "c", label: "C", state: "pending", detail: "" },
      { key: "d", label: "D", state: "done", detail: "" },
    ]),
    0.5,
  );
  assert.equal(readinessRatio([]), 0);
});

test("channelCards: estado real de tienda y listado; demo para los canales sin integración", () => {
  const cards = channelCards({ storefront: { launch_status: "READY" }, storeReadiness: 0.8 });
  assert.deepEqual(cards.map((c) => c.key), ["store", "amazon", "google", "tiktok"]);
  assert.equal(cards[0].status, "Activo");
  assert.equal(cards[0].readiness, 0.8);
  assert.equal(cards[1].isDemo, true);
  assert.equal(cards[1].readiness, DEMO_CHANNELS.amazon.readiness);
  const withListing = channelCards({ listing: { listing_status: "BLOCKED" }, storeReadiness: 0 });
  assert.equal(withListing[0].status, "Sin generar");
  assert.equal(withListing[1].status, "Bloqueado");
  assert.equal(withListing[1].isDemo, false);
});

test("purchaseFunnel: las compras son los pedidos y la conversión la de Economía", () => {
  const { steps, conversion } = purchaseFunnel(300, 2.8);
  assert.equal(steps[0].value, 10714);
  assert.equal(steps[4].value, 300);
  for (let k = 1; k < steps.length; k++) assert.ok(steps[k].value <= steps[k - 1].value);
  assert.ok(Math.abs(conversion - 0.028) < 0.0001);
  assert.equal(purchaseFunnel(300, 0).conversion, 0);
});

test("storeQuality: media de los siete ejes y etiqueta", () => {
  const q = storeQuality(1, 0.7);
  assert.equal(q.axes.length, 7);
  assert.equal(q.axes[0].value, 100);
  assert.equal(q.axes[4].value, 70);
  assert.equal(q.score, Math.round(q.axes.reduce((s, a) => s + a.value, 0) / 7));
  assert.equal(storeQuality(0, 0).label, "Mejorable");
});

test("marketConfig: países de la UE con el precio aprobado y mercados reales añadidos", () => {
  const rows = marketConfig(29.9, [
    { market: "us", launch_status: "NEEDS_REVIEW", data: { catalog_entry: { sku: "x", price: 35, category: "c", market: "us", restricted: false, lead_time_days: 5 } } },
    { market: "eu", launch_status: "READY", data: null },
  ]);
  assert.equal(rows.length, DEMO_EU_MARKETS.length + 1);
  assert.equal(rows[0].price, 29.9);
  assert.equal(rows[0].status, "Activo");
  assert.equal(rows[1].price, 30.9);
  const us = rows.find((r) => r.key === "us")!;
  assert.equal(us.price, 35);
  assert.equal(us.status, "Preparación");
});
