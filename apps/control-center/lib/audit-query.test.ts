import assert from "node:assert/strict";
import { test } from "node:test";
import { AUDIT_MAX_LIMIT, auditPath } from "./audit-query.ts";

// La petición de `GET /api/audit` (M47, micro-commit 5B): opciones tipadas, parámetros codificados con `URLSearchParams` (nunca
// concatenados a mano) y en un orden fijo. Sin opciones, la petición es la de siempre.

test("sin opciones: la petición de siempre, sin parámetros", () => {
  assert.equal(auditPath(), "/api/audit");
  assert.equal(auditPath({}), "/api/audit");
  assert.equal(auditPath({ correlationId: "" }), "/api/audit");
  assert.equal(auditPath({ correlationId: undefined, order: undefined, limit: undefined }), "/api/audit");
});

test("`correlationId` como texto (la firma antigua) sigue dando `?correlation_id=`", () => {
  assert.equal(auditPath("abc-123"), "/api/audit?correlation_id=abc-123");
  assert.equal(auditPath(""), "/api/audit");
  assert.equal(auditPath({ correlationId: "abc-123" }), "/api/audit?correlation_id=abc-123");
});

test("la petición de «Actividad registrada»: exactamente `order=desc&limit=5`", () => {
  assert.equal(auditPath({ order: "desc", limit: 5 }), "/api/audit?order=desc&limit=5");
});

test("los parámetros salen siempre en el mismo orden, se pasen como se pasen", () => {
  const a = auditPath({ before: "2026-10-01T12:00:00Z,r1", since: "2026-09-01T00:00:00Z", limit: 3, order: "asc", correlationId: "c" });
  const b = auditPath({ correlationId: "c", order: "asc", limit: 3, since: "2026-09-01T00:00:00Z", before: "2026-10-01T12:00:00Z,r1" });
  assert.equal(a, b);
  assert.match(a, /^\/api\/audit\?correlation_id=c&order=asc&limit=3&since=.*&before=/);
});

test("el `+` de un desplazamiento horario va codificado: llegaría como un espacio y sería un instante inválido", () => {
  const path = auditPath({ since: "2026-10-01T14:00:06+02:00" });
  assert.equal(path, "/api/audit?since=2026-10-01T14%3A00%3A06%2B02%3A00");
  assert.doesNotMatch(path, /\+/);
  assert.equal(new URL(`http://x${path}`).searchParams.get("since"), "2026-10-01T14:00:06+02:00");
});

test("el cursor `before` (instante, coma, id) se codifica y se recupera tal cual", () => {
  const cursor = "2026-10-01T14:00:03.123456+02:00,0f8e2c1a-7b3d-4c5e-9a10-2b4d6f8a0c1e";
  const path = auditPath({ order: "desc", limit: 5, before: cursor });
  assert.doesNotMatch(path, /\+|,/);
  assert.equal(new URL(`http://x${path}`).searchParams.get("before"), cursor);
});

test("un valor con caracteres especiales no rompe la petición ni añade parámetros", () => {
  const path = auditPath({ correlationId: "a&order=asc#x y" });
  assert.equal(new URL(`http://x${path}`).searchParams.get("correlation_id"), "a&order=asc#x y");
  assert.equal(new URL(`http://x${path}`).searchParams.get("order"), null);
});

test("`limit` fuera de 1..500 o no entero, y un `order` desconocido, se rechazan antes de pedir (no se envía una petición inválida)", () => {
  assert.equal(AUDIT_MAX_LIMIT, 500);
  assert.equal(auditPath({ limit: 1 }), "/api/audit?limit=1");
  assert.equal(auditPath({ limit: 500 }), "/api/audit?limit=500");
  for (const limit of [0, -1, 501, 1.5, Number.NaN, Number.POSITIVE_INFINITY]) assert.throws(() => auditPath({ limit }), RangeError, String(limit));
  for (const order of ["up", "DESC", "", "newest"]) assert.throws(() => auditPath({ order: order as never }), RangeError, order);
});

test("el estado de `since` y `before` vacíos no se descarta en silencio: llega al backend, que responde 422", () => {
  assert.equal(auditPath({ since: "" }), "/api/audit?since=");
  assert.equal(auditPath({ before: "" }), "/api/audit?before=");
});
