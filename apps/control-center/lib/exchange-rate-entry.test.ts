import assert from "node:assert/strict";
import { test } from "node:test";
import {
  EMPTY_RATE,
  numericRate,
  pairSentence,
  problems,
  ratePayload,
} from "./exchange-rate-entry.ts";

const TODAY = "2026-09-29";

const filled = {
  ...EMPTY_RATE,
  rate: "0,92",
  effectiveDate: "2026-09-25",
};

test("el par se lee en palabras, sin que nadie deduzca la dirección", () => {
  // Un 1,08 puede ser dólares por euro o al revés, y entre las dos lecturas hay
  // un 16 % que no se ve hasta que llega a un margen.
  assert.equal(pairSentence(filled), "1 USD = 0,92 EUR");
});

test("numericRate acepta la coma decimal", () => {
  assert.equal(numericRate("0,92"), 0.92);
  assert.equal(numericRate("0.92"), 0.92);
  assert.equal(numericRate("  "), null);
  assert.equal(numericRate("casi un euro"), null);
});

test("una tasa completa no tiene problemas", () => {
  assert.deepEqual(problems(filled, TODAY), []);
});

test("faltan la tasa y la fecha en un formulario vacío", () => {
  const fields = problems(EMPTY_RATE, TODAY).map((p) => p.field);

  assert.ok(fields.includes("rate"));
  assert.ok(fields.includes("effectiveDate"));
});

test("una tasa negativa o cero se rechaza", () => {
  assert.ok(problems({ ...filled, rate: "0" }, TODAY).some((p) => p.field === "rate"));
  assert.ok(problems({ ...filled, rate: "-1" }, TODAY).some((p) => p.field === "rate"));
});

test("una tasa del futuro se rechaza", () => {
  const found = problems({ ...filled, effectiveDate: "2026-10-05" }, TODAY);

  assert.ok(found.some((p) => p.field === "effectiveDate"));
});

test("un cambio entre una moneda y ella misma no es un cambio", () => {
  const found = problems({ ...filled, quoteCurrency: "usd" }, TODAY);

  assert.ok(found.some((p) => p.field === "quoteCurrency"));
});

test("«verificado por un tercero» exige emisor", () => {
  const form = { ...filled, provenance: "third_party_verified" as const };

  assert.ok(problems(form, TODAY).some((p) => p.field === "declaredBy"));
  assert.deepEqual(problems({ ...form, declaredBy: "Banco" }, TODAY), []);
});

test("el payload normaliza monedas y coma decimal", () => {
  const payload = ratePayload({ ...filled, baseCurrency: " usd ", quoteCurrency: "eur" });

  assert.equal(payload.base_currency, "USD");
  assert.equal(payload.quote_currency, "EUR");
  assert.equal(payload.rate, "0.92");
  assert.equal(payload.declared_by, null);
});
