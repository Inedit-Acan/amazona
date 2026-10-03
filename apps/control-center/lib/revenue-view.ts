import type {
  DecimalText,
  RevenueEntriesPage,
  RevenueEntry,
  RevenueSeries,
  RevenueSummary,
} from "./api.ts";

// Vista de los ingresos del Panel (M45, ADR 0030). Aquí NO se calcula nada económico: el backend ya devolvió cada cifra
// por moneda, separando lo verificado, lo que está en revisión y la evidencia pendiente. Este módulo solo decide QUÉ SE
// ENSEÑA y CÓMO SE DICE, con tres reglas que las pruebas fijan:
//
//   1. «Sin datos» no es un cero. Un `consolidated_eur` nulo se dice «Sin datos»; un cero solo sale cuando el backend
//      lo midió (hay entradas en EUR y su suma es cero).
//   2. Las monedas no se suman ni se convierten. Cada una sale en su línea; lo único consolidado es EUR, y lo dice el
//      backend, no esta vista.
//   3. Lo verificado, lo que está en revisión y la evidencia pendiente son tres cosas distintas: ninguna cifra de una
//      se construye con las otras, y esta vista no hace ninguna suma de importes.
//
// No importa nada de `lib/demo` ni del P&L modelado (`cfo-view`, `operations-view`): lo que hay aquí es medido.

export const NO_DATA = "Sin datos";
const CONSOLIDATION_CURRENCY = "EUR";
const DAY_MS = 86_400_000;

// --- Importes: texto exacto, nunca `float` -------------------------------------------------------------------------

const DECIMAL = /^(-?)(\d+)(?:\.(\d+))?$/;

/** `"1234.5600"` → `"1.234,56 €"` sin pasar por un número: no hay redondeo ni pérdida de precisión con importes de 17
 * dígitos. Dos decimales salvo que haya una cifra distinta de cero más allá de los céntimos (entonces se enseñan todos:
 * nada se redondea en silencio). Un texto que no es un decimal se devuelve tal cual, visible: ocultarlo escondería un
 * contrato roto. */
export function formatMoney(amount: DecimalText, currency: string): string {
  const match = DECIMAL.exec(amount);
  if (!match) return `${amount} ${currency}`;
  const [, sign, integer, fraction = ""] = match;
  let decimals = fraction.padEnd(2, "0");
  if (decimals.length > 2 && /^0+$/.test(decimals.slice(2))) decimals = decimals.slice(0, 2);
  const grouped = integer.replace(/\B(?=(\d{3})+(?!\d))/g, ".");
  const isZero = /^0*$/.test(integer) && /^0*$/.test(decimals);
  const text = `${grouped},${decimals}`;
  const signed = sign === "-" && !isZero ? `−${text}` : text;
  return currency === CONSOLIDATION_CURRENCY ? `${signed} €` : `${signed} ${currency}`;
}

export function formatCount(value: number): string {
  return String(Math.round(value)).replace(/\B(?=(\d{3})+(?!\d))/g, ".");
}

// --- Etiquetas ----------------------------------------------------------------------------------------------------

const CLASSIFICATION_LABEL: Record<string, string> = {
  ORDER_PAYMENT: "Verificado",
  DUPLICATE_RECEIPT: "Duplicado · en revisión",
  MISMATCH_RECEIPT: "Discrepancia · en revisión",
};

const KIND_LABEL: Record<string, string> = { CAPTURE: "Cobro", REFUND: "Reembolso" };

const EVIDENCE_LABEL: Record<string, string> = {
  "payment.succeeded": "Cobro sin asentar",
  "refund.succeeded": "Reembolso sin asentar",
};

export const classificationLabel = (value: string) => CLASSIFICATION_LABEL[value] ?? value;
export const kindLabel = (value: string) => KIND_LABEL[value] ?? value;
export const evidenceLabel = (value: string) => EVIDENCE_LABEL[value] ?? value;

/** Solo `ORDER_PAYMENT` es ingreso verificado; todo lo demás está en revisión. */
export const isVerified = (classification: string) => classification === "ORDER_PAYMENT";

