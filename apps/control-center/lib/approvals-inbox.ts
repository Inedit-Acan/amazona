import { actorLabel } from "./actor-label.ts";
import type { Approval, BudgetEffect, PipelineReview } from "./api.ts";
import { actionLabel, decisionImpact, resolvedImpact } from "./approvals.ts";
import { PIPELINE_STEP_LABELS, SIDE_EFFECT_LABELS } from "./approval-labels.ts";
import { formatUtcDateTime } from "./ceo-block-view.ts";
import { parseUtc } from "./dates.ts";
import { formatAmount } from "./format.ts";
import { listOf, type ReadState } from "./read-state.ts";

// LA BANDEJA REAL de /approvals (M47, Commit 6b). Antes la bandeja era UNA lista que mezclaba las aprobaciones del backend con solicitudes
// de demostración, y los indicadores contaban las dos; además la solicitud real llevaba una fecha de solicitud INVENTADA («caducidad − 24 h»
// o «ahora»), un vencimiento por SLA de severidad inventado, una severidad inventada y un solicitante escrito a mano. Esta capa es lo
// contrario: solo lo que el backend guarda y nada de demostración.
//
//   · `requestedAt` es `approvals.requested_at` (Commit 6a) o NULL: sin el dato no hay fecha, nunca «ahora» ni «caducidad − 24 h».
//   · `expiresAt` es `approvals.expires_at` o NULL: una revisión de pipeline no caduca y no se le inventa un SLA.
//   · No hay severidad, ni «Críticas», ni solicitante: el backend no los guarda.
//   · Un fallo de lectura es un aviso de ESA fuente (y las cifras que dependen de ella pasan a «No disponible»): nunca una lista vacía ni
//     un cero. `empty` (un hecho) y `error` / `unread` (no se sabe) son cosas distintas.

export interface RealRequest {
  id: string;
  code: string;
  source: "approval" | "review";
  title: string;
  /** De dónde sale, tal como lo dice el backend: la aprobación de una decisión del CEO o una revisión del pipeline. */
  originLabel: string;
  amount: number | null;
  /** `approvals.requested_at` en ms, o `null` si el backend no lo envió (backend anterior al 6a, o una revisión de pipeline). */
  requestedAt: number | null;
  /** `approvals.expires_at` en ms, o `null` (sin vencimiento: las revisiones de pipeline no caducan). */
  expiresAt: number | null;
  /** El estado TAL CUAL lo guarda el backend. */
  status: string;
  /** PENDING con el vencimiento ya pasado: el backend ya no la deja resolver. No cambia `status`. */
  expired: boolean;
  correlationId: string | null;
  /** Lo que la aprobación hizo en el LIBRO del presupuesto; `null` si el backend no lo envió (una revisión de pipeline no mueve presupuesto). */
  budgetEffect: BudgetEffect | null;
  /** `resolved_at` en ms, o `null` (sigue pendiente o el backend no lo envió). */
  resolvedAt: number | null;
  fields: { label: string; value: string }[];
  /** Lo que PASARÍA al aprobar / rechazar (solo tiene sentido si sigue pendiente y no ha vencido). */
  approveImpact: string[];
  rejectImpact: string[];
  /** Lo que PASÓ, si ya está resuelta (aprobada, rechazada…): vacío mientras está pendiente. */
  resolution: string[];
}

export type SourceNotice = { kind: "error" | "unread"; text: string };

export type InboxState = "loaded" | "empty" | "partial" | "error" | "unread";

export interface RealInbox {
  requests: RealRequest[];
  /** Por qué falta una fuente (`null` = leída bien). */
  sources: { approvals: SourceNotice | null; reviews: SourceNotice | null };
  /** `null` si alguna fuente no se pudo leer: una cifra parcial presentada como total sería falsa. */
  kpis: { pending: number | null; expired: number | null; expiringSoon: number | null };
  /** loaded = hay filas; empty = las dos fuentes leídas y vacías; partial = una fuente falta; error / unread = ninguna se leyó. */
  state: InboxState;
}

const HOUR_MS = 3_600_000;
const EXPIRING_SOON_MS = 4 * HOUR_MS;

