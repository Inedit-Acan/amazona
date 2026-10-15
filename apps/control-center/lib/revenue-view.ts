import type {
  RevenueEntriesPage,
  RevenueEntry,
  RevenueProviderKind,
  RevenueSeries,
  RevenueSummary,
} from "./api.ts";
import { RevenueContractError } from "./revenue-contract.ts";
import { classificationLabel, formatCount, formatMoney } from "./revenue-format.ts";
import { revenueFigures, summaryFigures, type FigureLine, type FigureSecondary, type RevenueFigures } from "./revenue-figures.ts";

// Vista de los ingresos del Panel y de Finanzas (M45, ADR 0030). Aquí NO se calcula nada económico: el backend ya devolvió cada cifra por moneda,
// separando lo verificado, lo que está en revisión y la evidencia pendiente. Este módulo solo decide QUÉ SE ENSEÑA y CÓMO SE DICE, y desde
// M47 · Commit 3A.1 NO conserva ninguna segunda implementación de la semántica: todo lo que lee de `GET /api/revenue/summary` pasa por
// `lib/revenue-figures.ts` (el núcleo que comparten `/ceo`, `/dashboard` y `/cfo`). Las reglas, que las pruebas fijan:
//
//   1. «Sin datos» no es un cero. Sin ninguna fila verificada se dice «Sin datos»; un cero solo sale cuando el backend lo midió (hay una fila).
//   2. Las monedas no se suman ni se convierten. Cada pareja origen × moneda sale en su línea; una moneda distinta de EUR NO se oculta.
//   3. Lo verificado, lo que está en revisión y la evidencia pendiente son tres cosas distintas: ninguna cifra de una se construye con las otras,
//      y esta vista no hace ninguna suma de importes.
//   4. (M46, ADR 0031) Cada cifra es de UN origen (`provider_kind`), tal como lo guardó el backend. Nunca se suman orígenes distintos. Un
//      origen ausente o desconocido no se completa jamás: ver `revenue-contract.ts`.
//
// No importa nada de `lib/demo` ni del P&L modelado (`cfo-view`, `operations-view`): lo que hay aquí es medido.

export const NO_DATA = "Sin datos";

/** Lo que se dice cuando una lectura FALLÓ. No es «Sin datos» (el backend no lo tiene): es «no sé si lo tiene». Un error
 * de lectura no es un dato, y no se convierte en una lista vacía ni en un cero. */
export const UNREAD = "No se pudo leer";
const DAY_MS = 86_400_000;

// Las primitivas de texto (importes exactos, recuentos y etiquetas de clase) viven en `lib/revenue-format.ts` desde M47 · Commit 3A.1, y se
// reexportan aquí con los mismos nombres: ningún import existente cambia.
export { classificationLabel, evidenceLabel, formatCount, formatMoney } from "./revenue-format.ts";

// --- Etiquetas ----------------------------------------------------------------------------------------------------

const KIND_LABEL: Record<string, string> = { CAPTURE: "Cobro", REFUND: "Reembolso" };

export const kindLabel = (value: string) => KIND_LABEL[value] ?? value;

/** Solo `ORDER_PAYMENT` es ingreso verificado; todo lo demás está en revisión. */
export const isVerified = (classification: string) => classification === "ORDER_PAYMENT";

export const REVENUE_SCOPE_NOTE =
  "Cifras tomadas del registro de hechos de pago verificados; no son un modelo ni contabilidad: no incluyen costes, margen, " +
  "beneficio, impuestos, IVA/OSS, caja, comisiones ni conversión de divisas. Cada cifra es de un origen (provider_kind), " +
  "tal como lo guardó el backend: nunca se suman orígenes distintos, y un hecho verificado no es dinero liquidado.";

export function periodLabel(days: number): string {
  return `últimos ${days} días`;
}

// --- Resultado de una lectura: dato o error visible ---------------------------------------------------------------

/** Lo que devuelve cada lectura del Panel. Un error se enseña como error; NUNCA se sustituye por datos de demostración. */
export type Settled<T> = { ok: true; data: T } | { ok: false; message: string };

