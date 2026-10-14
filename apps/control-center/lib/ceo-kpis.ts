import type { RevenueSummary } from "./api.ts";
import { unavailableState, type UnavailableState } from "./ceo-blocks.ts";
import { originName } from "./provenance.ts";
import { RevenueContractError } from "./revenue-contract.ts";
import type { RevenueWindow } from "./revenue-query.ts";
import { classificationLabel, evidenceLabel, formatMoney, periodLabel, settle, type Settled } from "./revenue-view.ts";

// Los KPI del Director ejecutivo (M47, Commit 3A).
//
// INGRESOS. La unidad de presentación es la pareja ORIGEN × MONEDA (`provider_kind` × `currency`): dos dimensiones distintas, ninguna
// se pierde ni se funde con la otra. Las cifras salen de `verified[]` (una fila por origen y moneda, con `revenue`, `refunds` y `net`
// tal cual los calcula el backend: aquí no se recalcula nada y no hay `float`, todo es texto decimal hasta el formateo). Nunca de
// `consolidated_eur_by_origin`: ese bloque solo existe si hay EUR, y además se emite cuando EUR solo está en revisión —entonces trae
// `revenue: "0.0000"` sin ningún cobro verificado—, así que usarlo fabricaría un cero.
//
//   · `non_aggregable_currencies[]` son las monedas que NO se integran en un total EUR (no hay FX). No significa ocultarlas: sus
//     importes están en `verified[]`. Una moneda que solo está ahí (sin ningún importe verificado) sale como una nota, no como ingreso.
//   · Ninguna suma entre monedas ni entre orígenes (ADR 0030 L6, ADR 0031 A1): no existe ese total.
//   · `under_review` y `pending_evidence` nunca entran en la cifra: solo información secundaria, etiquetada «Fuera de esta cifra».
//   · `verified[]` vacío ⇒ `empty` («Sin datos»), también si hay dinero en revisión o pendiente (eso es secundario). Una lectura
//     fallida o un contrato roto ⇒ `error`, jamás `empty`. `unread` no existe aquí: este bloque siempre intenta leer.

/** Lo que dice la sección secundaria: lo que NO forma parte de la cifra de Ingresos. */
export const OUTSIDE_FIGURE_TEXT = "Fuera de esta cifra (no es ingreso verificado)";

/** Qué demuestra y qué no la tarjeta de Ingresos. */
export const INGRESOS_NOT_SETTLED_NOTE = "Un hecho verificado no es dinero liquidado.";
/** Solo se dice cuando hay más de una línea: con una sola no hay nada que sumar. */
export const INGRESOS_NO_SUM_NOTE = "Orígenes y monedas no se suman ni se convierten.";

