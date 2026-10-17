import assert from "node:assert/strict";
import { test } from "node:test";
import type { Approval, PipelineReview } from "./api.ts";
import {
  filterReal,
  realInbox,
  realRequestFromApproval,
  realRequestFromReview,
  sortReal,
  type RealInbox,
} from "./approvals-inbox.ts";
import { approval, HOUR, NOW, review } from "./ceo-block-test-support.ts";
import type { ReadState } from "./read-state.ts";

// LA BANDEJA REAL de /approvals (M47, Commit 6b). Solo lo que el backend guarda: sin severidad, sin solicitante ni fecha inventados, sin
// «ahora» ni «caducidad − 24 h» como fecha de solicitud, y SIN mezclar nada de demostración. Un fallo de lectura es un aviso de esa fuente,
// nunca una lista vacía ni un cero.

const loaded = <T>(data: T[]): ReadState<T[]> => (data.length === 0 ? { kind: "empty" } : { kind: "loaded", data });
const failed = (message: string): ReadState<never> => ({ kind: "error", message });
const unread = (reason: string): ReadState<never> => ({ kind: "unread", reason });
const inbox = (approvals: ReadState<Approval[]>, reviews: ReadState<PipelineReview[]> = { kind: "empty" }): RealInbox => realInbox({ approvals, reviews, now: NOW });
const iso = (ms: number) => new Date(ms).toISOString();

test("una aprobación real: su fecha de solicitud es `requested_at`, su vencimiento es `expires_at`, y la correlación se conserva", () => {
  const request = realRequestFromApproval(
    approval("a1", { requested_at: iso(NOW - 3 * HOUR), expires_at: iso(NOW + 21 * HOUR), correlation_id: "c".repeat(36), amount: 150 }),
    NOW,
  );
  assert.equal(request.source, "approval");
  assert.equal(request.requestedAt, NOW - 3 * HOUR);
  assert.equal(request.expiresAt, NOW + 21 * HOUR);
  assert.equal(request.correlationId, "c".repeat(36));
  assert.equal(request.amount, 150);
  assert.equal(request.status, "PENDING");
  assert.equal(request.expired, false);
});

test("SIN `requested_at` la fecha de solicitud es NULL: ni «ahora», ni la caducidad menos 24 h", () => {
  const request = realRequestFromApproval(approval("a1", { expires_at: iso(NOW + 5 * HOUR) }), NOW);
  assert.equal(request.requestedAt, null);
  assert.equal(request.correlationId, null);
  assert.notEqual(request.requestedAt, NOW);
  assert.notEqual(request.requestedAt, NOW + 5 * HOUR - 24 * HOUR);
});

test("sin `expires_at` no hay vencimiento (null), y no se inventa uno por SLA", () => {
  const request = realRequestFromApproval(approval("a1", { expires_at: null }), NOW);
  assert.equal(request.expiresAt, null);
  assert.equal(request.expired, false);
});

test("una aprobación PENDING con la caducidad pasada está `expired` (el backend ya no la deja resolver) pero su estado sigue siendo el del backend", () => {
  const request = realRequestFromApproval(approval("a1", { expires_at: iso(NOW - HOUR) }), NOW);
  assert.equal(request.status, "PENDING");
  assert.equal(request.expired, true);
});

test("una revisión de pipeline real no trae fecha ni caducidad: ambas NULL (no «ahora», no un SLA inventado)", () => {
  const request = realRequestFromReview(review("g1"));
  assert.equal(request.source, "review");
  assert.equal(request.requestedAt, null);
  assert.equal(request.expiresAt, null);
  assert.equal(request.amount, null);
  assert.equal(request.expired, false);
});

test("ninguna solicitud real lleva severidad, `isDemo` ni textos inventados de solicitante con nombre de persona", () => {
  const requests = [realRequestFromApproval(approval("a1"), NOW), realRequestFromReview(review("g1"))];
  for (const request of requests) {
    assert.equal("severity" in request, false);
    assert.equal("isDemo" in request, false);
    assert.doesNotMatch(JSON.stringify(request), /Crítica|Alta|demo|demostraci/i);
  }
});

// --- La bandeja y sus fuentes ------------------------------------------------------------------------------------------------

test("las dos fuentes cargadas: aprobaciones y revisiones, y los recuentos reales", () => {
  const view = inbox(
    loaded([approval("a1", { expires_at: iso(NOW + 2 * HOUR) }), approval("a2", { expires_at: iso(NOW + 30 * HOUR) }), approval("old", { expires_at: iso(NOW - HOUR) }), approval("done", { status: "APPROVED" })]),
    loaded([review("g1"), review("g2", { status: "APPROVED" })]),
  );
  assert.equal(view.state, "loaded");
  assert.deepEqual(view.requests.map((r) => r.id).sort(), ["a1", "a2", "done", "g1", "g2", "old"]);
  assert.deepEqual(view.kpis, { pending: 3, expired: 1, expiringSoon: 1 });
  assert.deepEqual(view.sources, { approvals: null, reviews: null });
});

test("sin nada: vacío (un hecho), y los recuentos son 0 REALES", () => {
  const view = inbox({ kind: "empty" }, { kind: "empty" });
  assert.equal(view.state, "empty");
  assert.deepEqual(view.kpis, { pending: 0, expired: 0, expiringSoon: 0 });
  assert.deepEqual(view.requests, []);
});