const instantOf = (value: string | null | undefined): number | null => (value === null || value === undefined ? null : parseUtc(value));
const dateText = (ms: number | null) => (ms === null ? "—" : formatUtcDateTime(ms));

export function realRequestFromApproval(approval: Approval, now: number): RealRequest {
  const requestedAt = instantOf(approval.requested_at);
  const expiresAt = instantOf(approval.expires_at);
  const impact = decisionImpact(approval);
  const resolvedAt = instantOf(approval.resolved_at);
  const pending = approval.status === "PENDING" && !(expiresAt !== null && expiresAt <= now);
  return {
    id: approval.id,
    code: `APR-${approval.id.slice(0, 5).toUpperCase()}`,
    source: "approval",
    title: actionLabel(approval.action),
    originLabel: "Aprobación de una decisión del CEO",
    amount: approval.amount,
    requestedAt,
    expiresAt,
    status: approval.status,
    expired: approval.status === "PENDING" && expiresAt !== null && expiresAt <= now,
    correlationId: approval.correlation_id ?? null,
    budgetEffect: approval.budget_effect ?? null,
    resolvedAt,
    fields: [
      { label: "Acción", value: approval.action },
      { label: "Importe", value: approval.amount === null ? "Sin importe" : `${formatAmount(approval.amount)} (el backend no indica la moneda)` },
      { label: "Estado", value: approval.status },
      { label: "Solicitada", value: requestedAt === null ? "Sin fecha de solicitud (el backend no la envió)" : dateText(requestedAt) },
      { label: "Vence", value: expiresAt === null ? "Sin vencimiento" : dateText(expiresAt) },
      ...(approval.resolved_at === null ? [] : [{ label: "Resuelta", value: dateText(parseUtc(approval.resolved_at)) }]),
      ...(approval.resolved_by === null ? [] : [{ label: "Resuelta por", value: actorLabel(approval.resolved_by) }]),
      ...(approval.correlation_id === undefined ? [] : [{ label: "Correlación", value: approval.correlation_id }]),
    ],
    approveImpact: impact.approve,
    rejectImpact: impact.reject,
    resolution: pending ? [] : resolutionLines(approval),
  };
}

/** Lo que consta de una aprobación que ya no está pendiente: cómo terminó y qué pasó con el presupuesto, sin suponer nada. */
function resolutionLines(approval: Approval): string[] {
  const outcome: Record<string, string> = {
    APPROVED: "Aprobada: la acción quedó autorizada (una sola vez).",
    REJECTED: "Rechazada: la acción no se ejecuta.",
    EXPIRED: "Venció sin resolverse: ya no se puede aprobar ni rechazar.",
    CANCELLED: "Cancelada.",
    CONSUMED: "Consumida: su autorización ya se usó.",
  };
  const headline =
    approval.status === "PENDING" ? "Venció sin resolverse: ya no se puede aprobar ni rechazar." : (outcome[approval.status] ?? `Estado: ${approval.status}.`);
  return [headline, ...resolvedImpact(approval)];
}

