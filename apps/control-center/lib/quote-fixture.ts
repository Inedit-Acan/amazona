import type { Supplier, SupplierQuoteDetail } from "./api.ts";

type QuoteOverrides = Partial<Omit<SupplierQuoteDetail, "supplier">> & {
  /** Solo los campos del proveedor que interesen al test; el resto se hereda.
   * `null` deja la cotización sin ficha de proveedor, que es lo que pasa con
   * una fila antigua. */
  supplier?: Partial<Supplier> | null;
};

/** Cotización de ejemplo **para los tests**, con la forma completa que el
 * backend devuelve desde el Milestone 39.
 *
 * No es dato de demostración de pantalla —eso vive en `lib/demo/` y lleva su
 * insignia— sino el andamio que evita repetir veinte campos en cada fichero de
 * test. Por defecto describe un proveedor verificado por un tercero con todos
 * sus números declarados; cada test cambia lo que le interesa y, sobre todo,
 * puede poner `null` en lo que quiera dejar sin declarar.
 */
export function quoteFixture(overrides: QuoteOverrides = {}): SupplierQuoteDetail {
  const supplierId = overrides.supplier_id ?? "sup-eu";
  const { supplier, ...quote } = overrides;
  return {
    id: "q1",
    product_id: "p1",
    supplier_id: supplierId,
    unit_price: 3.4,
    currency: "EUR",
    quoted_unit: "piece",
    quoted_quantity: 1,
    moq: 10,
    lead_time_days: 10,
    transit_days: null,
    transport_mode: null,
    incoterm: "DAP",
    payment_terms: null,
    destination_market: "eu",
    valid_from: null,
    valid_until: null,
    provenance: "supplier_claim",
    source: "manual:test",
    logistics_cost_per_unit: 1.2,
    logistics_provenance: "amazona_estimate",
    total_landed_cost_per_unit: 4.6,
    data: { name: "Bratislava Homeware Supply", region: "eu" },
    capabilities: [],
    unanswered_capabilities: [],
    risk: [],
    ...quote,
    // El proveedor se fusiona campo a campo, no se sustituye entero: un test
    // que solo quiere cambiar la fiabilidad no debería reescribir la ficha.
    supplier:
      supplier === null
        ? null
        : {
            id: supplierId,
            name: "Bratislava Homeware Supply",
            identity_key: "bratislava homeware supply|region:eu",
            identity_method: "normalised",
            region: "eu",
            country: null,
            city: null,
            website: null,
            verification: "third_party_verified",
            verified_by: "Bureau of Test",
            reliability_score: 0.9,
            reliability_provenance: "third_party_verified",
            last_checked_at: null,
            ...(supplier ?? {}),
          },
  };
}