export interface IngresosLine {
  /** `<moneda>·<origen>`: una línea es de UN origen y UNA moneda, nunca de dos. */
  key: string;
  providerKind: string;
  /** El origen tal como se llama en pantalla (Simulado, Entorno de pruebas, Proveedor real). */
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

export interface UnderReviewLine {
  key: string;
  currency: string;
  origin: string;
  label: string;
  /** Lo pendiente de resolver (`outstanding`, tal cual lo da el backend). */
  amount: string;
}

export interface PendingLine {
  key: string;
  currency: string;
  origin: string;
  label: string;
  count: number;
  amount: string;
}

export interface IngresosSecondary {
  underReview: UnderReviewLine[];
  /** Un recuento de eventos (no dinero). */
  pendingCount: number;
  pending: PendingLine[];
  /** Monedas sin conversión contable que no tienen ningún importe verificado: se dicen, no se inventan. */
  notes: string[];
}

export type IngresosView =
  | { kind: "error"; message: string }
  | { kind: "empty"; periodText: string; secondary: IngresosSecondary }
  | { kind: "loaded"; periodText: string; lines: IngresosLine[]; secondary: IngresosSecondary };

/** Altura de la tarjeta de Ingresos (M47, 3A): el máximo que se acepta en desktop en estado normal, y el alto del área de líneas con
 * scroll (en `rem`; `components/ceo/revenue-kpi.tsx` lleva la clase literal `max-h-[6rem]` y una prueba la ata a este número). Con
 * más líneas de las que caben, las líneas hacen scroll y el desglose completo está en «Ver desglose»: nada se oculta. */
export const INGRESOS_CARD_MAX_PX = 300;
export const INGRESOS_LINES_MAX_REM = 6;

/** El resumen compacto de lo que queda fuera de la cifra, con recuentos reales y sin sumar importes ni monedas; `null` si no hay nada. */
export function secondarySummary(secondary: IngresosSecondary): string | null {
  const parts: string[] = [];
  if (secondary.underReview.length > 0) parts.push(`${secondary.underReview.length} en revisión`);
  if (secondary.pendingCount > 0) parts.push(`${secondary.pendingCount} sin asentar`);
  else if (secondary.pending.length > 0) parts.push(`${secondary.pending.length} pendientes`);
  if (secondary.notes.length > 0) parts.push(`${secondary.notes.length} sin conversión`);
  return parts.length === 0 ? null : `Fuera de esta cifra: ${parts.join(" · ")}`;
}

/** Cuántas cifras hay cuando son varias (origen × moneda): se dice, para que el scroll no esconda que hay más. */
export const linesCountText = (count: number): string => `${count} cifras · origen × moneda`;

export const hasSecondary = (secondary: IngresosSecondary): boolean =>
  secondary.underReview.length > 0 || secondary.pendingCount > 0 || secondary.pending.length > 0 || secondary.notes.length > 0;

const compare = (a: string, b: string) => (a < b ? -1 : a > b ? 1 : 0);
const currencyRank = (currency: string) => (currency === "EUR" ? 0 : 1);

/** Orden determinista, independiente del de la respuesta: EUR primero, luego las demás monedas por código y, dentro de cada moneda, el
 * origen por su valor guardado (`mock`, `real`, `sandbox`). */
const byCurrencyThenOrigin = (
  a: { currency: string; provider_kind: string; classification?: string },
  b: { currency: string; provider_kind: string; classification?: string },
) =>
  currencyRank(a.currency) - currencyRank(b.currency) ||
  compare(a.currency, b.currency) ||
  compare(a.provider_kind, b.provider_kind) ||
  compare(a.classification ?? "", b.classification ?? "");

const isNegative = (amount: string) => /^-\d*\.?\d*[1-9]/.test(amount);

const contractError = (message: string): IngresosView => ({ kind: "error", message: new RevenueContractError(message).message });

export function ingresosView(settled: Settled<RevenueSummary>, days: number): IngresosView {
  if (!settled.ok) return { kind: "error", message: settled.message };
  const summary = settled.data;
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

  const lines: IngresosLine[] = [...summary.verified].sort(byCurrencyThenOrigin).map((row) => ({
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

  const withLine = new Set(summary.verified.map((row) => row.currency));
  const secondary: IngresosSecondary = {
    underReview: [...summary.under_review].sort(byCurrencyThenOrigin).map((row) => ({
      key: `${row.currency}·${row.provider_kind}·${row.classification}`,
      currency: row.currency,
      origin: originName(row.provider_kind),
      label: classificationLabel(row.classification),
      amount: formatMoney(row.outstanding, row.currency),
    })),
    pendingCount: summary.pending_evidence.count,
    pending: [...summary.pending_evidence.by_currency].sort(byCurrencyThenOrigin).map((row) => ({
      key: `${row.currency}·${row.provider_kind}·${row.event_type}`,
      currency: row.currency,
      origin: originName(row.provider_kind),
      label: evidenceLabel(row.event_type),
      count: row.count,
      amount: formatMoney(row.amount, row.currency),
    })),
    notes: [...new Set(summary.non_aggregable_currencies.map((row) => row.currency))]
      .filter((currency) => !withLine.has(currency))
      .sort((a, b) => currencyRank(a) - currencyRank(b) || compare(a, b))
      .map((currency) => `${currency}: sin conversión contable disponible`),
  };

  const periodText = `${periodLabel(days)} (UTC)`;
  return lines.length === 0 ? { kind: "empty", periodText, secondary } : { kind: "loaded", periodText, lines, secondary };
}

/** Lo que Ingresos necesita del cliente de la API. `api` lo cumple; las pruebas pasan dobles. */
export interface IngresosSource {
  revenueSummary(window?: RevenueWindow): Promise<RevenueSummary>;
}

/** UNA lectura (`GET /api/revenue/summary?from=&to=`) de la ventana elegida. Un fallo es `error`; nunca datos de otra ventana ni vacío. */
export async function readIngresos(source: IngresosSource, window: RevenueWindow, days: number): Promise<IngresosView> {
  return ingresosView(await settle(() => source.revenueSummary(window)), days);
}

// --- Los otros tres KPI: hoy no hay fuente ---------------------------------------------------------------------------------

export interface UnavailableKpi {
  key: "beneficio" | "margen" | "cash";
  label: string;
  state: UnavailableState;
  /** La frase corta que sale en la tarjeta; el motivo completo es `state.reason`. */
  caption: string;
  /** Un enlace solo donde tiene sentido, sin sugerir que la cifra ya exista. */
  link?: { href: string; label: string };
}

export const UNAVAILABLE_KPIS: UnavailableKpi[] = [
  {
    key: "beneficio",
    label: "Beneficio",
    state: unavailableState("Falta una fuente de costes completa: el backend no registra coste de ventas, envíos, comisiones ni impuestos."),
    caption: "Falta una fuente de costes completa.",
    link: { href: "/cfo", label: "Ver en Finanzas el margen de contribución declarado (no es el beneficio)" },
  },
  {
    key: "margen",
    label: "Margen neto",
    state: unavailableState("Depende del beneficio, que hoy no puede calcularse."),
    caption: "Depende del beneficio.",
  },
  {
    key: "cash",
    label: "Cash disponible",
    state: unavailableState("No hay fuente de caja: el backend no tiene cuentas ni conciliación."),
    caption: "No hay fuente de caja.",
  },
];
