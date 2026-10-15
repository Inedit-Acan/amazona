import type { Approval, PipelineReview } from "./api.ts";
import { actionLabel, isExpired } from "./approvals.ts";
import { emptyView, formatUtcDateTime, loadedView, plural, unusable, type BlockRow, type BlockView } from "./ceo-block-view.ts";
import { parseUtc } from "./dates.ts";
import { formatAmount } from "./format.ts";
import { listOf, type ReadState } from "./read-state.ts";

// DECISIONES PENDIENTES (M47, Commit 3B, D-3B-1). Una decisión «pendiente» es lo que un humano tiene que contestar y desbloquea algo:
//
//   · una APROBACIÓN `PENDING` y no vencida (la autorización de una decisión del CEO, con su dinero ya reservado), o
//   · una autorización de acción (`ACTION_GATE`) pendiente (autoriza un efecto de un paso que todavía no ha ocurrido).
//
// Lo que NO lo es, y se dice aparte sin sumar al contador:
//
//   · una aprobación `PENDING` VENCIDA (ya no se puede contestar: el backend la rechaza), y
//   · una revisión posterior (`POST_HOC`): una anotación sobre una ejecución terminada que «nunca autoriza nada».
//
// Una `Decision` (HUMAN_APPROVAL, GO…) es una RECOMENDACIÓN del motor de decisión, no una decisión pendiente: este módulo no la lee. Las
// listas de aprobaciones y de revisiones NO traen prioridad, severidad, fecha de solicitud, solicitante, confianza ni racional, y aquí
// no se inventan (el racional de una revisión son sus `reasons[]` reales). El importe se muestra y NO deriva ninguna prioridad.

export const DECISIONS_BLOCK = {
  key: "decisiones",
  title: "Decisiones pendientes",
  tab: "Decisiones",
  seeAll: { href: "/approvals", label: "Ver todas" },
} as const;

/** Los efectos que una autorización de acción puede pedir (plan maestro §7). Una acción que no está aquí se enseña con su nombre real. */
const SIDE_EFFECT_LABELS: Record<string, string> = {
  publish_product: "publicar el producto",
  activate_ads: "activar la publicidad",
  spend_money: "gastar dinero",
  purchase_supplier: "comprar al proveedor",
  make_payment: "realizar el pago",
  ship_order: "enviar el pedido",
  refund: "hacer el reembolso",
  change_price: "cambiar el precio",
  send_contract_communication: "enviar la comunicación contractual",
};

const PIPELINE_STEP_LABELS: Record<string, string> = {
  research: "Investigación",
  sourcing: "Proveedores",
  economics: "Economía",
  legal: "Legal",
  ecommerce: "Tienda",
  marketplace: "Marketplace",
  marketing: "Marketing",
  operations: "Operaciones",
  cfo: "CFO",
};

const EMPTY_TEXT = "Ninguna decisión pendiente.";
const NO_ROWS_TEXT = "Ninguna decisión accionable.";

function approvalRow(approval: Approval): BlockRow {
  const amount = approval.amount === null ? "Sin importe" : `Importe ${formatAmount(approval.amount)}`;
  const expiry = approval.expires_at === null ? "Sin vencimiento" : `vence ${formatUtcDateTime(parseUtc(approval.expires_at))}`;
  return {
    key: `approval:${approval.id}`,
    title: actionLabel(approval.action),
    subtitle: `${amount} · ${expiry}`,
    tag: { text: "Aprobación del CEO" },
    detail: [
      `Acción: ${approval.action}`,
      "Autorización de una decisión del CEO; el importe está reservado en el presupuesto hasta que se resuelva.",
      ...(approval.amount === null ? [] : ["El backend no indica la moneda del importe."]),
    ],
    provenance: {
      source: "approvals",
      entity: "approval",
      id: approval.id,
      status: approval.status,
      areaLabel: "Aprobación del CEO",
      at: approval.expires_at,
      confidence: null,
      rationale: null,
    },
  };
}

function gateRow(review: PipelineReview): BlockRow {
  const action = review.action === null ? null : (SIDE_EFFECT_LABELS[review.action] ?? review.action);
  const step = review.step === null ? null : (PIPELINE_STEP_LABELS[review.step] ?? review.step);
  return {
    key: `review:${review.id}`,
    title: action === null ? "Autorización de acción" : `Autorizar: ${action}`,
    subtitle: step === null ? "Paso no indicado" : `Paso: ${step}`,
    tag: { text: "Autorización de acción" },
    detail: [...review.reasons.map((reason) => `Motivo: ${reason}`), "Autoriza un efecto que todavía no ha ocurrido; no caduca."],
    provenance: {
      source: "pipeline_reviews",
      entity: "pipeline_review",
      id: review.id,
      status: review.status,
      areaLabel: "Revisión del pipeline",
      at: null,
      confidence: null,
      rationale: review.reasons.length === 0 ? null : review.reasons.join("; "),
    },
  };
}

/** Por vencimiento ascendente (la que antes vence, primero); sin vencimiento, al final; el id desempata. */
function byExpiry(a: Approval, b: Approval): number {
  const ax = a.expires_at === null ? Number.POSITIVE_INFINITY : parseUtc(a.expires_at);
  const bx = b.expires_at === null ? Number.POSITIVE_INFINITY : parseUtc(b.expires_at);
  if (ax !== bx) return ax < bx ? -1 : 1;
  return a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
}

export function decisionsBlock(input: { approvals: ReadState<Approval[]>; reviews: ReadState<PipelineReview[]>; now: number }): BlockView {
  const { approvals, reviews, now } = input;
  const failed = unusable([approvals, reviews]);
  if (failed) return failed;

  const pending = (listOf(approvals) ?? []).filter((approval) => approval.status === "PENDING");
  const at = new Date(now);
  const actionable = pending.filter((approval) => !isExpired(approval, at)).sort(byExpiry);
  const expired = pending.filter((approval) => isExpired(approval, at));
  const open = (listOf(reviews) ?? []).filter((review) => review.status === "PENDING");
  const gates = open.filter((review) => review.kind === "ACTION_GATE");
  const postHoc = open.filter((review) => review.kind === "POST_HOC");

  const rows = [...actionable.map(approvalRow), ...gates.map(gateRow)];
  const secondary = [
    ...(expired.length === 0 ? [] : [`${expired.length} ${plural(expired.length, "aprobación vencida", "aprobaciones vencidas")} sin resolver`]),
    ...(postHoc.length === 0
      ? []
      : [`${postHoc.length} ${plural(postHoc.length, "revisión posterior sin resolver (no autoriza nada)", "revisiones posteriores sin resolver (no autorizan nada)")}`]),
  ];
  if (rows.length === 0 && secondary.length === 0) return emptyView(EMPTY_TEXT);
  return loadedView({
    rows,
    countText: String(rows.length),
    countLabel: `${rows.length} ${plural(rows.length, "decisión accionable", "decisiones accionables")}`,
    noRowsText: rows.length === 0 ? NO_ROWS_TEXT : null,
    secondary,
  });
}
