import type { Approval } from "@/lib/api";

/** An approval that is still PENDING but whose expiry has passed cannot be
 * acted on anymore — the backend rejects it with 409 (ApprovalNotPendingError)
 * the moment expire_pending logic runs. The UI mirrors that check locally so
 * the buttons are disabled before the round trip. */
export function isExpired(approval: Pick<Approval, "status" | "expires_at">, now: Date = new Date()): boolean {
  if (approval.status !== "PENDING") return false;
  if (!approval.expires_at) return false;
  return new Date(approval.expires_at).getTime() <= now.getTime();
}

export function isActionable(approval: Pick<Approval, "status" | "expires_at">, now: Date = new Date()): boolean {
  return approval.status === "PENDING" && !isExpired(approval, now);
}
