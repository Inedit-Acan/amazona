import type { Approval, Decision, PipelineReview, Project } from "./api.ts";
import { isSameLocalDay, parseUtc, relativeTime } from "./dates.ts";
import { formatAmount } from "./format.ts";

/** An approval that is still PENDING but whose expiry has passed cannot be
 * acted on anymore — the backend rejects it with 409 (ApprovalNotPendingError)
 * the moment expire_pending logic runs. The UI mirrors that check locally so
 * the buttons are disabled before the round trip. */
export function isExpired(approval: Pick<Approval, "status" | "expires_at">, now: Date = new Date()): boolean {
  if (approval.status !== "PENDING") return false;
  if (!approval.expires_at) return false;
  return parseUtc(approval.expires_at) <= now.getTime();
}

export function isActionable(approval: Pick<Approval, "status" | "expires_at">, now: Date = new Date()): boolean {
  return approval.status === "PENDING" && !isExpired(approval, now);
}

// --- Bandeja unificada: aprobaciones de gasto + revisiones de pipeline (ADR 0006) ---

export type InboxEntry =
  | { kind: "approval"; id: string; approval: Approval; decision: Decision | null; project: Project | null }
  | { kind: "pipeline_review"; id: string; review: PipelineReview };

/** Un elemento se puede accionar hoy: aprobación pendiente sin vencer, o revisión pendiente. */
export function isEntryPending(entry: InboxEntry, now: Date = new Date()): boolean {
  return entry.kind === "approval" ? isActionable(entry.approval, now) : entry.review.status === "PENDING";
}

/** Estado que se muestra: una aprobación pendiente ya vencida figura como expirada. */
export function entryStatus(entry: InboxEntry, now: Date = new Date()): string {
  if (entry.kind === "pipeline_review") return entry.review.status;
  return isExpired(entry.approval, now) ? "EXPIRED" : entry.approval.status;
}

const ACTION_LABELS: Record<string, string> = {
  launch_marketing_campaign: "Lanzamiento de campaña de marketing",
};

export function actionLabel(action: string): string {
  const known = ACTION_LABELS[action];
  if (known) return known;
  const text = action.replace(/_/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function entryTitle(entry: InboxEntry): string {
  return entry.kind === "approval" ? actionLabel(entry.approval.action) : "Revisión de pipeline";
}

export function entryAmount(entry: InboxEntry): number | null {
  return entry.kind === "approval" ? entry.approval.amount : null;
}

/** Instante en que se resolvió (aprobó, rechazó o expiró), si ya se resolvió. */
function resolvedAt(entry: InboxEntry): number | null {
  const value = entry.kind === "approval" ? entry.approval.resolved_at : entry.review.resolved_at;
  return value ? parseUtc(value) : null;
}

/** Pendientes primero (las que vencen antes, arriba) y después las decididas, la más reciente primero. */
export function sortInbox(entries: InboxEntry[], now: Date = new Date()): InboxEntry[] {
  const expiry = (entry: InboxEntry) =>
    entry.kind === "approval" && entry.approval.expires_at ? parseUtc(entry.approval.expires_at) : Number.POSITIVE_INFINITY;
  return [...entries].sort((a, b) => {
    const pa = isEntryPending(a, now);
    const pb = isEntryPending(b, now);
    if (pa !== pb) return pa ? -1 : 1;
    if (pa) return expiry(a) - expiry(b);
    return (resolvedAt(b) ?? 0) - (resolvedAt(a) ?? 0);
  });
}

/** Horas por debajo de las cuales una solicitud pendiente «vence pronto». La spec no
 * fija el umbral: se usa un día. */
export const EXPIRING_SOON_HOURS = 24;

export interface InboxStats {
  pending: number;
  expiringSoon: number;
  approvedToday: number;
  decided: number;
  total: number;
}

export function inboxStats(entries: InboxEntry[], now: Date = new Date()): InboxStats {
  const nowMs = now.getTime();
  let pending = 0;
  let expiringSoon = 0;
  let approvedToday = 0;
  let decided = 0;
  for (const entry of entries) {
    if (isEntryPending(entry, now)) {
      pending += 1;
      if (entry.kind === "approval" && entry.approval.expires_at) {
        const remaining = parseUtc(entry.approval.expires_at) - nowMs;
        if (remaining <= EXPIRING_SOON_HOURS * 3_600_000) expiringSoon += 1;
      }
    } else {
      decided += 1;
      const status = entry.kind === "approval" ? entry.approval.status : entry.review.status;
      const at = resolvedAt(entry);
      if (status === "APPROVED" && at !== null && isSameLocalDay(at, nowMs)) approvedToday += 1;
    }
  }
  return { pending, expiringSoon, approvedToday, decided, total: entries.length };
}

/** «Vence en 3 h», «Vencida hace 2 h» o «Sin vencimiento». */
export function expiryLabel(expiresAt: string | null, now: Date = new Date()): string {
  if (!expiresAt) return "Sin vencimiento";
  const target = parseUtc(expiresAt);
  return target > now.getTime() ? `Vence ${relativeTime(target, now.getTime())}` : `Vencida ${relativeTime(target, now.getTime())}`;
}

export interface DecisionImpact {
  approve: string[];
  reject: string[];
}

/** Qué pasa al aprobar y al rechazar, según lo que hace el backend: aprobar autoriza esa
 * única acción y compromete el importe del presupuesto; rechazar no la ejecuta y libera
 * la reserva (api/approvals.py). No se inventan condiciones ni límites. */
export function decisionImpact(approval: Pick<Approval, "action" | "amount">): DecisionImpact {
  const label = actionLabel(approval.action);
  const amount = approval.amount != null && approval.amount > 0 ? formatAmount(approval.amount) : null;
  return {
    approve: [
      `Se autoriza «${label}»${amount ? ` por ${amount}` : ""}.`,
      ...(amount ? ["El importe pasa de reservado a comprometido en el presupuesto."] : []),
      "Autoriza solo esta acción con este importe y no se puede reutilizar. Queda registrado en la auditoría.",
    ],
    reject: [
      `No se ejecuta «${label}».`,
      ...(amount ? [`Se libera la reserva de ${amount} del presupuesto.`] : []),
      "La solicitud queda resuelta y registrada en la auditoría.",
    ],
  };
}