/** Texto de un error de lectura de ingresos. **No repite el estado HTTP ni el detalle del backend** (M46, Commit 6): al
 * usuario no se le enseña `500`, `ECONNREFUSED` ni un cuerpo de error, sino qué no se pudo hacer. Por eso solo recibe el
 * estado, que decide QUÉ se dice y no se escribe. */
export function revenueErrorText(status: number | undefined): string {
  if (status === 401) return "La sesión no es válida o ha caducado. Vuelve a iniciar sesión.";
  if (status === 403) return "Tu usuario no tiene permiso para leer los ingresos (business.read).";
  if (status === 422) return "El backend rechazó la petición de ingresos.";
  if (status !== undefined && status >= 500) return "Los ingresos no están disponibles en este momento.";
  return "No se pudieron cargar los ingresos.";
}

/** Cómo se convierte un fallo de lectura en el texto que ve el usuario. */
export type DescribeReadError = (status: number | undefined, detail: string) => string;

/** Ejecuta una lectura y devuelve el dato o el error. Reconoce un `ApiError` por su forma (`status`, `detail`) para no
 * depender de `lib/api.ts`, que arrastra el resolutor de token. `describe` da el texto del error; por defecto el de los
 * ingresos (M45). */
export async function settle<T>(read: () => Promise<T>, describe: DescribeReadError = revenueErrorText): Promise<Settled<T>> {
  try {
    return { ok: true, data: await read() };
  } catch (err) {
    // El error de contrato es texto NUESTRO, escrito para verse («El contrato de ingresos cambió: …»): es el aviso de que
    // el backend y la pantalla ya no se entienden, y no se esconde detrás de un mensaje genérico.
    if (err instanceof RevenueContractError) return { ok: false, message: err.message };
    const status = err !== null && typeof err === "object" && "status" in err && typeof err.status === "number" ? err.status : undefined;
    const detail =
      err !== null && typeof err === "object" && "detail" in err && typeof err.detail === "string"
        ? err.detail
        : err instanceof Error
          ? err.message
          : "error desconocido";
    return { ok: false, message: describe(status, detail) };
  }
}

// --- Resumen ------------------------------------------------------------------------------------------------------

export interface VerifiedLine {
  providerKind: RevenueProviderKind;
  currency: string;
  revenue: string;
  refunds: string;
  net: string;
  captures: string;
  refundCount: string;
}

export interface UnderReviewLine {
  providerKind: RevenueProviderKind;
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
  providerKind: RevenueProviderKind;
  currency: string;
  label: string;
  count: string;
  amount: string;
}

export interface SummaryView {
  /** Hay algo que enseñar: alguna entrada del registro o algún evento sin asentar. */
  hasAnyData: boolean;
  /** Orígenes con algún dato (entradas), en el orden del backend. */
  origins: RevenueProviderKind[];
  verified: VerifiedLine[];
  underReview: UnderReviewLine[];
  pendingEvidence: { count: number; lines: EvidenceLine[] };
  /** Monedas declaradas sin conversión: informativo, no oculta ninguna. Salen por separado y nunca se suman ni se convierten. */
  otherCurrencies: string[];
}

/** Las TABLAS de `/dashboard` y `/cfo`. Es un adaptador de presentación (recuentos con separador de miles): todas las filas, su orden y su
 * formato salen de `lib/revenue-figures.ts`, el mismo núcleo que las tarjetas; aquí no se ordena, no se agrega ni se decide nada. */
export function summaryView(summary: RevenueSummary): SummaryView {
  const figures = summaryFigures(summary);
  return {
    hasAnyData: figures.hasAnyData,
    origins: figures.origins,
    verified: figures.verified.map((line) => ({
      providerKind: line.providerKind,
      currency: line.currency,
      revenue: line.revenue,
      refunds: line.refunds,
      net: line.net,
      captures: formatCount(line.captures),
      refundCount: formatCount(line.refundCount),
    })),
    underReview: figures.underReview.map((row) => ({
      providerKind: row.providerKind,
      currency: row.currency,
      classification: row.classification,
      label: row.label,
      received: row.received,
      refunded: row.refunded,
      outstanding: row.amount,
      receipts: formatCount(row.receipts),
      refundCount: formatCount(row.refundCount),
    })),
    pendingEvidence: {
      count: figures.pending.count,
      lines: figures.pending.lines.map((line) => ({
        providerKind: line.providerKind,
        currency: line.currency,
        label: line.label,
        count: formatCount(line.count),
        amount: line.amount,
      })),
    },
    otherCurrencies: figures.nonAggregable,
  };
}

