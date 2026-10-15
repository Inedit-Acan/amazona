import type { RevenueProviderKind, RevenueSummary } from "./api.ts";
import { originName } from "./provenance.ts";
import { RevenueContractError } from "./revenue-contract.ts";
import { classificationLabel, evidenceLabel, formatMoney } from "./revenue-format.ts";

// EL NÚCLEO de la semántica de los ingresos verificados (M47, Commit 3A.1). UNA sola semántica y varias presentaciones: `/ceo`
// (`lib/ceo-kpis.ts`), `/dashboard` y `/cfo` (`lib/revenue-view.ts`) leen `GET /api/revenue/summary` SOLO a través de este módulo. Ninguno
// de los tres toca `verified[]`, `under_review[]`, `pending_evidence` ni `non_aggregable_currencies[]`: lo prohíbe una prueba de frontera
// (`lib/revenue-figures-boundary.test.ts`).
//
// La unidad es la pareja ORIGEN × MONEDA (`provider_kind` × `currency`): dos dimensiones distintas, ninguna se pierde ni se funde con la otra.
//
//   · Las cifras salen de `verified[]`, con `revenue`, `refunds` y `net` tal cual los calcula el backend: no se recalcula nada y no hay
//     `float` (todo es texto decimal hasta el formateo).
//   · NUNCA de `consolidated_eur_by_origin`: es un bloque solo en EUR que además se emite cuando EUR existe únicamente en revisión, y entonces
//     trae `revenue: "0.0000"` sin ningún cobro verificado; usarlo fabricaría un cero.
//   · `non_aggregable_currencies[]` son las monedas que NO se integran en un total EUR (no hay tipo de cambio). No significa ocultarlas: sus
//     importes están en `verified[]`. Una moneda que solo está ahí, sin ningún importe verificado, sale como una nota, nunca como ingreso.
//   · Ninguna suma entre monedas ni entre orígenes (ADR 0030 L6, ADR 0031 A1): ese total no existe.
//   · `under_review[]` y `pending_evidence` nunca entran en la cifra: son información secundaria, siempre aparte.
//   · `verified[]` vacío ⇒ `empty` (también si hay dinero en revisión o pendiente). Un contrato roto ⇒ `error`, jamás `empty`.
//   · Un orden determinista, independiente del de la respuesta: EUR primero, luego las demás monedas por código y, dentro de cada moneda, el
//     origen por su valor guardado.

export interface FigureLine {
  /** `<moneda>·<origen>`: una línea es de UN origen y UNA moneda, nunca de dos. */
  key: string;
  providerKind: RevenueProviderKind;
  /** El origen tal como se llama en pantalla. */
  origin: string;
  currency: string;
  revenue: string;
  refunds: string;
  /** El neto que calculó el backend (puede ser negativo: un reembolso de una captura anterior). */
  net: string;
  netNegative: boolean;
  captures: number;
  refundCount: number;
}

export interface ReviewFigure {
  key: string;
  providerKind: RevenueProviderKind;
  origin: string;
  currency: string;
  classification: string;
  label: string;
  received: string;
  refunded: string;
  /** Lo pendiente de resolver (`outstanding`, tal cual lo da el backend). */
  amount: string;
  receipts: number;
  refundCount: number;
}

export interface PendingFigure {
  key: string;
  providerKind: RevenueProviderKind;
  origin: string;
  currency: string;
  label: string;
  count: number;
  amount: string;
}

export interface FigureSecondary {
  underReview: ReviewFigure[];
  /** Un recuento de eventos (no dinero). */
  pendingCount: number;
  pending: PendingFigure[];
  /** Monedas sin conversión contable que no tienen ningún importe verificado: se dicen, no se inventan. */
  notes: string[];
}

export type RevenueFigures =
  | { kind: "error"; message: string }
  | { kind: "empty"; secondary: FigureSecondary }
  | { kind: "loaded"; lines: FigureLine[]; secondary: FigureSecondary };

/** Lo que dice la sección secundaria: lo que NO forma parte de la cifra de Ingresos. */
export const OUTSIDE_FIGURE_TEXT = "Fuera de esta cifra (no es ingreso verificado)";

/** El resumen compacto de lo que queda fuera de la cifra, con recuentos y sin sumar importes ni monedas; `null` si no hay nada. */
export function secondarySummary(secondary: FigureSecondary): string | null {
  const parts: string[] = [];
  if (secondary.underReview.length > 0) parts.push(`${secondary.underReview.length} en revisión`);
  if (secondary.pendingCount > 0) parts.push(`${secondary.pendingCount} sin asentar`);
  else if (secondary.pending.length > 0) parts.push(`${secondary.pending.length} pendientes`);
  if (secondary.notes.length > 0) parts.push(`${secondary.notes.length} sin conversión`);
  return parts.length === 0 ? null : `Fuera de esta cifra: ${parts.join(" · ")}`;
}

/** Cuántas cifras hay cuando son varias (origen × moneda): se dice, para que un scroll o un resumen no escondan que hay más. */
export const linesCountText = (count: number): string => `${count} cifras · origen × moneda`;

export const hasSecondary = (secondary: FigureSecondary): boolean =>
  secondary.underReview.length > 0 || secondary.pendingCount > 0 || secondary.pending.length > 0 || secondary.notes.length > 0;

// --- Orden y formato: la ÚNICA implementación -------------------------------------------------------------------------------------

const compare = (a: string, b: string) => (a < b ? -1 : a > b ? 1 : 0);
const currencyRank = (currency: string) => (currency === "EUR" ? 0 : 1);

