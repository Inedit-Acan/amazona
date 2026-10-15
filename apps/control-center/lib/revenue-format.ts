import type { DecimalText } from "./api.ts";

// Las primitivas de TEXTO de los ingresos (M45, ADR 0030), movidas tal cual desde `lib/revenue-view.ts` (M47, Commit 3A.1) para que el núcleo
// `lib/revenue-figures.ts` y la vista `lib/revenue-view.ts` las compartan sin un ciclo de importación. `revenue-view.ts` las reexporta con los
// mismos nombres: ningún import existente cambia. Aquí no hay semántica de negocio, solo cómo se escribe un importe, un recuento y una clase.

const CONSOLIDATION_CURRENCY = "EUR";

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

const EVIDENCE_LABEL: Record<string, string> = {
  "payment.succeeded": "Cobro sin asentar",
  "refund.succeeded": "Reembolso sin asentar",
};

export const classificationLabel = (value: string) => CLASSIFICATION_LABEL[value] ?? value;
export const evidenceLabel = (value: string) => EVIDENCE_LABEL[value] ?? value;