export const REVENUE_SCOPE_NOTE =
  "Cifras tomadas del registro de hechos de pago verificados; no son un modelo ni contabilidad: no incluyen costes, margen, " +
  "beneficio, impuestos, IVA/OSS, caja, comisiones ni conversión de divisas. Un hecho verificado tampoco dice si la operación " +
  "fue simulada: el registro todavía no guarda esa procedencia.";

export function periodLabel(days: number): string {
  return `últimos ${days} días`;
}

// --- Resultado de una lectura: dato o error visible ---------------------------------------------------------------

/** Lo que devuelve cada lectura del Panel. Un error se enseña como error; NUNCA se sustituye por datos de demostración. */
export type Settled<T> = { ok: true; data: T } | { ok: false; message: string };

/** Texto de un error de lectura. `detail` es el cuerpo legible del backend (`ApiError.detail`). */
export function revenueErrorText(status: number | undefined, detail: string): string {
  if (status === 401) return "La sesión no es válida o ha caducado. Vuelve a iniciar sesión.";
  if (status === 403) return "Tu usuario no tiene permiso para leer los ingresos (business.read).";
  if (status === 422) return `El backend rechazó la petición de ingresos: ${detail}`;
  if (status !== undefined && status >= 500) return `El backend falló al leer los ingresos (${status}): ${detail}`;
  return detail || "Error desconocido";
}

/** Ejecuta una lectura y devuelve el dato o el error. Reconoce un `ApiError` por su forma (`status`, `detail`) para no
 * depender de `lib/api.ts`, que arrastra el resolutor de token. */
export async function settle<T>(read: () => Promise<T>): Promise<Settled<T>> {
  try {
    return { ok: true, data: await read() };
  } catch (err) {
    const status = err !== null && typeof err === "object" && "status" in err && typeof err.status === "number" ? err.status : undefined;
    const detail =
      err !== null && typeof err === "object" && "detail" in err && typeof err.detail === "string"
        ? err.detail
        : err instanceof Error
          ? err.message
          : "error desconocido";
    return { ok: false, message: revenueErrorText(status, detail) };
  }
}

// --- Resumen ------------------------------------------------------------------------------------------------------

export interface VerifiedLine {
  currency: string;
  revenue: string;
  refunds: string;
  net: string;
  captures: string;
  refundCount: string;
}

export interface UnderReviewLine {
  currency: string;
  classification: string;
  label: string;
  received: string;
  refunded: string;
  outstanding: string;
  receipts: string;
  refundCount: string;
}

export interface EvidenceLine {
  currency: string;
  label: string;
  count: string;
  amount: string;
}

export interface SummaryView {
  /** Hay algo que enseñar: alguna entrada del registro o algún evento sin asentar. */
  hasAnyData: boolean;
  /** `null` = «Sin datos» en EUR. */
  eur: { revenue: string; refunds: string; net: string; underReview: string } | null;
  verified: VerifiedLine[];
  underReview: UnderReviewLine[];
  pendingEvidence: { count: number; lines: EvidenceLine[] };
  /** Monedas que no se consolidan: salen por separado y nunca se suman ni se convierten. */
  otherCurrencies: string[];
}

const byCurrency = <T extends { currency: string }>(a: T, b: T) => {
  const rank = (currency: string) => (currency === CONSOLIDATION_CURRENCY ? 0 : 1);
  return rank(a.currency) - rank(b.currency) || a.currency.localeCompare(b.currency);
};

