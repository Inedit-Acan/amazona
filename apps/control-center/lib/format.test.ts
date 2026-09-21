import assert from "node:assert/strict";
import { test } from "node:test";
import { formatDuration } from "./format.ts";

test("formatDuration: sub-milisegundo, milisegundos y segundos", () => {
  assert.equal(formatDuration(0.013), "<1 ms");
  assert.equal(formatDuration(0), "<1 ms");
  assert.equal(formatDuration(42.4), "42 ms");
  assert.equal(formatDuration(1234), "1,2 s");
});
