import assert from "node:assert/strict";
import { test } from "node:test";
import type { ApiProviderUsage } from "./api.ts";
import {
  apiUsageSummary,
  authorisationLabel,
  buildApiUsageRows,
  deniedLabel,
  quotaStatusOf,
  unitLabel,
} from "./api-usage-view.ts";

const usage = (over: Partial<ApiProviderUsage> = {}): ApiProviderUsage => ({
  provider: "ebay-browse",
  pricing: "free",
  unit: "requests",
  units_today: 8,
  denied_today: 0,
  last_denied_reason: null,
  estimated_cost_today: 0,
  actual_cost_today: null,
  currency: "EUR",
  quota_units_per_day: 5000,
  max_units_per_run: 8,
  authorised_cost_per_day: null,
  authorised_cost_per_run: null,
  source: "developer.ebay.com",
  ...over,
});

test("el consumo se lee contra la cuota publicada", () => {
  const [row] = buildApiUsageRows([usage()]);

  assert.equal(row.consumption, "8 de 5000 peticiones");
  assert.equal(row.quotaPercent, 0);
  assert.equal(row.quotaStatus, "holgado");
});

test("sin cuota publicada no hay barra que dibujar, y eso no es un cero", () => {
  const [row] = buildApiUsageRows([usage({ quota_units_per_day: null, units_today: 12 })]);

  assert.equal(row.consumption, "12 peticiones");
  assert.equal(row.quotaPercent, null);
  assert.equal(row.quotaStatus, "sin-limite");
});

test("quotaStatusOf avisa antes de agotarse", () => {
  assert.equal(quotaStatusOf(0, 100), "holgado");
  assert.equal(quotaStatusOf(79, 100), "holgado");
  assert.equal(quotaStatusOf(80, 100), "ajustado");
  assert.equal(quotaStatusOf(100, 100), "agotado");
  assert.equal(quotaStatusOf(120, 100), "agotado");
  assert.equal(quotaStatusOf(5, null), "sin-limite");
});

test("lo que el proveedor no ha cobrado todavía se queda ausente", () => {
  const [row] = buildApiUsageRows([usage()]);

  assert.equal(row.estimatedCost, "0.00 EUR");
  assert.equal(row.actualCost, null);
});

test("cuando el proveedor dice lo que cobró, se enseña", () => {
  const [row] = buildApiUsageRows([usage({ actual_cost_today: 1.5 })]);

  assert.equal(row.actualCost, "1.50 EUR");
});

test("un proveedor de pago sin autorización dice que no se llamará", () => {
  assert.equal(
    authorisationLabel(usage({ pricing: "paid" })),
    "Sin gasto autorizado — no se llamará",
  );
});

test("un proveedor gratuito sin autorización no es un problema", () => {
  assert.match(authorisationLabel(usage()), /no hace falta/);
});

test("los límites autorizados se enseñan con su moneda", () => {
  const label = authorisationLabel(
    usage({ pricing: "paid", authorised_cost_per_day: 10, authorised_cost_per_run: 0.5 }),
  );

  assert.equal(label, "Autorizado: 10.00 EUR/día · 0.50 EUR/ejecución");
});

test("una denegación se cuenta y se explica", () => {
  assert.equal(deniedLabel(usage()), null);
  assert.equal(
    deniedLabel(usage({ denied_today: 1, last_denied_reason: "sin cuota" })),
    "1 llamada denegada hoy: sin cuota",
  );
  assert.equal(deniedLabel(usage({ denied_today: 3 })), "3 llamadas denegadas hoy");
});

test("el resumen suma llamadas y gasto, y solo menciona denegaciones si las hay", () => {
  assert.equal(
    apiUsageSummary([usage({ units_today: 4 }), usage({ provider: "wikimedia-pageviews", units_today: 6 })]),
    "10 llamadas hoy · 0.00 EUR estimados",
  );
  assert.match(apiUsageSummary([usage({ denied_today: 2 })])!, /2 denegadas/);
});

test("sin proveedores no se inventa un resumen de cero", () => {
  assert.equal(apiUsageSummary([]), null);
});

test("las unidades se dicen en castellano y lo desconocido se deja tal cual", () => {
  assert.equal(unitLabel("requests"), "peticiones");
  assert.equal(unitLabel("tokens"), "tokens");
  assert.equal(unitLabel("unidades-raras"), "unidades-raras");
});

test("cada fila conserva dónde se comprobaron sus cifras", () => {
  const [row] = buildApiUsageRows([usage()]);

  assert.equal(row.source, "developer.ebay.com");
});
