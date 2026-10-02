import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { KEYED_OPERATIONS, OPERATIONS } from "./intent-operations.ts";

const CLASSIFICATION = new URL("../../../backend/tests/unit/test_post_route_classification.py", import.meta.url);

/** Las rutas que el backend clasifica como protegidas por clave de cliente (`GENERIC` y `EXTERNAL_WRITE`). */
async function backendKeyedRoutes(): Promise<Map<string, string>> {
  const source = await readFile(CLASSIFICATION, "utf8");
  const routes = new Map<string, string>();
  for (const match of source.matchAll(/^\s*"(\/api\/[^"]+)":\s*(GENERIC|EXTERNAL_WRITE),/gm)) {
    routes.set(match[1], match[2]);
  }
  return routes;
}

test("el cliente conoce exactamente las rutas con clave que declara el backend", async () => {
  const backend = await backendKeyedRoutes();

  assert.ok(backend.size >= 13, "the classification of the backend could not be read: the guard would pass for nothing");
  assert.deepEqual([...KEYED_OPERATIONS.map((o) => o.path)].sort(), [...backend.keys()].sort());
});

test("cada operación coincide con la clase de su ruta (externa o genérica)", async () => {
  const backend = await backendKeyedRoutes();

  for (const operation of KEYED_OPERATIONS) {
    const expected = backend.get(operation.path) === "EXTERNAL_WRITE" ? "external" : "generic";
    assert.equal(operation.kind, expected, operation.path);
  }
});

test("los nombres de operación son únicos, opacos y están todos en el catálogo", () => {
  const names = KEYED_OPERATIONS.map((o) => o.operation);

  assert.equal(new Set(names).size, names.length);
  assert.deepEqual([...names].sort(), Object.values(OPERATIONS).sort());
  for (const name of names) assert.match(name, /^[a-z][a-z0-9.-]*$/);
});

test("toda operación de M44 con efecto está en el catálogo (pedido, cobro, reembolso, fulfillment, compra, envío)", () => {
  const paths = new Set(KEYED_OPERATIONS.map((o) => o.path));

  for (const path of [
    "/api/orders",
    "/api/orders/{order_id}/payments",
    "/api/orders/{order_id}/refunds",
    "/api/orders/{order_id}/fulfillments",
    "/api/fulfillments/{fulfillment_id}/purchase",
    "/api/fulfillments/{fulfillment_id}/ship",
  ]) {
    assert.ok(paths.has(path), path);
  }
});

test("el cliente lanza hoy desde la interfaz las operaciones que el catálogo dice, y las usa con una clave de intención", async () => {
  const sources = await Promise.all(
    [
      "../app/ceo/page.tsx",
      "../app/legal/legal-workspace.tsx",
      "../app/research/research-workspace.tsx",
      "../components/regulatory-panel.tsx",
      "../components/national-transpositions.tsx",
    ].map((file) => readFile(new URL(file, import.meta.url), "utf8")),
  );
  const joined = sources.join("\n");

  for (const operation of KEYED_OPERATIONS.filter((o) => o.inInterface)) {
    const name = Object.entries(OPERATIONS).find(([, value]) => value === operation.operation)![0];
    assert.match(joined, new RegExp(`OPERATIONS\\.${name}\\b`), `${operation.path} is launched without an intent key`);
  }
});
