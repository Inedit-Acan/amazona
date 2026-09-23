import type { Approval } from "./api.ts";
import { parseUtc } from "./dates.ts";
import { formatAmount } from "./format.ts";

// Lo que se puede decir de una aprobación del backend: si sigue accionable, cómo
// se llama su acción y qué pasa al aprobarla o rechazarla (api/approvals.py). La
// bandeja que enseña la pantalla la construye lib/approvals-view.ts.

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

const ACTION_LABELS: Record<string, string> = {
  launch_marketing_campaign: "Lanzamiento de campaña de marketing",
};

export function actionLabel(action: string): string {
  const known = ACTION_LABELS[action];
  if (known) return known;
  const text = action.replace(/_/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
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
