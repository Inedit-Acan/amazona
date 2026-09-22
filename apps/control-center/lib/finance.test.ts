import assert from "node:assert/strict";
import { test } from "node:test";
import { FINANCIAL_VERDICT } from "./finance.ts";

test("FINANCIAL_VERDICT traduce los cuatro estados del agente con su tono", () => {
  assert.deepEqual(
    Object.entries(FINANCIAL_VERDICT).map(([status, verdict]) => [status, verdict.tone]),
    [
      ["HEALTHY", "ok"],
      ["AT_RISK", "warn"],
      ["CRITICAL", "bad"],
      ["NEEDS_REVIEW", "warn"],
    ],
  );
  assert.equal(FINANCIAL_VERDICT.HEALTHY.title, "Saludable");
  assert.ok(FINANCIAL_VERDICT.CRITICAL.detail.length > 10);
});
