// Modelo económico por unidad de la pantalla de Economía (mockup
// docs/design/economia y rentabilidad.png). Todo lo que se ve en el panel
// (KPIs, escenarios, desglose, simulador, sensibilidad, punto de equilibrio y
// viabilidad) se deriva de un único conjunto de supuestos, así que las cifras
// son coherentes entre sí y el simulador las recalcula en vivo.
//
// El motor del backend solo calcula coste de entrega + costes fijos y tres
// volúmenes; el resto de costes (arancel, fulfillment, pasarela, devoluciones,
// CAC) son supuestos de demostración (lib/demo/economics.ts) hasta que el
// backend los exponga.

export interface EconomicsInputs {
  salePrice: number;
  /** Precio unitario del proveedor. */
  supplierCost: number;
  /** Transporte por unidad (aéreo, DDP). */
  transport: number;
  /** Arancel / importación por unidad. */
  tariff: number;
  /** Gestión / fulfillment por unidad. */
  fulfillment: number;
  /** Comisión de la pasarela de pago, en % del precio. */
  paymentFeePct: number;
  /** Reserva para devoluciones, en % del precio. */
  returnsPct: number;
  /** Publicidad / CAC por pedido. */
  cac: number;
  otherCosts: number;
  /** Conversión estimada, en % (2,8 = 2,8 %). */
  conversionPct: number;
  monthlyOrders: number;
  monthlyFixedCosts: number;
  /** Capital inicial comprometido (stock del primer pedido). */
  initialInvestment: number;
}

export type CostKey =
  | "supplier"
  | "transport"
  | "tariff"
  | "fulfillment"
  | "payment"
  | "returns"
  | "cac"
  | "other";

export interface CostLine {
  key: CostKey;
  label: string;
  amount: number;
}

export function costLines(i: EconomicsInputs): CostLine[] {
  return [
    { key: "supplier", label: "Producto (proveedor)", amount: i.supplierCost },
    { key: "transport", label: "Transporte (aéreo, DDP)", amount: i.transport },
    { key: "tariff", label: "Arancel / importación", amount: i.tariff },
    { key: "fulfillment", label: "Gestión / fulfillment", amount: i.fulfillment },
    { key: "payment", label: `Pasarela de pago (${trimPct(i.paymentFeePct)} %)`, amount: (i.salePrice * i.paymentFeePct) / 100 },
    { key: "returns", label: `Reserva devoluciones (${trimPct(i.returnsPct)} %)`, amount: (i.salePrice * i.returnsPct) / 100 },
    { key: "cac", label: "Publicidad / CAC", amount: i.cac },
    { key: "other", label: "Otros costes", amount: i.otherCosts },
  ];
}

function trimPct(value: number): string {
  return value.toLocaleString("es-ES", { maximumFractionDigits: 1 });
}

export function unitCost(i: EconomicsInputs): number {
  return costLines(i).reduce((sum, line) => sum + line.amount, 0);
}

export interface EconomicsResult {
  unitCost: number;
  /** Margen de contribución por unidad. */
  contribution: number;
  /** Fracción (0,42 = 42 %). */
  contributionMargin: number;
  monthlyRevenue: number;
  monthlyProfit: number;
  /** Beneficio / ingresos, fracción. */
  netMargin: number;
  /** null si cada unidad pierde dinero (nunca se alcanza). */
  breakEvenUnits: number | null;
  breakEvenRevenue: number | null;
  /** Meses para recuperar el capital inicial; null si no hay beneficio. */
  paybackMonths: number | null;
  /** CAC con el que el beneficio mensual sería 0. */
  maxCac: number;
  /** Precio con el que el beneficio mensual sería 0. */
  minViablePrice: number;
}