test("las aprobaciones fallan y las revisiones no: las revisiones se ven, las aprobaciones dicen su error y NINGÚN recuento se enseña como cifra", () => {
  const view = inbox(failed("No se pudieron cargar las aprobaciones."), loaded([review("g1")]));
  assert.equal(view.state, "partial");
  assert.deepEqual(view.requests.map((r) => r.id), ["g1"]);
  assert.deepEqual(view.sources.approvals, { kind: "error", text: "No se pudieron cargar las aprobaciones." });
  assert.equal(view.sources.reviews, null);
  assert.deepEqual(view.kpis, { pending: null, expired: null, expiringSoon: null });
});

test("las revisiones fallan y las aprobaciones no: lo mismo a la inversa", () => {
  const view = inbox(loaded([approval("a1")]), failed("No se pudieron cargar las revisiones de pipeline."));
  assert.equal(view.state, "partial");
  assert.deepEqual(view.requests.map((r) => r.id), ["a1"]);
  assert.equal(view.sources.reviews?.kind, "error");
  assert.deepEqual(view.kpis, { pending: null, expired: null, expiringSoon: null });
});

test("las dos fallan: error, NO vacío; sin filas y sin cifras", () => {
  const view = inbox(failed("a"), failed("b"));
  assert.equal(view.state, "error");
  assert.notEqual(view.state, "empty");
  assert.deepEqual(view.requests, []);
  assert.deepEqual(view.kpis, { pending: null, expired: null, expiringSoon: null });
});

test("una fuente vacía y la otra con error: parcial, no «vacío»", () => {
  const view = inbox({ kind: "empty" }, failed("x"));
  assert.equal(view.state, "partial");
  assert.notEqual(view.state, "empty");
});

test("sin leer ≠ vacío: una fuente sin leer se dice «sin leer» y no suma cero", () => {
  const view = inbox(unread("pendiente"), { kind: "empty" });
  assert.equal(view.state, "partial");
  assert.deepEqual(view.sources.approvals, { kind: "unread", text: "pendiente" });
  assert.equal(view.kpis.pending, null);
  const both = inbox(unread("a"), unread("b"));
  assert.equal(both.state, "unread");
  assert.notEqual(both.state, "empty");
});

test("un error nunca se convierte en lista vacía: con un error, `requests` no contiene filas inventadas ni de demostración", () => {
  const view = inbox(failed("x"), failed("y"));
  assert.equal(view.requests.length, 0);
  assert.doesNotMatch(JSON.stringify(view), /demo|Demo|demostraci/);
});

// --- Filtro y orden ----------------------------------------------------------------------------------------------------------

test("filtro: «Pendientes» = PENDING y no vencida; «Todas» = todas", () => {
  const view = inbox(loaded([approval("a1"), approval("old", { expires_at: iso(NOW - HOUR) }), approval("done", { status: "REJECTED" })]), loaded([review("g1")]));
  assert.deepEqual(filterReal(view.requests, "pending").map((r) => r.id).sort(), ["a1", "g1"]);
  assert.equal(filterReal(view.requests, "all").length, 4);
});

test("orden por vencimiento: el que antes vence primero; sin vencimiento al final; el id desempata", () => {
  const view = inbox(loaded([approval("late", { expires_at: iso(NOW + 9 * HOUR) }), approval("soon", { expires_at: iso(NOW + HOUR) }), approval("none", { expires_at: null })]), loaded([review("g1")]));
  assert.deepEqual(sortReal(view.requests, "expiry").map((r) => r.id), ["soon", "late", "g1", "none"]);
});

test("orden por solicitud más reciente: sin fecha de solicitud al final, nunca arriba; el id desempata", () => {
  const view = inbox(
    loaded([
      approval("old", { requested_at: iso(NOW - 9 * HOUR) }),
      approval("new", { requested_at: iso(NOW - HOUR) }),
      approval("nodate"),
      approval("same", { requested_at: iso(NOW - HOUR) }),
    ]),
    loaded([review("g1")]),
  );
  assert.deepEqual(sortReal(view.requests, "recent").map((r) => r.id), ["new", "same", "old", "g1", "nodate"]);
});

test("el orden no depende del orden en que llegan las filas", () => {
  const rows = [approval("b", { expires_at: iso(NOW + 3 * HOUR) }), approval("a", { expires_at: iso(NOW + 3 * HOUR) }), approval("c", { expires_at: iso(NOW + HOUR) })];
  const one = sortReal(inbox(loaded(rows)).requests, "expiry").map((r) => r.id);
  const two = sortReal(inbox(loaded([...rows].reverse())).requests, "expiry").map((r) => r.id);
  assert.deepEqual(one, two);
  assert.deepEqual(one, ["c", "a", "b"]);
});

test("una aprobación sin importe tiene importe NULL (no 0): el backend no lo guarda", () => {
  const request = realRequestFromApproval(approval("a1", { amount: null }), NOW);
  assert.equal(request.amount, null);
  assert.match(request.fields.find((field) => field.label === "Importe")?.value ?? "", /Sin importe/);
});
