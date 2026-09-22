import assert from "node:assert/strict";
import { test } from "node:test";
import { formatDuration, formatEuro } from "./format.ts";

test("formatDuration: sub-milisegundo, milisegundos y segundos", () => {
  assert.equal(formatDuration(0.013), "<1 ms");
  assert.equal(formatDuration(0), "<1 ms");
  assert.equal(formatDuration(42.4), "42 ms");
  assert.equal(formatDuration(1234), "1,2 s");
});

test("formatEuro: separador de miles, decimales y símbolo al final", () => {
  assert.equal(formatEuro(29.9), "29,90 €");
  assert.equal(formatEuro(2180, 0), "2.180 €");
  assert.equal(formatEuro(-0.36), "-0,36 €");
});