export function evaluate(i: EconomicsInputs): EconomicsResult {
  const cost = unitCost(i);
  const contribution = i.salePrice - cost;
  const monthlyRevenue = i.salePrice * i.monthlyOrders;
  const monthlyProfit = contribution * i.monthlyOrders - i.monthlyFixedCosts;
  const breakEvenUnits = contribution > 0 ? Math.ceil(i.monthlyFixedCosts / contribution) : null;
  const priceShare = 1 - (i.paymentFeePct + i.returnsPct) / 100;
  const fixedPerUnitCosts = i.supplierCost + i.transport + i.tariff + i.fulfillment + i.cac + i.otherCosts;
  const fixedPerOrder = i.monthlyOrders > 0 ? i.monthlyFixedCosts / i.monthlyOrders : Infinity;
  return {
    unitCost: cost,
    contribution,
    contributionMargin: i.salePrice > 0 ? contribution / i.salePrice : 0,
    monthlyRevenue,
    monthlyProfit,
    netMargin: monthlyRevenue > 0 ? monthlyProfit / monthlyRevenue : 0,
    breakEvenUnits,
    breakEvenRevenue: breakEvenUnits === null ? null : breakEvenUnits * i.salePrice,
    paybackMonths: monthlyProfit > 0 ? i.initialInvestment / monthlyProfit : null,
    maxCac: i.monthlyOrders > 0 ? i.cac + monthlyProfit / i.monthlyOrders : 0,
    minViablePrice: priceShare > 0 ? (fixedPerUnitCosts + fixedPerOrder) / priceShare : Infinity,
  };
}

// --- Escenarios ---------------------------------------------------------------

export type ScenarioKey = "conservative" | "base" | "optimistic";

/** Variación de precio y volumen respecto al caso base (supuesto de demostración:
 * el backend solo varía el volumen). */
export const SCENARIO_FACTORS: Record<ScenarioKey, { label: string; price: number; orders: number }> = {
  conservative: { label: "Conservador", price: 0.933, orders: 0.4 },
  base: { label: "Base", price: 1, orders: 1 },
  optimistic: { label: "Optimista", price: 1.1, orders: 2 },
};

export interface ScenarioResult {
  key: ScenarioKey;
  label: string;
  inputs: EconomicsInputs;
  result: EconomicsResult;
}

export function scenarios(i: EconomicsInputs): ScenarioResult[] {
  return (Object.keys(SCENARIO_FACTORS) as ScenarioKey[]).map((key) => {
    const f = SCENARIO_FACTORS[key];
    const inputs = {
      ...i,
      salePrice: Math.round(i.salePrice * f.price * 100) / 100,
      monthlyOrders: Math.round(i.monthlyOrders * f.orders),
    };
    return { key, label: f.label, inputs, result: evaluate(inputs) };
  });
}

/** Beneficio mensual de un escenario para distintos volúmenes de pedidos. */
export function profitCurve(i: EconomicsInputs, orders: number[]): { x: number; y: number }[] {
  return orders.map((x) => ({ x, y: evaluate({ ...i, monthlyOrders: x }).monthlyProfit }));
}

// --- Sensibilidad -------------------------------------------------------------

export type ImpactLevel = "Alto" | "Medio" | "Bajo";

export interface SensitivityItem {
  key: string;
  label: string;
  /** Caída del beneficio mensual respecto al caso base, fracción (0,35 = −35 %). */
  impact: number;
  level: ImpactLevel;
}

const SHOCKS: { key: string; label: string; apply: (i: EconomicsInputs) => EconomicsInputs }[] = [
  { key: "cac", label: "CAC +25 %", apply: (i) => ({ ...i, cac: i.cac * 1.25 }) },
  { key: "supplier", label: "Coste proveedor +15 %", apply: (i) => ({ ...i, supplierCost: i.supplierCost * 1.15 }) },
  { key: "returns", label: "Devoluciones +5 pp", apply: (i) => ({ ...i, returnsPct: i.returnsPct + 5 }) },
  { key: "price", label: "Precio venta −5 %", apply: (i) => ({ ...i, salePrice: i.salePrice * 0.95 }) },
  { key: "transport", label: "Transporte +20 %", apply: (i) => ({ ...i, transport: i.transport * 1.2 }) },
  {
    key: "conversion",
    label: "Conversión −20 %",
    apply: (i) => ({ ...i, conversionPct: i.conversionPct * 0.8, monthlyOrders: Math.round(i.monthlyOrders * 0.8) }),
  },
];

