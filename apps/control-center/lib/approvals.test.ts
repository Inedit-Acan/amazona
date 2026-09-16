import { test } from "node:test";
import assert from "node:assert/strict";
import { isActionable, isExpired } from "./approvals.ts";

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
