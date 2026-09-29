import type { SupplierProvenance } from "./api.ts";

/** La lógica del alta manual de un tipo de cambio (Milestone 40, ADR 0018).
 *
 * Vive aquí y no en el componente porque es la regla del proyecto y porque es
 * lo que hay que poder probar. Lo que esta capa protege es una sola cosa, y es
 * la que más cara sale: **que la dirección del par no se pueda confundir**. Un
 * 1,08 puede ser dólares por euro o euros por dólar, y entre las dos lecturas
 * hay un 16 % que nadie ve hasta que llega a un margen.
 */

export interface ExchangeRateForm {
  baseCurrency: string;
  quoteCurrency: string;
  rate: string;
  effectiveDate: string;
  provenance: SupplierProvenance;
  declaredBy: string;
  note: string;
}

export const EMPTY_RATE: ExchangeRateForm = {
  baseCurrency: "USD",
  quoteCurrency: "EUR",
  rate: "",
  effectiveDate: "",
  // Lo normal es que lo escriba el operador: el cambio que aplicó el banco.
  provenance: "declared",
  declaredBy: "",
  note: "",
};

export interface RateProblem {
  field: keyof ExchangeRateForm;
  message: string;
}

/** Cómo se lee el par, en palabras. Se enseña junto al formulario para que
 * nadie tenga que deducir la dirección. */
export function pairSentence(form: ExchangeRateForm): string {
  const base = form.baseCurrency.trim().toUpperCase() || "???";
  const quote = form.quoteCurrency.trim().toUpperCase() || "???";
  const rate = form.rate.trim() || "…";
  return `1 ${base} = ${rate} ${quote}`;
}

/** Un número del formulario, o `null`. Acepta la coma decimal. */
export function numericRate(value: string): number | null {
  const trimmed = value.trim();
  if (trimmed === "") return null;
  const parsed = Number(trimmed.replace(",", "."));
  return Number.isFinite(parsed) ? parsed : null;
}

/** Lo que se puede comprobar antes de llamar al backend. Deliberadamente poco:
 * el catálogo de monedas vive allí y es él quien lo valida; duplicarlo aquí
 * crearía dos verdades que se separan. */
export function problems(form: ExchangeRateForm, today: string): RateProblem[] {
  const found: RateProblem[] = [];
  const base = form.baseCurrency.trim().toUpperCase();
  const quote = form.quoteCurrency.trim().toUpperCase();
  const rate = numericRate(form.rate);

  if (!base) found.push({ field: "baseCurrency", message: "Falta la moneda de origen." });
  if (!quote) found.push({ field: "quoteCurrency", message: "Falta la moneda de destino." });
  if (base && quote && base === quote) {
    found.push({
      field: "quoteCurrency",
      message: "Un cambio entre una moneda y ella misma no es un cambio.",
    });
  }
  if (rate === null) {
    found.push({ field: "rate", message: "Falta la tasa." });
  } else if (rate <= 0) {
    found.push({ field: "rate", message: "Una tasa tiene que ser positiva." });
  }
  if (!form.effectiveDate.trim()) {
    found.push({ field: "effectiveDate", message: "Falta la fecha de vigencia." });
  } else if (form.effectiveDate > today) {
    found.push({
      field: "effectiveDate",
      message: "Una tasa del futuro no vale: sería leer la respuesta antes del examen.",
    });
  }
  if (form.provenance === "third_party_verified" && !form.declaredBy.trim()) {
    found.push({
      field: "declaredBy",
      message: "«Verificado por un tercero» exige decir quién lo emite.",
    });
  }
  return found;
}

export function ratePayload(form: ExchangeRateForm) {
  return {
    base_currency: form.baseCurrency.trim().toUpperCase(),
    quote_currency: form.quoteCurrency.trim().toUpperCase(),
    rate: form.rate.trim().replace(",", "."),
    effective_date: form.effectiveDate,
    provenance: form.provenance,
    declared_by: form.declaredBy.trim() || null,
    note: form.note.trim() || null,
  };
}
