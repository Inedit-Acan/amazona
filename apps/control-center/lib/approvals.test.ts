import { test } from "node:test";
import assert from "node:assert/strict";
import {
  actionLabel,
  decisionImpact,
  entryStatus,
  expiryLabel,
  inboxStats,
  isActionable,
  isEntryPending,
  isExpired,
  sortInbox,
  type InboxEntry,
} from "./approvals.ts";
import { parseUtc, relativeTime } from "./dates.ts";

const now = new Date("2026-01-01T12:00:00Z");

test("a pending approval with a future expiry is not expired", () => {
  assert.equal(
    isExpired({ status: "PENDING", expires_at: "2026-01-02T00:00:00Z" }, now),
    false,
  );
});

test("a pending approval past its expiry is expired", () => {
  assert.equal(
    isExpired({ status: "PENDING", expires_at: "2025-12-31T00:00:00Z" }, now),
    true,
  );
});

test("a pending approval with no expiry never expires", () => {
  assert.equal(isExpired({ status: "PENDING", expires_at: null }, now), false);
});

test("a resolved approval is never reported as expired, even past its expiry date", () => {
  assert.equal(
    isExpired({ status: "APPROVED", expires_at: "2025-12-31T00:00:00Z" }, now),
    false,
  );
});

test("an expired pending approval is not actionable", () => {
  assert.equal(
    isActionable({ status: "PENDING", expires_at: "2025-12-31T00:00:00Z" }, now),
    false,
  );
});

test("a non-expired pending approval is actionable", () => {
  assert.equal(
    isActionable({ status: "PENDING", expires_at: "2026-01-02T00:00:00Z" }, now),
    true,
  );
});

test("an already-approved approval is not actionable again", () => {
  assert.equal(isActionable({ status: "APPROVED", expires_at: null }, now), false);
});

test("a rejected approval is not actionable again", () => {
  assert.equal(isActionable({ status: "REJECTED", expires_at: null }, now), false);
});

// --- Bandeja unificada ---
const approvalEntry = (id: string, over: Partial<{ status: "PENDING" | "APPROVED" | "REJECTED" | "EXPIRED" | "CANCELLED"; expires_at: string | null; resolved_at: string | null; amount: number | null }> = {}): InboxEntry => ({
  kind: "approval",
  id,
  approval: { id, decision_id: "d", action: "launch_marketing_campaign", amount: over.amount ?? 150, status: over.status ?? "PENDING", expires_at: over.expires_at ?? null, resolved_at: over.resolved_at ?? null, resolved_by: null },
  decision: null,
  project: null,
});
const reviewEntry = (id: string, status: "PENDING" | "APPROVED" | "REJECTED", resolved_at: string | null = null): InboxEntry => ({
  kind: "pipeline_review",
  id,
  review: { id, pipeline_run_id: "r", reasons: ["x"], status, resolved_at, resolved_by: null, correlation_id: "c" },
});
const NOW = new Date("2026-09-22T12:00:00Z");

test("parseUtc trata las fechas sin zona como UTC y respeta las que la traen", () => {
  assert.equal(parseUtc("2026-09-22T12:00:00"), Date.parse("2026-09-22T12:00:00Z"));
  assert.equal(parseUtc("2026-09-22T12:00:00Z"), Date.parse("2026-09-22T12:00:00Z"));
  assert.equal(parseUtc("2026-09-22T14:00:00+02:00"), Date.parse("2026-09-22T12:00:00Z"));
});

test("isExpired usa UTC también con fechas sin zona (SQLite)", () => {
  assert.equal(isExpired({ status: "PENDING", expires_at: "2026-09-22T11:59:00" }, NOW), true);
  assert.equal(isExpired({ status: "PENDING", expires_at: "2026-09-22T12:01:00" }, NOW), false);
});

