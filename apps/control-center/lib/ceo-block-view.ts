import type { BlockState } from "./ceo-blocks.ts";
import { worstOf, type ReadState } from "./read-state.ts";

// La MECÁNICA común de los tres bloques ejecutivos del Director ejecutivo (M47, Commit 3B): tipos de la vista, composición de lecturas,
// «tres visibles y N más» y el formato de fecha. Aquí NO hay ninguna regla de significado: qué es una decisión pendiente, un candidato o una
// incidencia lo decide cada bloque en su propio módulo (`ceo-decisions`, `ceo-opportunities`, `ceo-risks`). Compartir significado fue lo
// que, en los ingresos, produjo dos semánticas para un mismo dato (Commit 3A.1).

/** Cuántas filas enseña cada tarjeta; el resto se dice con «N más» y se ve en la pantalla de «Ver todas». */
export const VISIBLE_ROWS = 3;

/** La insignia visible de los tres bloques. «Verificado» queda reservado a los hechos contables y de pago. */
export const RECORDED_LABEL = "Registrado";
export const RECORDED_MEANING =
  "Dato que el backend guarda tal cual: lo que el sistema registró, no una comprobación contra la fuente original. Que exista no lo hace verificado.";

/** La trazabilidad de una fila. Nada de esto tiene por qué verse: se puede comprobar en `data-*` y en las pruebas. */
export interface BlockProvenance {
  /** La tabla o el recurso del backend de donde sale. */
  source: string;
  /** La entidad que representa la fila. */
  entity: string;
  id: string | null;
  status: string;
  /** Una etiqueta del tipo de entidad u origen; nunca un solicitante inventado. */
  areaLabel: string;
  /** La marca de tiempo REAL que trae el dato (ISO), o `null` si el backend no la expone. */
  at: string | null;
  /** Ninguna de las fuentes de estos bloques trae confianza en su lista: siempre `null`, nunca un 0. */
  confidence: null;
  rationale: string | null;
}

export interface BlockRow {
  key: string;
  title: string;
  subtitle: string;
  /** La etiqueta de la fila. `level` solo existe cuando el backend da una severidad real. */
  tag: { text: string; level?: "low" | "medium" | "high" | "critical" };
  /** Líneas de detalle para el tooltip (motivos reales, descripción…). */
  detail: string[];
  provenance: BlockProvenance;
}

/** Una franja aparte de estado, que NO es una fila ni suma al contador. */
export interface BlockStrip {
  text: string;
  detail: string | null;
  provenance: BlockProvenance;
}

export type BlockView =
  | {
      kind: "loaded";
      count: number;
      /** El texto corto del contador de la cabecera y su nombre accesible. */
      countText: string;
      countLabel: string;
      rows: BlockRow[];
      visible: BlockRow[];
      /** Filas que no caben en las tres visibles. */
      more: number;
      /** Lo que se dice cuando hay lectura válida pero ninguna fila que contar. */
      noRowsText: string | null;
      /** Lo que queda fuera del contador, dicho aparte y con recuentos reales. */
      secondary: string[];
      strip: BlockStrip | null;
      footnote: string | null;
    }
  | { kind: "empty"; text: string; footnote: string | null }
  | { kind: "error"; message: string }
  | { kind: "unread"; reason: string };

export interface LoadedInput {
  rows: BlockRow[];
  countText: string;
  countLabel: string;
  noRowsText?: string | null;
  secondary?: string[];
  strip?: BlockStrip | null;
  footnote?: string | null;
}

/** Una vista cargada: las tres primeras filas y cuántas quedan fuera. El contador es el de las filas, no el de lo secundario. */
export function loadedView(input: LoadedInput): BlockView {
  return {
    kind: "loaded",
    count: input.rows.length,
    countText: input.countText,
    countLabel: input.countLabel,
    rows: input.rows,
    visible: input.rows.slice(0, VISIBLE_ROWS),
    more: Math.max(0, input.rows.length - VISIBLE_ROWS),
    noRowsText: input.noRowsText ?? null,
    secondary: input.secondary ?? [],
    strip: input.strip ?? null,
    footnote: input.footnote ?? null,
  };
}

export const emptyView = (text: string, footnote: string | null = null): BlockView => ({ kind: "empty", text, footnote });

/** Si alguna de las lecturas de un bloque falló o no se hizo, el bloque entero lo dice: no hay datos parciales presentados como completos.
 * `error` gana a `unread`. Devuelve `null` si todas las lecturas son válidas. */
export function unusable(states: ReadonlyArray<ReadState<unknown>>): BlockView | null {
  const worst = worstOf(states);
  if (worst === "error") {
    const messages = states.flatMap((state) => (state.kind === "error" ? [state.message] : []));
    return { kind: "error", message: [...new Set(messages)].join(" ") };
  }
  if (worst === "unread") {
    const reasons = states.flatMap((state) => (state.kind === "unread" ? [state.reason] : []));
    return { kind: "unread", reason: [...new Set(reasons)].join(" ") };
  }
  return null;
}

/** El estado que entiende `BlockCard`. `loaded` y `empty` no llevan nada: el contenido lo pinta la vista. */
export function blockStateOf(view: BlockView): BlockState<unknown> {
  switch (view.kind) {
    case "loaded":
      return { kind: "loaded", data: view };
    case "empty":
      return { kind: "empty" };
    case "error":
      return { kind: "error", message: view.message };
    case "unread":
      return { kind: "unread", reason: view.reason };
  }
}

const MONTHS = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"] as const;
const two = (value: number) => String(value).padStart(2, "0");

/** «16 oct 2026 · 14:05 UTC»: siempre en UTC y escrito a mano, sin `Intl` ni la zona del navegador, para que el servidor y el cliente
 * pinten exactamente lo mismo. */
export function formatUtcDateTime(ms: number): string {
  const date = new Date(ms);
  return `${date.getUTCDate()} ${MONTHS[date.getUTCMonth()]} ${date.getUTCFullYear()} · ${two(date.getUTCHours())}:${two(date.getUTCMinutes())} UTC`;
}

/** El mismo contador en singular y plural. */
export const plural = (count: number, one: string, many: string) => (count === 1 ? one : many);

/** Cuántos de un total no caben en las tres visibles, dicho en una línea. */
export const moreText = (more: number) => `y ${more} más`;
