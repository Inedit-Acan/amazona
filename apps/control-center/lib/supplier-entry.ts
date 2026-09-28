import type { SupplierProvenance, SupplyCapability } from "./api.ts";

/** La lógica del alta manual de un proveedor real (Milestone 39, ADR 0017).
 *
 * Vive aquí y no en el componente porque es la regla del proyecto y porque es
 * lo que hay que poder probar: **un campo vacío se envía como ausente, nunca
 * como cero**. Un formulario que manda `0` en el MOQ que nadie rellenó le
 * estaría diciendo al backend que el proveedor sirve pedidos de cero unidades.
 */

export interface SupplierEntryForm {
  name: string;
  country: string;
  city: string;
  website: string;
  verification: SupplierProvenance;
  verifiedBy: string;
  unitPrice: string;
  currency: string;
  moq: string;
  leadTimeDays: string;
  transitDays: string;
  incoterm: string;
  paymentTerms: string;
  destinationMarket: string;
  logisticsCostPerUnit: string;
  validUntil: string;
  capabilities: Partial<Record<SupplyCapability, boolean>>;
}

export const EMPTY_ENTRY: SupplierEntryForm = {
  name: "",
  country: "",
  city: "",
  website: "",
  // Lo que trae una persona de una negociación lo dice el proveedor. Subirlo a
  // «verificado por un tercero» exige nombrar al verificador, y el backend lo
  // rechaza si no.
  verification: "supplier_claim",
  verifiedBy: "",
  unitPrice: "",
  currency: "EUR",
  moq: "",
  leadTimeDays: "",
  transitDays: "",
  incoterm: "",
  paymentTerms: "",
  destinationMarket: "eu",
  logisticsCostPerUnit: "",
  validUntil: "",
  capabilities: {},
};

/** Un texto del formulario, o `null` si está vacío. Nunca la cadena vacía: el
 * backend distingue «no declarado» de «declarado en blanco», y nosotros
 * también. */
export function text(value: string): string | null {
  const trimmed = value.trim();
  return trimmed === "" ? null : trimmed;
}

/** Un número del formulario, o `null`. **Nunca cero por defecto.** */
export function numeric(value: string): number | null {
  const trimmed = value.trim();
  if (trimmed === "") return null;
  const parsed = Number(trimmed.replace(",", "."));
  return Number.isFinite(parsed) ? parsed : null;
}

export interface EntryProblem {
  field: keyof SupplierEntryForm;
  message: string;
}

/** Lo que se puede comprobar antes de llamar al backend. Deliberadamente poco:
 * el catálogo de Incoterms y el de monedas viven en el backend y son él quien
 * los valida, y duplicarlos aquí crearía dos verdades que se separan. */
export function problems(form: SupplierEntryForm): EntryProblem[] {
  const found: EntryProblem[] = [];
  if (text(form.name) === null) {
    found.push({ field: "name", message: "Un proveedor necesita un nombre." });
  }
  if (form.verification === "third_party_verified" && text(form.verifiedBy) === null) {
    found.push({
      field: "verifiedBy",
      message: "«Verificado por un tercero» exige decir quién verificó.",
    });
  }
  if (numeric(form.unitPrice) !== null && text(form.currency) === null) {
    found.push({
      field: "currency",
      message: "Un precio necesita moneda: sin ella no se compara con ningún otro.",
    });
  }
  return found;
}

/** El cuerpo del alta de proveedor. */
export function supplierPayload(form: SupplierEntryForm) {
  return {
    name: text(form.name) ?? "",
    country: text(form.country),
    city: text(form.city),
    website: text(form.website),
    verification: form.verification,
    verified_by: text(form.verifiedBy),
  };
}

/** El cuerpo de la cotización. Todo lo que el formulario deje vacío va como
 * `null`, y el backend lo guarda como no declarado. */
export function quotePayload(form: SupplierEntryForm, productId: string) {
  const provenance: SupplierProvenance =
    form.verification === "third_party_verified" ? "third_party_verified" : "supplier_claim";
  return {
    product_id: productId,
    provenance,
    unit_price: numeric(form.unitPrice),
    currency: numeric(form.unitPrice) === null ? null : text(form.currency),
    moq: numeric(form.moq),
    lead_time_days: numeric(form.leadTimeDays),
    transit_days: numeric(form.transitDays),
    incoterm: text(form.incoterm),
    payment_terms: text(form.paymentTerms),
    destination_market: text(form.destinationMarket),
    logistics_cost_per_unit: numeric(form.logisticsCostPerUnit),
    valid_until: text(form.validUntil) ? `${form.validUntil}T00:00:00Z` : null,
  };
}

/** Solo las capacidades que alguien ha marcado. Una casilla sin tocar **no se
 * envía**: el backend la leerá como no declarada, que es la verdad. Un
 * formulario de casillas manda «no» por omisión, y eso es justo lo que el
 * Milestone 39 quita de en medio. */
export function capabilityPayloads(form: SupplierEntryForm) {
  return (Object.entries(form.capabilities) as [SupplyCapability, boolean | undefined][])
    .filter((entry): entry is [SupplyCapability, boolean] => entry[1] !== undefined)
    .map(([capability, supported]) => ({
      capability,
      supported,
      provenance: "supplier_claim" as const,
    }));
}
