import assert from "node:assert/strict";
import { test } from "node:test";
import type { RevenueEntriesPage, RevenueSeries, RevenueSummary } from "./api.ts";
import {
  PROVIDER_KINDS,
  RevenueContractError,
  assertRevenueEntries,
  assertRevenueSeries,
  assertRevenueSummary,
} from "./revenue-contract.ts";
import { settle } from "./revenue-view.ts";

// El contrato de procedencia de los ingresos (M46, Commit 3, ADR 0031): lo que llega sin origen, con el origen
// desconocido o con el total antiguo que sumaba orígenes FALLA a la vista; nunca se completa con «mock» ni se lee como
// «Sin datos».

const SCOPE = { is_accounting_ledger: false, basis: "x", excludes: [] };

function good(over: Partial<RevenueSummary> = {}): RevenueSummary {
  return {
    period: {},
    entries: 2,
    entries_by_provider_kind: [{ provider_kind: "mock", entries: 2 }],
    verified: [
      { provider_kind: "mock", currency: "EUR", revenue: "20.0000", refunds: "0.0000", net: "20.0000", captures: 1, refund_count: 0 },
    ],
    under_review: [],
    pending_evidence: { count: 0, by_currency: [] },
    consolidated_eur_by_origin: [
      { provider_kind: "mock", currency: "EUR", revenue: "20.0000", refunds: "0.0000", net: "20.0000", under_review_outstanding: "0.0000" },
    ],
    non_aggregable_currencies: [],
    scope: SCOPE,
    ...over,
  };
}

test("el vocabulario de orígenes es exactamente el del backend: mock, sandbox y real", () => {
  assert.deepEqual([...PROVIDER_KINDS], ["mock", "sandbox", "real"]);
});

test("una respuesta con el contrato nuevo pasa tal cual, sin tocarla", () => {
  const summary = good();
  assert.equal(assertRevenueSummary(summary), summary);
});

test("el total antiguo que sumaba todos los orígenes (consolidated_eur) se rechaza a la vista", () => {
  const old = { ...good(), consolidated_eur: { currency: "EUR", revenue: "140.0000" } } as unknown as RevenueSummary;
  assert.throws(() => assertRevenueSummary(old), (error: unknown) => {
    assert.ok(error instanceof RevenueContractError);
    assert.match(error.message, /consolidated_eur/);
    assert.match(error.message, /sumaba todos los orígenes/);
    return true;
  });
});

test("un backend sin consolidated_eur_by_origin falla: no se lee como «Sin datos»", () => {
  const old = good() as unknown as Record<string, unknown>;
  delete old.consolidated_eur_by_origin;
  assert.throws(() => assertRevenueSummary(old as unknown as RevenueSummary), RevenueContractError);
});

test("una fila sin provider_kind se rechaza: el origen ausente no se completa con mock", () => {
  const row = { currency: "EUR", revenue: "20.0000", refunds: "0.0000", net: "20.0000", captures: 1, refund_count: 0 };
  assert.throws(() => assertRevenueSummary(good({ verified: [row as never] })), /verified\[0\] no trae un provider_kind válido/);
});

test("un origen desconocido (composite, mayúsculas, vacío, null) se rechaza en cada bloque", () => {
  for (const bad of ["composite", "REAL", "Mock", "", null, undefined, 3]) {
    const verified = [{ ...good().verified[0], provider_kind: bad as never }];
    assert.throws(() => assertRevenueSummary(good({ verified })), RevenueContractError, `verified con ${String(bad)}`);
    const pending = { count: 1, by_currency: [{ provider_kind: bad as never, currency: "EUR", event_type: "payment.succeeded", count: 1, amount: "1.0000" }] };
    assert.throws(() => assertRevenueSummary(good({ pending_evidence: pending })), RevenueContractError, `pending con ${String(bad)}`);
    const eur = [{ ...good().consolidated_eur_by_origin[0], provider_kind: bad as never }];
    assert.throws(() => assertRevenueSummary(good({ consolidated_eur_by_origin: eur })), RevenueContractError);
  }
});

test("la serie y las entradas también exigen el origen", () => {
  const bucket = { bucket: "2026-10-01", currency: "EUR", revenue: "1.0000", refunds: "0.0000", net: "1.0000", under_review_received: "0.0000", under_review_refunded: "0.0000", entries: 1 };
  const series = (provider_kind?: string) =>
    ({ granularity: "day", period: {}, buckets: [{ ...bucket, provider_kind }], scope: SCOPE }) as unknown as RevenueSeries;
  assert.doesNotThrow(() => assertRevenueSeries(series("sandbox")));
  assert.throws(() => assertRevenueSeries(series(undefined)), RevenueContractError);
  const entry = { id: "e", kind: "CAPTURE", classification: "ORDER_PAYMENT", payment_event_id: "x", payment_id: "p", order_id: "o", refund_id: null, capture_entry_id: null, amount: "1.0000", currency: "EUR", occurred_at: "t", recorded_at: "t" };
  const page = (provider_kind?: string) => ({ items: [{ ...entry, provider_kind }], has_more: false, next_cursor: null }) as unknown as RevenueEntriesPage;
  assert.doesNotThrow(() => assertRevenueEntries(page("real")));
  assert.throws(() => assertRevenueEntries(page("")), RevenueContractError);
});

test("el error de contrato llega a la pantalla como un error visible, no como datos vacíos", async () => {
  const old = { ...good(), consolidated_eur: null } as unknown as RevenueSummary;
  const settled = await settle(async () => assertRevenueSummary(old));
  assert.equal(settled.ok, false);
  if (!settled.ok) assert.match(settled.message, /El contrato de ingresos cambió/);
});
