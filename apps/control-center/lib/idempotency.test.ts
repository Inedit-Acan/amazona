import assert from "node:assert/strict";
import { test } from "node:test";
import { IDEMPOTENCY_HEADER, newIdempotencyKey, withIdempotencyKey } from "./idempotency.ts";

test("un POST lleva una clave de idempotencia", () => {
  assert.deepEqual(withIdempotencyKey({ method: "POST" }, () => "k-1"), { "Idempotency-Key": "k-1" });
});

test("un POST en minúsculas también", () => {
  assert.deepEqual(withIdempotencyKey({ method: "post" }, () => "k-1"), { "Idempotency-Key": "k-1" });
});

test("una lectura no lleva clave", () => {
  assert.deepEqual(withIdempotencyKey(undefined, () => "k-1"), {});
  assert.deepEqual(withIdempotencyKey({ method: "GET" }, () => "k-1"), {});
});

test("la clave que pone quien llama no se pisa, sea cual sea la forma de sus cabeceras", () => {
  const mine = "mine";
  assert.deepEqual(withIdempotencyKey({ method: "POST", headers: { [IDEMPOTENCY_HEADER]: mine } }, () => "k"), {});
  assert.deepEqual(withIdempotencyKey({ method: "POST", headers: { "idempotency-key": mine } }, () => "k"), {});
  assert.deepEqual(
    withIdempotencyKey({ method: "POST", headers: new Headers({ [IDEMPOTENCY_HEADER]: mine }) }, () => "k"),
    {},
  );
  assert.deepEqual(withIdempotencyKey({ method: "POST", headers: [[IDEMPOTENCY_HEADER, mine]] }, () => "k"), {});
});

test("otras cabeceras no cuentan como clave", () => {
  assert.deepEqual(withIdempotencyKey({ method: "POST", headers: { "Content-Type": "application/json" } }, () => "k"), {
    "Idempotency-Key": "k",
  });
});

test("cada clave generada es distinta y cumple lo que el backend acepta", () => {
  const keys = new Set(Array.from({ length: 50 }, () => newIdempotencyKey()));
  assert.equal(keys.size, 50);
  for (const key of keys) assert.match(key, /^[A-Za-z0-9._:-]{1,128}$/);
});
