import assert from "node:assert/strict";
import { test } from "node:test";
import { fxNotices, fxSourceLabel, fxSourceNotice, ingestedOn, isEcbSource, splitRates } from "./fx-source.ts";

test("una fuente con prefijo ecb: se reconoce y se rotula como referencia BCE", () => {
  assert.equal(isEcbSource("ecb:eurofxref"), true);
  assert.equal(fxSourceLabel("ecb:eurofxref"), "referencia BCE");
});

test("la referencia del BCE lleva la atribución de su licencia y la advertencia de que no es transaccional", () => {
  const notice = fxSourceNotice("ecb:eurofxref");
  assert.ok(notice);
  assert.match(notice.attribution, /Banco Central Europeo/);
  assert.match(notice.warning, /no es la tasa transaccional/);
});

test("una tasa declarada o de fixture no lleva aviso y conserva su fuente", () => {
  for (const source of ["manual:owner", "fixtures:mock-exchange-rates", "becb:x"]) {
    assert.equal(fxSourceNotice(source), null);
    assert.equal(fxSourceLabel(source), source);
  }
});

test("los avisos no se repiten aunque haya varias conversiones del BCE", () => {
  const notices = fxNotices(["ecb:eurofxref", "ecb:eurofxref", "manual:owner"]);
  assert.equal(notices.length, 1);
  assert.deepEqual(fxNotices(["manual:owner"]), []);
});

test("la fecha de ingestión se recorta a día y no se inventa si falta", () => {
  assert.equal(ingestedOn("2026-09-29T14:05:00+00:00"), "2026-09-29");
  assert.equal(ingestedOn(null), null);
  assert.equal(ingestedOn(undefined), null);
});

test("las referencias del BCE no tapan las tasas declaradas a mano", () => {
  const rates = [
    { source: "ecb:eurofxref", effective_date: "2026-09-29", ingested_at: "2026-09-29T14:05:00+00:00" },
    { source: "ecb:eurofxref", effective_date: "2026-09-28", ingested_at: "2026-09-28T14:05:00+00:00" },
    { source: "manual:owner", effective_date: "2026-09-01" },
  ];
  const { declared, ecb } = splitRates(rates);
  assert.deepEqual(declared.map((rate) => rate.source), ["manual:owner"]);
  assert.ok(ecb);
  assert.equal(ecb.count, 2);
  assert.equal(ecb.latestEffectiveDate, "2026-09-29");
  assert.equal(ecb.latestIngestedAt, "2026-09-29T14:05:00+00:00");
  assert.match(ecb.notice.warning, /no es la tasa transaccional/);
});

test("sin referencias del BCE no hay resumen y todo es declarado", () => {
  const { declared, ecb } = splitRates([{ source: "manual:owner", effective_date: "2026-09-01" }]);
  assert.equal(declared.length, 1);
  assert.equal(ecb, null);
});

test("la fecha efectiva más reciente del BCE es la de la fuente, no la de ingestión", () => {
  const { ecb } = splitRates([
    { source: "ecb:eurofxref", effective_date: "2026-09-25", ingested_at: "2026-09-29T10:00:00+00:00" },
  ]);
  assert.equal(ecb?.latestEffectiveDate, "2026-09-25");
});