export function impactLevel(impact: number): ImpactLevel {
  if (impact >= 0.3) return "Alto";
  if (impact >= 0.12) return "Medio";
  return "Bajo";
}

/** Cuánto cae el beneficio con cada variación, de mayor a menor impacto. */
export function sensitivity(i: EconomicsInputs): SensitivityItem[] {
  const base = evaluate(i).monthlyProfit;
  const scale = Math.abs(base) || 1;
  return SHOCKS.map((shock) => {
    const impact = Math.max(0, (base - evaluate(shock.apply(i)).monthlyProfit) / scale);
    return { key: shock.key, label: shock.label, impact, level: impactLevel(impact) };
  }).sort((a, b) => b.impact - a.impact);
}

// --- Riesgo y viabilidad --------------------------------------------------------

export type RiskLevel = "Bajo" | "Medio" | "Alto";

/** Riesgo económico y su nivel en una escala de 1 (mínimo) a 5. */
export function economicRisk(i: EconomicsInputs): { level: RiskLevel; score: number } {
  const r = evaluate(i);
  const conservative = evaluate(scenarios(i)[0].inputs).monthlyProfit;
  let score = 1;
  if (r.contributionMargin < 0.35) score++;
  if (r.contributionMargin < 0.2) score++;
  if (conservative <= 0) score++;
  if (r.monthlyProfit <= 0) score++;
  return { level: score <= 2 ? "Bajo" : score <= 3 ? "Medio" : "Alto", score };
}

export interface ViabilityItem {
  label: string;
  value: string;
  tone: "ok" | "warn" | "bad";
}

export function viabilityItems(i: EconomicsInputs): ViabilityItem[] {
  const r = evaluate(i);
  const [conservative] = scenarios(i);
  const risk = economicRisk(i);
  const profitability: ViabilityItem =
    r.monthlyProfit > 0 && r.contributionMargin >= 0.35
      ? { label: "Rentabilidad", value: "Alta", tone: "ok" }
      : r.monthlyProfit > 0
        ? { label: "Rentabilidad", value: "Media", tone: "warn" }
        : { label: "Rentabilidad", value: "Baja", tone: "bad" };
  const robustness: ViabilityItem =
    conservative.result.monthlyProfit > 0
      ? { label: "Robustez de escenarios", value: "Alta", tone: "ok" }
      : r.monthlyProfit > 0
        ? { label: "Robustez de escenarios", value: "Media", tone: "warn" }
        : { label: "Robustez de escenarios", value: "Baja", tone: "bad" };
  const capital: ViabilityItem =
    i.initialInvestment < 5000
      ? { label: "Capital necesario", value: "Bajo", tone: "ok" }
      : i.initialInvestment < 15000
        ? { label: "Capital necesario", value: "Medio", tone: "warn" }
        : { label: "Capital necesario", value: "Alto", tone: "bad" };
  return [
    profitability,
    robustness,
    capital,
    { label: "Riesgo financiero", value: risk.level, tone: risk.level === "Bajo" ? "ok" : risk.level === "Medio" ? "warn" : "bad" },
  ];
}

/** Veredicto global: nunca «rentable» sin «bajo estas hipótesis» (spec §7.10). */
export function verdict(i: EconomicsInputs): { title: string; tone: "ok" | "warn" | "bad" } {
  const r = evaluate(i);
  const risk = economicRisk(i);
  if (r.monthlyProfit <= 0) return { title: "No rentable bajo estas hipótesis.", tone: "bad" };
  if (risk.level === "Bajo") return { title: "Rentable bajo estas hipótesis.", tone: "ok" };
  return { title: "Rentable con reservas bajo estas hipótesis.", tone: "warn" };
}
