import type { Approval, BudgetEffect } from "./api.ts";
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

/** Lo que el backend sabe del importe de una aprobación. */
type ImpactInput = Pick<Approval, "action" | "amount"> & { budget_effect?: BudgetEffect };

const NO_FINANCIAL_IMPACT = "Impacto financiero no disponible.";

/** Qué pasa AL APROBAR y AL RECHAZAR una aprobación PENDIENTE. El efecto en el presupuesto sale del LIBRO (`budget_effect`, el que
 * guarda `financial_events` para esa aprobación) y NUNCA del importe: tener un importe no implica que haya presupuesto reservado. Una
 * aprobación sin presupuesto autorizado (despliegue simulado) no reserva ni compromete nada y así se dice.
 *   · `reserved`  → aprobar compromete lo reservado; rechazar lo libera;
 *   · `none`      → no hay reserva: ni se compromete ni se libera nada;
 *   · sin dato (backend anterior) → «Impacto financiero no disponible.»;
 *   · sin importe o con importe 0 → no se enseña ningún impacto financiero (no se finge uno). */
export function decisionImpact(approval: ImpactInput): DecisionImpact {
  const label = actionLabel(approval.action);
  const amount = approval.amount != null && approval.amount > 0 ? formatAmount(approval.amount) : null;
  const effect = approval.budget_effect;

  let approveMoney: string[] = [];
  let rejectMoney: string[] = [];
  if (amount !== null) {
    if (effect === "reserved") {
      approveMoney = ["El importe reservado en el presupuesto pasa a comprometido."];
      rejectMoney = [`Se libera la reserva de ${amount} del presupuesto.`];
    } else if (effect === "none") {
      approveMoney = ["No hay reserva en el presupuesto para esta aprobación: no reserva ni compromete fondos."];
      rejectMoney = ["No hay reserva que liberar: no se mueve ningún fondo del presupuesto."];
    } else {
      // Sin el dato del libro (backend anterior), o un efecto ya liquidado en una aprobación que sigue pendiente (no es coherente):
      // no se afirma nada.
      approveMoney = [NO_FINANCIAL_IMPACT];
      rejectMoney = [NO_FINANCIAL_IMPACT];
    }
  }
  return {
    approve: [
      `Se autoriza «${label}»${amount ? ` por ${amount}` : ""}.`,
      ...approveMoney,
      "Autoriza solo esta acción con este importe y no se puede reutilizar. Queda registrado en la auditoría.",
    ],
    reject: [`No se ejecuta «${label}».`, ...rejectMoney, "La solicitud queda resuelta y registrada en la auditoría."],
  };
}

/** Qué pasó con el presupuesto cuando una aprobación YA se resolvió (en pasado, y solo lo que el libro dice). */
export function resolvedImpact(approval: ImpactInput): string[] {
  const amount = approval.amount != null && approval.amount > 0 ? formatAmount(approval.amount) : null;
  if (amount === null) return ["Sin importe: no hay impacto financiero que mostrar."];
  switch (approval.budget_effect) {
    case "committed":
      return [`La reserva de ${amount} pasó a comprometida en el presupuesto.`];
    case "released":
      return [`La reserva de ${amount} se liberó: el presupuesto no se compromete.`];
    case "reserved":
      return [`El importe de ${amount} sigue reservado en el presupuesto, sin liquidar.`];
    case "none":
      return ["No hubo movimiento en el presupuesto: no se reservó ni se comprometió ningún fondo."];
    default:
      return [NO_FINANCIAL_IMPACT];
  }
}