export function realRequestFromReview(review: PipelineReview): RealRequest {
  const isGate = review.kind === "ACTION_GATE";
  const action = review.action === null ? null : (SIDE_EFFECT_LABELS[review.action] ?? review.action);
  const step = review.step === null ? null : (PIPELINE_STEP_LABELS[review.step] ?? review.step);
  return {
    id: review.id,
    code: `${isGate ? "ACT" : "REV"}-${review.id.slice(0, 5).toUpperCase()}`,
    source: "review",
    title: isGate && action !== null ? `Autorizar: ${action}` : isGate ? "Autorización de acción" : "Revisión posterior de una ejecución del pipeline",
    originLabel: isGate ? "Autorización de acción del pipeline" : "Revisión posterior del pipeline",
    amount: null,
    requestedAt: null,
    expiresAt: null,
    status: review.status,
    expired: false,
    correlationId: review.correlation_id ?? null,
    budgetEffect: null,
    resolvedAt: instantOf(review.resolved_at),
    fields: [
      { label: "Ejecución", value: review.pipeline_run_id },
      ...(step === null ? [] : [{ label: "Paso", value: step }]),
      { label: "Estado", value: review.status },
      { label: "Solicitada", value: "Sin fecha de solicitud (el backend no la guarda)" },
      { label: "Motivos", value: review.reasons.length === 0 ? "Ninguno" : review.reasons.join("; ") },
      ...(review.resolved_by === null ? [] : [{ label: "Resuelta por", value: actorLabel(review.resolved_by) }]),
    ],
    approveImpact: isGate
      ? [`Se ejecuta «${action ?? "la acción"}» y la ejecución continúa por ese paso.`, "Queda registrada en la auditoría."]
      : ["La ejecución del pipeline continúa.", "Queda registrada en la auditoría."],
    rejectImpact: isGate
      ? [`No se ejecuta «${action ?? "la acción"}»: ese paso queda denegado.`, "El resto de la cadena sigue: lo que solo analiza no se detiene."]
      : ["La ejecución del pipeline no continúa.", "Queda registrada en la auditoría."],
    resolution: review.status === "PENDING" ? [] : [review.status === "APPROVED" ? "Aprobada." : review.status === "REJECTED" ? "Rechazada." : `Estado: ${review.status}.`],
  };
}

function noticeOf(state: ReadState<unknown>): SourceNotice | null {
  if (state.kind === "error") return { kind: "error", text: state.message };
  if (state.kind === "unread") return { kind: "unread", text: state.reason };
  return null;
}

export function realInbox(input: { approvals: ReadState<Approval[]>; reviews: ReadState<PipelineReview[]>; now: number }): RealInbox {
  const { approvals, reviews, now } = input;
  const sources = { approvals: noticeOf(approvals), reviews: noticeOf(reviews) };
  const requests = [
    ...(listOf(approvals) ?? []).map((approval) => realRequestFromApproval(approval, now)),
    ...(listOf(reviews) ?? []).map((review) => realRequestFromReview(review)),
  ];
  const usable = [sources.approvals === null, sources.reviews === null].filter(Boolean).length;
  const state: InboxState =
    usable === 2 ? (requests.length === 0 ? "empty" : "loaded") : usable === 1 ? "partial" : sources.approvals?.kind === "unread" && sources.reviews?.kind === "unread" ? "unread" : "error";

  const pending = requests.filter((request) => request.status === "PENDING" && !request.expired);
  const kpis =
    usable === 2
      ? {
          pending: pending.length,
          expired: requests.filter((request) => request.expired).length,
          expiringSoon: pending.filter((request) => request.expiresAt !== null && request.expiresAt - now <= EXPIRING_SOON_MS).length,
        }
      : { pending: null, expired: null, expiringSoon: null };
  return { requests, sources, kpis, state };
}

export type RealFilter = "pending" | "all";
export type RealSort = "expiry" | "recent";

export const REAL_FILTERS: { key: RealFilter; label: string }[] = [
  { key: "pending", label: "Pendientes" },
  { key: "all", label: "Todas" },
];

export const REAL_SORT_LABELS: Record<RealSort, string> = { expiry: "Por vencimiento", recent: "Más recientes" };

export function filterReal(requests: RealRequest[], filter: RealFilter): RealRequest[] {
  return filter === "all" ? requests : requests.filter((request) => request.status === "PENDING" && !request.expired);
}

const byId = (a: RealRequest, b: RealRequest) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0);

export function sortReal(requests: RealRequest[], sort: RealSort): RealRequest[] {
  const copy = [...requests];
  if (sort === "recent") {
    // Más reciente primero; sin fecha de solicitud, al final (nunca arriba); el id desempata.
    return copy.sort((a, b) => {
      if (a.requestedAt === b.requestedAt) return byId(a, b);
      if (a.requestedAt === null) return 1;
      if (b.requestedAt === null) return -1;
      return b.requestedAt - a.requestedAt;
    });
  }
  // El que antes vence, primero; sin vencimiento, al final; el id desempata.
  return copy.sort((a, b) => {
    if (a.expiresAt === b.expiresAt) return byId(a, b);
    if (a.expiresAt === null) return 1;
    if (b.expiresAt === null) return -1;
    return a.expiresAt - b.expiresAt;
  });
}
