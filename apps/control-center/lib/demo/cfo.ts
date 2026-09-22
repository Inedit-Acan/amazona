// DATOS DE DEMOSTRACIÓN — pantalla de Finanzas y control.
//
// Valores inventados (con permiso del propietario, 22-09-2026) para que el
// panel se vea como el mockup mientras el backend no los proporciona: AMAZONA
// no tiene contabilidad, tesorería, facturación ni banco, así que la caja, el
// cash flow, las cuentas a pagar y cobrar, la fiscalidad y las subvenciones son
// simulados. Lo real —el informe del agente CFO y los análisis económicos— se
// usa siempre que existe. Sustituir cuando existan los endpoints
// (docs/design/AMAZONA_estado_paneles_rediseno.md, sección 7).

/** «Entidades» de la demostración: AMAZONA no tiene sociedades ni contabilidad
 * separada, así que cada una filtra por los mercados de destino de los pedidos. */
export const ENTITIES = [
  { value: "es", label: "AMAZONA España + UE", markets: ["eu"] },
  { value: "intl", label: "AMAZONA Internacional", markets: ["us", "mx"] },
  { value: "all", label: "Consolidado", markets: ["eu", "us", "mx"] },
];

export const SCENARIO_VIEWS = [
  { value: "actual_forecast", label: "Actual + Forecast" },
  { value: "actual", label: "Solo actual" },
  { value: "forecast", label: "Solo forecast" },
];

export const CASH_FLOW_RANGES = [
  { value: "6", label: "6 meses", months: 6 },
  { value: "12", label: "12 meses", months: 12 },
];

/** Coste mensual de software e IA de toda la empresa (no se reparte por producto). */
export const DEMO_SOFTWARE_MONTHLY = 1080;

/** Impuesto de sociedades aplicado al EBITDA y IVA sobre el valor añadido. */
export const DEMO_TAX_RATE = 0.25;
export const DEMO_VAT_RATE = 0.21;

/** Caja de partida de la demostración (no hay banco conectado). */
export const DEMO_CASH = {
  operating: 18240,
  reserve: 5000,
  /** Cobros de pasarela todavía no liquidados, como proporción de lo pendiente de cobro. */
  stripeShare: 0.3,
  paypalShare: 0.1,
};

/** Crecimiento mensual de ingresos y costes en el cash flow y el forecast. */
export const DEMO_GROWTH = { revenue: 0.06, costs: 0.04 };

/** Variación de cada mes pasado respecto a la tendencia (determinista por mes). */
export const DEMO_MONTH_NOISE = 0.12;

export const BUDGET_CATEGORIES = [
  { key: "marketing", label: "Marketing", color: "#f2c94c", annual: 35000 },
  { key: "operations", label: "Operaciones", color: "#00d69a", annual: 20000 },
  { key: "software", label: "Software / IA", color: "#4f8df7", annual: 15000 },
  { key: "legal", label: "Legal", color: "#e056c8", annual: 8000 },
  { key: "admin", label: "Administración", color: "#f2994a", annual: 12000 },
  { key: "reserve", label: "Reserva", color: "#e05c5c", annual: 10000 },
];

/** Presupuesto anual de demostración cuando el BudgetEngine no tiene límite. */
export const DEMO_ANNUAL_BUDGET = BUDGET_CATEGORIES.reduce((sum, c) => sum + c.annual, 0);

/** Coste mensual de legal (asesoría) que no sale de ningún análisis. */
export const DEMO_LEGAL_MONTHLY = 390;

/** Plataformas de pago y su canal de pedido, para las cuentas a cobrar. */
export const PAYMENT_CHANNELS = [
  { key: "stripe", label: "Stripe", channel: "Web", settlementDays: 2 },
  { key: "amazon", label: "Amazon", channel: "Amazon", settlementDays: 14 },
  { key: "paypal", label: "PayPal", channel: "Instagram", settlementDays: 3 },
  { key: "tiktok", label: "TikTok Shop", channel: "TikTok", settlementDays: 7 },
];

/** Gastos fijos de la empresa que aparecen en cuentas a pagar además de los proveedores. */
export const DEMO_FIXED_PAYABLES = [
  { key: "aws", label: "AWS", amount: 180, dueInDays: 9 },
  { key: "software", label: "Software / IA", amount: DEMO_SOFTWARE_MONTHLY - 180, dueInDays: 12 },
];

/** Capital de trabajo: cuánto se cobra al cliente antes de pagar al proveedor. */
export const DEMO_WORKING_CAPITAL = { prepaidShare: 0.924, targetMin: 0.75, targetMax: 0.9 };

/** Subvenciones y financiación detectadas (no hay buscador de ayudas). */
export const DEMO_FUNDING = { detected: 3, eligible: 1, inProgress: 0 };

/** Porcentaje de documentación fiscal preparada. */
export const DEMO_TAX_DOCS_READY = 0.94;

/** Preguntas de ejemplo del copiloto financiero (sin backend conversacional). */
export const DEMO_COPILOT_QUESTIONS = [
  "¿Cuánto podemos invertir en marketing?",
  "¿Cuál será la caja en 3 meses?",
  "¿Por qué ha bajado el margen este mes?",
];

export const MONTH_LABELS = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"];