export function summaryView(summary: RevenueSummary): SummaryView {
  const eur = summary.consolidated_eur;
  return {
    hasAnyData: summary.entries > 0 || summary.pending_evidence.count > 0,
    eur: eur
      ? {
          revenue: formatMoney(eur.revenue, eur.currency),
          refunds: formatMoney(eur.refunds, eur.currency),
          net: formatMoney(eur.net, eur.currency),
          underReview: formatMoney(eur.under_review_outstanding, eur.currency),
        }
      : null,
    verified: [...summary.verified].sort(byCurrency).map((row) => ({
      currency: row.currency,
      revenue: formatMoney(row.revenue, row.currency),
      refunds: formatMoney(row.refunds, row.currency),
      net: formatMoney(row.net, row.currency),
      captures: formatCount(row.captures),
      refundCount: formatCount(row.refund_count),
    })),
    underReview: [...summary.under_review].sort(byCurrency).map((row) => ({
      currency: row.currency,
      classification: row.classification,
      label: classificationLabel(row.classification),
      received: formatMoney(row.received, row.currency),
      refunded: formatMoney(row.refunded, row.currency),
      outstanding: formatMoney(row.outstanding, row.currency),
      receipts: formatCount(row.receipts),
      refundCount: formatCount(row.refund_count),
    })),
    pendingEvidence: {
      count: summary.pending_evidence.count,
      lines: [...summary.pending_evidence.by_currency].sort(byCurrency).map((row) => ({
        currency: row.currency,
        label: evidenceLabel(row.event_type),
        count: formatCount(row.count),
        amount: formatMoney(row.amount, row.currency),
      })),
    },
    otherCurrencies: summary.non_aggregable_currencies.map((row) => row.currency).sort(),
  };
}

export interface KpiText {
  value: string;
  caption: string;
  /** El valor es «Sin datos»: la pantalla lo enseña sin acento de cifra. */
  isNoData: boolean;
}

export interface RevenueKpis {
  verified: KpiText;
  underReview: KpiText;
  pending: KpiText;
}

const othersText = (currencies: string[]) =>
  currencies.length === 0 ? "" : ` Hay entradas en ${currencies.join(", ")}: se enseñan aparte, no se suman ni se convierten.`;

/** Las tres cifras de cabecera. EUR es lo único consolidado; sin entradas en EUR el valor es «Sin datos», no 0,00 €. */
export function revenueKpis(summary: RevenueSummary): RevenueKpis {
  const view = summaryView(summary);
  const others = view.otherCurrencies;
  const verified: KpiText = view.eur
    ? {
        value: view.eur.revenue,
        caption: `Reembolsos ${view.eur.refunds} · Neto ${view.eur.net}.${othersText(others)}`,
        isNoData: false,
      }
    : {
        value: NO_DATA,
        caption: `Ninguna entrada en EUR en el periodo.${othersText(others)}`,
        isNoData: true,
      };
  const underReview: KpiText = view.eur
    ? {
        value: view.eur.underReview,
        caption: "Duplicados y discrepancias pendientes de resolver. No suman a lo verificado.",
        isNoData: false,
      }
    : { value: NO_DATA, caption: "Ninguna entrada en EUR en el periodo. No suma a lo verificado.", isNoData: true };
  const evidence = view.pendingEvidence;
  const pending: KpiText = {
    value: formatCount(evidence.count),
    caption:
      evidence.count === 0
        ? "Ningún evento de pago sin asentar."
        : `Eventos de pago sin asentar (${evidence.lines.map((line) => `${line.amount}`).join(" · ")}). No son ingreso ni reembolso.`,
    isNoData: false,
  };
  return { verified, underReview, pending };
}

// --- Serie por día ------------------------------------------------------------------------------------------------

export interface SeriesColumn {
  /** Índice del día dentro de la ventana (0 = el primero). */
  x: number;
  at: number;
  label: string;
  /** Solo para dibujar la barra: el importe exacto es `revenueText`. */
  plot: number;
  revenueText: string;
}

export interface SeriesRow {
  bucket: string;
  revenue: string;
  refunds: string;
  net: string;
  underReviewReceived: string;
  underReviewRefunded: string;
  entries: string;
}

export interface CurrencySeries {
  currency: string;
  columns: SeriesColumn[];
  /** De más reciente a más antiguo. */
  rows: SeriesRow[];
}

export interface SeriesView {
  currencies: string[];
  byCurrency: Record<string, CurrencySeries>;
  /** Días de la ventana. Los que no tienen cubo no tienen barra: sin datos, no cero. */
  windowDays: number;
}

const DAY_BUCKET = /^\d{4}-\d{2}-\d{2}$/;

