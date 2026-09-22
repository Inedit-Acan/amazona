// DATOS DE DEMOSTRACIÓN — pantalla de Economía y rentabilidad.
//
// Valores inventados (con permiso del propietario, 22-09-2026) para que el
// panel se vea como el mockup mientras el backend no los proporciona. Se usan
// solo cuando no hay dato real y la pantalla lo señala con la etiqueta «Demo».
// Sustituir por datos reales cuando existan los endpoints (ver
// docs/design/AMAZONA_estado_paneles_rediseno.md, sección 2).

/** Supuestos de venta cuando no hay ningún análisis guardado. */
export const DEMO_SALE = {
  salePrice: 29.9,
  monthlyFixedCosts: 1000,
  monthlyOrders: 300,
  /** Unidades del primer pedido de stock (capital inicial comprometido). */
  firstOrderUnits: 500,
};

/** Parte de la logística de la cotización que se atribuye a transporte; el
 * resto es arancel / importación (el backend los da juntos). */
export const DEMO_TRANSPORT_SHARE = 0.85;

/** Costes por unidad que el motor económico del backend todavía no modela. */
export const DEMO_UNIT_COSTS = {
  fulfillment: 0.75,
  paymentFeePct: 2.9,
  returnsPct: 4,
  cac: 3.2,
  otherCosts: 0.4,
  conversionPct: 2.8,
};

/** Ficha del producto que el backend aún no guarda. */
export const DEMO_PRODUCT_META = {
  markets: ["es", "eu"] as const,
  marketLabel: "España + UE",
  logisticsModel: "Envío directo",
  description: "Ficha de demostración: la descripción, las fotos y las especificaciones llegarán con el catálogo de producto.",
};