/** Los destinos del enlace «ver el detalle» de las tarjetas compactas: las tablas de la MISMA página que enseñan todas las filas. */
export const VERIFIED_TABLE_ID = "ingresos-por-moneda";
export const OUTSIDE_TABLE_ID = "fuera-de-lo-verificado";

export interface KpiText {
  value: string;
  caption: string;
  /** El valor es «Sin datos», o no hay una sola cifra: la pantalla lo enseña sin acento de cifra. */
  isNoData: boolean;
  /** Hay varias cifras (origen × moneda): la tarjeta es compacta y el detalle completo está en la tabla de la misma página. */
  detail?: boolean;
}

export type RevenueKpisResult =
  | { kind: "error"; message: string }
  | { kind: "ok"; verified: KpiText; underReview: KpiText; pending: KpiText };

export type VerifiedMetric = "revenue" | "refunds" | "net";

export type VerifiedKpisResult =
  | { kind: "error"; message: string }
  | { kind: "ok"; revenue: KpiText; refunds: KpiText; net: KpiText };

const plural = (count: number, one: string, many: string) => (count === 1 ? one : many);

/** Lo que dice una tarjeta compacta cuando hay varias cifras (la etiqueta de la tarjeta ya dice «verificados»): ninguna se elige como total, ninguna se
 * pierde y el detalle está en la tabla de la misma página. El valor es solo el recuento («4 cifras»). */
const COMPACT_CAPTION = "Verificadas, por origen y moneda: sin sumar ni convertir.";
const COMPACT_REVIEW_CAPTION = "Por origen, moneda y clase: sin sumar ni convertir. No suman a lo verificado.";

const notesText = (secondary: FigureSecondary): string => (secondary.notes.length === 0 ? "" : ` ${secondary.notes.join(" · ")}.`);

/** UNA métrica verificada (ingresos, reembolsos o neto) a partir de las líneas del núcleo. Sin ninguna línea: «Sin datos». Una línea: su cifra.
 * Varias: «N cifras» y ninguna cifra elegida; el detalle está en la tabla de la misma página. */
function verifiedKpi(
  figures: Exclude<RevenueFigures, { kind: "error" }>,
  metric: VerifiedMetric,
  singleCaption: (line: FigureLine) => string,
  emptyCaption: string,
): KpiText {
  const notes = notesText(figures.secondary);
  if (figures.kind === "empty") return { value: NO_DATA, caption: `${emptyCaption}${notes}`, isNoData: true };
  if (figures.lines.length === 1) {
    const [line] = figures.lines;
    return { value: line[metric], caption: `${singleCaption(line)}${notes}`, isNoData: false };
  }
  return {
    value: `${figures.lines.length} cifras`,
    caption: `${COMPACT_CAPTION}${notes}`,
    isNoData: true,
    detail: true,
  };
}

function reviewKpi(secondary: FigureSecondary): KpiText {
  const rows = secondary.underReview;
  if (rows.length === 0) return { value: NO_DATA, caption: "Nada en revisión en el periodo. No suma a lo verificado.", isNoData: true };
  if (rows.length === 1) {
    const [row] = rows;
    return { value: row.amount, caption: `${row.label} · Origen: ${row.origin}. No suma a lo verificado.`, isNoData: false };
  }
  return {
    value: `${rows.length} partidas`,
    caption: COMPACT_REVIEW_CAPTION,
    isNoData: true,
    detail: true,
  };
}

/** El recuento es un recuento de EVENTOS (no dinero): cero es un cero verdadero. Cada línea conserva su clase, origen, moneda, recuento e
 * importe; dos orígenes o dos monedas nunca se funden en una cifra. */