test("relativeTime y expiryLabel describen la distancia en min, h o días", () => {
  assert.equal(relativeTime(NOW.getTime() + 25 * 60_000, NOW.getTime()), "en 25 min");
  assert.equal(relativeTime(NOW.getTime() - 3 * 3_600_000, NOW.getTime()), "hace 3 h");
  assert.equal(relativeTime(NOW.getTime() + 5 * 86_400_000, NOW.getTime()), "en 5 días");
  assert.equal(expiryLabel("2026-09-22T15:00:00", NOW), "Vence en 3 h");
  assert.equal(expiryLabel("2026-09-22T10:00:00", NOW), "Vencida hace 2 h");
  assert.equal(expiryLabel(null, NOW), "Sin vencimiento");
});

test("entryStatus y isEntryPending: una aprobación vencida figura como expirada y no se puede accionar", () => {
  const expired = approvalEntry("a", { expires_at: "2026-09-22T10:00:00" });
  assert.equal(entryStatus(expired, NOW), "EXPIRED");
  assert.equal(isEntryPending(expired, NOW), false);
  assert.equal(isEntryPending(approvalEntry("b", { expires_at: "2026-09-23T10:00:00" }), NOW), true);
  assert.equal(isEntryPending(reviewEntry("r", "PENDING"), NOW), true);
  assert.equal(entryStatus(reviewEntry("r", "REJECTED"), NOW), "REJECTED");
});

test("sortInbox: pendientes primero (las que vencen antes arriba) y luego las decididas más recientes", () => {
  const sorted = sortInbox(
    [
      approvalEntry("old", { status: "APPROVED", resolved_at: "2026-09-20T10:00:00" }),
      approvalEntry("late", { expires_at: "2026-09-24T10:00:00" }),
      reviewEntry("rev", "PENDING"),
      approvalEntry("soon", { expires_at: "2026-09-22T18:00:00" }),
      reviewEntry("new", "APPROVED", "2026-09-22T09:00:00"),
    ],
    NOW,
  );
  assert.deepEqual(
    sorted.map((e) => e.id),
    ["soon", "late", "rev", "new", "old"],
  );
});

test("inboxStats cuenta pendientes, las que vencen en 24 h, aprobadas hoy y decididas", () => {
  const stats = inboxStats(
    [
      approvalEntry("soon", { expires_at: "2026-09-22T20:00:00" }),
      approvalEntry("later", { expires_at: "2026-09-25T20:00:00" }),
      approvalEntry("expired", { expires_at: "2026-09-22T08:00:00" }),
      approvalEntry("today", { status: "APPROVED", resolved_at: "2026-09-22T11:00:00" }),
      approvalEntry("yesterday", { status: "APPROVED", resolved_at: "2026-09-20T11:00:00" }),
      approvalEntry("rejected", { status: "REJECTED", resolved_at: "2026-09-22T11:00:00" }),
      reviewEntry("rev", "PENDING"),
    ],
    NOW,
  );
  assert.deepEqual(stats, { pending: 3, expiringSoon: 1, approvedToday: 1, decided: 4, total: 7 });
});

test("actionLabel y decisionImpact describen lo que hace el backend al aprobar o rechazar", () => {
  assert.equal(actionLabel("launch_marketing_campaign"), "Lanzamiento de campaña de marketing");
  assert.equal(actionLabel("pago_extraordinario"), "Pago extraordinario");
  const withAmount = decisionImpact({ action: "launch_marketing_campaign", amount: 150 });
  assert.match(withAmount.approve[0], /por 150,00/);
  assert.ok(withAmount.approve.some((line) => /reservado a comprometido/.test(line)));
  assert.ok(withAmount.reject.some((line) => /libera la reserva de 150,00/.test(line)));
  const noAmount = decisionImpact({ action: "x", amount: null });
  assert.ok(noAmount.approve.every((line) => !/comprometido/.test(line)));
  assert.ok(noAmount.reject.every((line) => !/reserva/.test(line)));
});