const byCurrencyThenOrigin = (
  a: { currency: string; provider_kind: string; classification?: string; event_type?: string },
  b: { currency: string; provider_kind: string; classification?: string; event_type?: string },
) =>
  currencyRank(a.currency) - currencyRank(b.currency) ||
  compare(a.currency, b.currency) ||
  compare(a.provider_kind, b.provider_kind) ||
  compare(a.classification ?? "", b.classification ?? "") ||
  compare(a.event_type ?? "", b.event_type ?? "");

const isNegative = (amount: string) => /^-\d*\.?\d*[1-9]/.test(amount);

type VerifiedRow = RevenueSummary["verified"][number];
type ReviewRow = RevenueSummary["under_review"][number];
type PendingRow = RevenueSummary["pending_evidence"]["by_currency"][number];

/** Una línea por fila de `verified[]`, en el orden determinista. No valida ni agrega: lo hace `revenueFigures`. */
function verifiedLines(rows: VerifiedRow[]): FigureLine[] {
  return [...rows].sort(byCurrencyThenOrigin).map((row) => ({
    key: `${row.currency}·${row.provider_kind}`,
    providerKind: row.provider_kind,
    origin: originName(row.provider_kind),
    currency: row.currency,
    revenue: formatMoney(row.revenue, row.currency),
    refunds: formatMoney(row.refunds, row.currency),
    net: formatMoney(row.net, row.currency),
    netNegative: isNegative(row.net),
    captures: row.captures,
    refundCount: row.refund_count,
  }));
}

function reviewFigures(rows: ReviewRow[]): ReviewFigure[] {
  return [...rows].sort(byCurrencyThenOrigin).map((row) => ({
    key: `${row.currency}·${row.provider_kind}·${row.classification}`,
    providerKind: row.provider_kind,
    origin: originName(row.provider_kind),
    currency: row.currency,
    classification: row.classification,
    label: classificationLabel(row.classification),
    received: formatMoney(row.received, row.currency),
    refunded: formatMoney(row.refunded, row.currency),
    amount: formatMoney(row.outstanding, row.currency),
    receipts: row.receipts,
    refundCount: row.refund_count,
  }));
}

function pendingFigures(rows: PendingRow[]): PendingFigure[] {
  return [...rows].sort(byCurrencyThenOrigin).map((row) => ({
    key: `${row.currency}·${row.provider_kind}·${row.event_type}`,
    providerKind: row.provider_kind,
    origin: originName(row.provider_kind),
    currency: row.currency,
    label: evidenceLabel(row.event_type),
    count: row.count,
    amount: formatMoney(row.amount, row.currency),
  }));
}

/** Las monedas declaradas sin conversión que NO tienen ninguna línea verificada, como nota; nunca una cifra. */
function conversionNotes(declared: RevenueSummary["non_aggregable_currencies"], withLine: Set<string>): string[] {
  return [...new Set(declared.map((row) => row.currency))]
    .filter((currency) => !withLine.has(currency))
    .sort((a, b) => currencyRank(a) - currencyRank(b) || compare(a, b))
    .map((currency) => `${currency}: sin conversión contable disponible`);
}

const contractError = (message: string): RevenueFigures => ({ kind: "error", message: new RevenueContractError(message).message });

/** La semántica completa. Una respuesta que no tiene la forma del contrato, o con dos filas para el mismo origen y moneda, es un `error`
 * visible: no se suma en silencio ni se toma por un vacío. */
export function revenueFigures(summary: RevenueSummary): RevenueFigures {
  if (
    !Array.isArray(summary?.verified) ||
    !Array.isArray(summary.under_review) ||
    !Array.isArray(summary.non_aggregable_currencies) ||
    !summary.pending_evidence ||
    !Array.isArray(summary.pending_evidence.by_currency)
  ) {
    return contractError("la respuesta no trae verified, under_review, pending_evidence y non_aggregable_currencies con su forma");
  }

  const seen = new Set<string>();
  for (const row of summary.verified) {
    const key = `${row.currency}·${row.provider_kind}`;
    if (seen.has(key)) {
      return contractError(`verified trae dos filas para ${row.currency} · ${originName(row.provider_kind)}: no se suman en silencio`);
    }
    seen.add(key);
  }

  const lines = verifiedLines(summary.verified);
  const secondary: FigureSecondary = {
    underReview: reviewFigures(summary.under_review),
    pendingCount: summary.pending_evidence.count,
    pending: pendingFigures(summary.pending_evidence.by_currency),
    notes: conversionNotes(summary.non_aggregable_currencies, new Set(summary.verified.map((row) => row.currency))),
  };
  return lines.length === 0 ? { kind: "empty", secondary } : { kind: "loaded", lines, secondary };
}

/** Lo que necesitan las TABLAS de `/dashboard` y `/cfo` (todas las filas, sin validar ni fallar): las mismas líneas y el mismo orden que
 * las tarjetas, porque salen de las mismas funciones. */
export interface SummaryFigures {
  hasAnyData: boolean;
  origins: RevenueProviderKind[];
  verified: FigureLine[];
  underReview: ReviewFigure[];
  pending: { count: number; lines: PendingFigure[] };
  /** Las monedas declaradas sin conversión (solo informativo: no oculta ninguna). */
  nonAggregable: string[];
}

export function summaryFigures(summary: RevenueSummary): SummaryFigures {
  return {
    hasAnyData: summary.entries > 0 || summary.pending_evidence.count > 0,
    origins: summary.entries_by_provider_kind.map((row) => row.provider_kind),
    verified: verifiedLines(summary.verified),
    underReview: reviewFigures(summary.under_review),
    pending: { count: summary.pending_evidence.count, lines: pendingFigures(summary.pending_evidence.by_currency) },
    nonAggregable: summary.non_aggregable_currencies.map((row) => row.currency).sort(),
  };
}
