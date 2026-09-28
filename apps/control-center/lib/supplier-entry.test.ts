import assert from "node:assert/strict";
import { test } from "node:test";
import {
  EMPTY_ENTRY,
  capabilityPayloads,
  numeric,
  problems,
  quotePayload,
  supplierPayload,
  text,
} from "./supplier-entry.ts";

const filled = {
  ...EMPTY_ENTRY,
  name: "  Fábrica Real S.L. ",
  country: "ES",
  unitPrice: "6,40",
  currency: "EUR",
  moq: "25",
  incoterm: "DDP",
};

test("un campo vacío se envía como ausente, nunca como cero", () => {
  // Mandar `0` en el MOQ que nadie rellenó le diría al backend que el proveedor
  // sirve pedidos de cero unidades.
  const payload = quotePayload(EMPTY_ENTRY, "p1");

  assert.equal(payload.unit_price, null);
  assert.equal(payload.moq, null);
  assert.equal(payload.lead_time_days, null);
  assert.equal(payload.logistics_cost_per_unit, null);
  assert.equal(payload.incoterm, null);
});

test("numeric acepta la coma decimal y rechaza lo que no es un número", () => {
  assert.equal(numeric("6,40"), 6.4);
  assert.equal(numeric("6.40"), 6.4);
  assert.equal(numeric("  "), null);
  assert.equal(numeric("cuatro"), null);
  assert.equal(numeric("0"), 0);
});

test("text no confunde el blanco con lo no declarado", () => {
  assert.equal(text("   "), null);
  assert.equal(text(" Acme "), "Acme");
});

test("el nombre es obligatorio", () => {
  assert.deepEqual(
    problems(EMPTY_ENTRY).map((p) => p.field),
    ["name"],
  );
});

test("«verificado por un tercero» exige decir quién verificó", () => {
  const form = { ...filled, verification: "third_party_verified" as const };

  assert.ok(problems(form).some((p) => p.field === "verifiedBy"));
  assert.deepEqual(problems({ ...form, verifiedBy: "Bureau Veritas" }), []);
});

test("un precio sin moneda no se deja enviar", () => {
  const form = { ...filled, currency: "  " };

  assert.ok(problems(form).some((p) => p.field === "currency"));
});

test("sin precio no se manda moneda: no hay nada que denominar", () => {
  const payload = quotePayload({ ...filled, unitPrice: "" }, "p1");

  assert.equal(payload.unit_price, null);
  assert.equal(payload.currency, null);
});

test("supplierPayload limpia los espacios y respeta lo no declarado", () => {
  const payload = supplierPayload(filled);

  assert.equal(payload.name, "Fábrica Real S.L.");
  assert.equal(payload.country, "ES");
  assert.equal(payload.city, null);
  assert.equal(payload.verification, "supplier_claim");
  assert.equal(payload.verified_by, null);
});

test("una capacidad sin tocar no se envía", () => {
  // Un formulario de casillas manda «no» por omisión, y eso es lo que el
  // Milestone 39 quita de en medio.
  assert.deepEqual(capabilityPayloads(EMPTY_ENTRY), []);
});

test("solo se envían las capacidades que alguien ha contestado", () => {
  const form = {
    ...filled,
    capabilities: { dropshipping: true, blind_shipping: false } as const,
  };

  assert.deepEqual(capabilityPayloads(form), [
    { capability: "dropshipping", supported: true, provenance: "supplier_claim" },
    { capability: "blind_shipping", supported: false, provenance: "supplier_claim" },
  ]);
});

test("una fecha de vigencia se manda como instante UTC, y su ausencia como nula", () => {
  assert.equal(quotePayload({ ...filled, validUntil: "2026-12-31" }, "p1").valid_until, "2026-12-31T00:00:00Z");
  assert.equal(quotePayload(filled, "p1").valid_until, null);
});