function pendingKpi(secondary: FigureSecondary): KpiText {
  const value = formatCount(secondary.pendingCount);
  if (secondary.pendingCount === 0) return { value, caption: "Ningún evento de pago sin asentar.", isNoData: false };
  const lines = secondary.pending.map(
    (line) => `${line.label} · ${line.origin} · ${line.count} ${plural(line.count, "evento", "eventos")} · ${line.amount}`,
  );
  const listed = lines.length === 0 ? "Eventos de pago sin asentar" : lines.join("; ");
  return { value, caption: `${listed}. No son ingreso ni reembolso.`, isNoData: false };
}

/** Las tres cifras de cabecera del Panel. Salen del núcleo (`revenueFigures`): una línea por origen × moneda, nada se suma ni se convierte, y
 * sin ningún cobro verificado el valor es «Sin datos», nunca un cero fabricado. */
export function revenueKpis(summary: RevenueSummary): RevenueKpisResult {
  const figures = revenueFigures(summary);
  if (figures.kind === "error") return { kind: "error", message: figures.message };
  return {
    kind: "ok",
    verified: verifiedKpi(
      figures,
      "revenue",
      (line) => `Origen: ${line.origin}. Reembolsos ${line.refunds} · Neto ${line.net}.`,
      "Ningún ingreso verificado en el periodo.",
    ),
    underReview: reviewKpi(figures.secondary),
    pending: pendingKpi(figures.secondary),
  };
}

/** Las tres cifras verificadas de Finanzas (ingresos, reembolsos y neto), sobre LAS MISMAS líneas: coherentes entre sí por construcción. */
export function verifiedMetricKpis(summary: RevenueSummary): VerifiedKpisResult {
  const figures = revenueFigures(summary);
  if (figures.kind === "error") return { kind: "error", message: figures.message };
  const none = "Ningún ingreso verificado en el periodo.";
  return {
    kind: "ok",
    revenue: verifiedKpi(figures, "revenue", (line) => `Cobros verificados. Origen: ${line.origin}.`, none),
    refunds: verifiedKpi(figures, "refunds", (line) => `Devoluciones confirmadas. Origen: ${line.origin}.`, none),
    net: verifiedKpi(figures, "net", (line) => `Ingresos menos reembolsos, tal como los da el backend. Origen: ${line.origin}.`, none),
  };
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
  /** `<origen>·<moneda>`: una serie es de UN origen y UNA moneda, nunca de dos. */
  key: string;
  providerKind: RevenueProviderKind;
  currency: string;
  columns: SeriesColumn[];
  /** De más reciente a más antiguo. */
  rows: SeriesRow[];
}

export interface SeriesView {
  /** Las series que hay, por origen y moneda (EUR primero dentro de cada origen). */
  keys: string[];
  bySeries: Record<string, CurrencySeries>;
  /** Días de la ventana. Los que no tienen cubo no tienen barra: sin datos, no cero. */
  windowDays: number;
}

/** El orden de las SERIES por día (`/api/revenue/series`, otro endpoint): EUR primero dentro de cada origen. No es el de `verified[]`. */
const byCurrency = <T extends { currency: string }>(a: T, b: T) => {
  const rank = (currency: string) => (currency === "EUR" ? 0 : 1);
  return rank(a.currency) - rank(b.currency) || a.currency.localeCompare(b.currency);
};

const DAY_BUCKET =/^\d{4}-\d{2}-\d{2}$/;

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
    const key = `${bucket.provider_kind}·${bucket.currency}`;
    const current = grouped.get(key) ?? {
      key,
      providerKind: bucket.provider_kind,
      currency: bucket.currency,
      columns: [],
      rows: [],
    };
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
    grouped.set(key, current);
  }
  const all = [...grouped.values()].sort((a, b) => a.providerKind.localeCompare(b.providerKind) || byCurrency(a, b));
  for (const entry of all) {
    entry.columns.sort((a, b) => a.x - b.x);
    entry.rows.sort((a, b) => b.bucket.localeCompare(a.bucket));
  }
  return {
    keys: all.map((entry) => entry.key),
    bySeries: Object.fromEntries(all.map((entry) => [entry.key, entry])),
    windowDays,
  };
}

// --- Entradas explicativas, por cursor ----------------------------------------------------------------------------

export interface EntryRow {
  id: string;
  providerKind: RevenueProviderKind;
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
    providerKind: entry.provider_kind,
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