export function dayLabel(at: number): string {
  return new Date(at).toLocaleDateString("es-ES", { day: "numeric", month: "short", timeZone: "UTC" });
}

export function seriesView(series: RevenueSeries, windowFrom: string, windowTo: string): SeriesView {
  const from = Date.parse(windowFrom);
  const windowDays = Math.max(1, Math.round((Date.parse(windowTo) - from) / DAY_MS));
  const grouped = new Map<string, CurrencySeries>();
  for (const bucket of series.buckets) {
    if (!DAY_BUCKET.test(bucket.bucket)) continue;
    const at = Date.parse(`${bucket.bucket}T00:00:00Z`);
    const x = Math.round((at - from) / DAY_MS);
    if (x < 0 || x >= windowDays) continue;
    const current = grouped.get(bucket.currency) ?? { currency: bucket.currency, columns: [], rows: [] };
    current.columns.push({
      x,
      at,
      label: dayLabel(at),
      plot: Math.max(0, Number(bucket.revenue)),
      revenueText: formatMoney(bucket.revenue, bucket.currency),
    });
    current.rows.push({
      bucket: bucket.bucket,
      revenue: formatMoney(bucket.revenue, bucket.currency),
      refunds: formatMoney(bucket.refunds, bucket.currency),
      net: formatMoney(bucket.net, bucket.currency),
      underReviewReceived: formatMoney(bucket.under_review_received, bucket.currency),
      underReviewRefunded: formatMoney(bucket.under_review_refunded, bucket.currency),
      entries: formatCount(bucket.entries),
    });
    grouped.set(bucket.currency, current);
  }
  const all = [...grouped.values()].sort(byCurrency);
  for (const entry of all) {
    entry.columns.sort((a, b) => a.x - b.x);
    entry.rows.sort((a, b) => b.bucket.localeCompare(a.bucket));
  }
  return {
    currencies: all.map((entry) => entry.currency),
    byCurrency: Object.fromEntries(all.map((entry) => [entry.currency, entry])),
    windowDays,
  };
}

// --- Entradas explicativas, por cursor ----------------------------------------------------------------------------

export interface EntryRow {
  id: string;
  kind: string;
  kindLabel: string;
  classification: string;
  classificationLabel: string;
  verified: boolean;
  amount: string;
  orderId: string;
  occurredAt: string;
}

export function entryRow(entry: RevenueEntry): EntryRow {
  return {
    id: entry.id,
    kind: entry.kind,
    kindLabel: kindLabel(entry.kind),
    classification: entry.classification,
    classificationLabel: classificationLabel(entry.classification),
    verified: isVerified(entry.classification),
    amount: formatMoney(entry.amount, entry.currency),
    orderId: entry.order_id,
    occurredAt: entry.occurred_at,
  };
}

/** Lo cargado hasta ahora y si el backend dice que hay más. Nunca se toma una página por el total. */
export interface EntriesLoaded {
  items: RevenueEntry[];
  hasMore: boolean;
  nextCursor: string | null;
}

export function entriesFromPage(page: RevenueEntriesPage): EntriesLoaded {
  return { items: page.items, hasMore: page.has_more, nextCursor: page.next_cursor };
}

/** Añade la página siguiente sin repetir ninguna entrada (por `id`) y conserva el orden del backend. */
export function appendEntries(current: EntriesLoaded, page: RevenueEntriesPage): EntriesLoaded {
  const seen = new Set(current.items.map((item) => item.id));
  return {
    items: [...current.items, ...page.items.filter((item) => !seen.has(item.id))],
    hasMore: page.has_more,
    nextCursor: page.next_cursor,
  };
}

export function entriesSummaryText(loaded: EntriesLoaded): string {
  const count = loaded.items.length;
  if (count === 0) return loaded.hasMore ? "Ninguna entrada cargada todavía." : "No hay entradas en este periodo.";
  const noun = count === 1 ? "entrada cargada" : "entradas cargadas";
  return loaded.hasMore
    ? `${formatCount(count)} ${noun}; hay más antiguas sin cargar.`
    : `${formatCount(count)} ${noun}: son todas las del periodo.`;
}
