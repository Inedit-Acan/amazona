import assert from "node:assert/strict";
import { test } from "node:test";
import type { Approval } from "./api.ts";
import { actionLabel, decisionImpact, isActionable, isExpired } from "./approvals.ts";

const NOW = new Date("2026-09-22T12:00:00Z");

const approval = (overrides: Partial<Approval> = {}): Approval => ({
  id: "apr-1",
  decision_id: "dec-1",
  action: "launch_marketing_campaign",
  amount: 1500,
  status: "PENDING",
  expires_at: new Date(NOW.getTime() + 3_600_000).toISOString(),
  resolved_at: null,
  resolved_by: null,
  ...overrides,
});

test("isExpired: solo una pendiente con vencimiento pasado está vencida", () => {
  assert.equal(isExpired(approval(), NOW), false);
  assert.equal(isExpired(approval({ expires_at: new Date(NOW.getTime() - 1).toISOString() }), NOW), true);
  assert.equal(isExpired(approval({ expires_at: null }), NOW), false);
  assert.equal(isExpired(approval({ status: "APPROVED", expires_at: new Date(NOW.getTime() - 1).toISOString() }), NOW), false);
});

test("isActionable: pendiente y sin vencer", () => {
  assert.equal(isActionable(approval(), NOW), true);
  assert.equal(isActionable(approval({ status: "REJECTED" }), NOW), false);
  assert.equal(isActionable(approval({ expires_at: new Date(NOW.getTime() - 1).toISOString() }), NOW), false);
});

test("actionLabel traduce lo conocido y limpia lo demás", () => {
  assert.equal(actionLabel("launch_marketing_campaign"), "Lanzamiento de campaña de marketing");
  assert.equal(actionLabel("purchase_stock"), "Purchase stock");
});

test("decisionImpact: qué pasa al aprobar y al rechazar, con y sin importe", () => {
  const withAmount = decisionImpact({ action: "launch_marketing_campaign", amount: 1500 });
  assert.equal(withAmount.approve.length, 3);
  assert.ok(withAmount.approve[0].includes("1.500"));
  assert.ok(withAmount.reject.some((line) => line.includes("libera la reserva")));

  const withoutAmount = decisionImpact({ action: "purchase_stock", amount: null });
  assert.equal(withoutAmount.approve.length, 2);
  assert.equal(withoutAmount.reject.length, 2);
});
