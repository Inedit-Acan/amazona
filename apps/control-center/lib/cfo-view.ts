import type { CFOReport, EconomicAnalysis } from "./api.ts";
import {
  BUDGET_CATEGORIES,
  DEMO_ANNUAL_BUDGET,
  DEMO_CASH,
  DEMO_FIXED_PAYABLES,
  DEMO_GROWTH,
  DEMO_LEGAL_MONTHLY,
  DEMO_MONTH_NOISE,
  DEMO_SOFTWARE_MONTHLY,
  DEMO_TAX_RATE,
  DEMO_VAT_RATE,
  DEMO_WORKING_CAPITAL,
  MONTH_LABELS,
  PAYMENT_CHANNELS,
} from "./demo/cfo.ts";
import { demoRandom } from "./demo/random.ts";
import { costLines, scenarios as modelScenarios, type EconomicsInputs } from "./economics-model.ts";
import { ACTIVE_STATUSES, daysBetween, type Order } from "./operations-view.ts";

// Vista de la pantalla de Finanzas y control (mockup docs/design/CFO.png).
// La cuenta de resultados se construye con los MISMOS supuestos que Economía
// (lib/economics-model.ts sobre cada producto), así que ingresos, costes y
// margen cuadran con esa pantalla, el marketing con el CAC objetivo de Marketing
// y las cuentas a cobrar y pagar con los pedidos de Operaciones. Lo que exige
// contabilidad o banco —caja, cash flow, fiscalidad, subvenciones— es de
// demostración (lib/demo/cfo.ts). El informe del agente CFO aporta su veredicto
// de salud financiera y el presupuesto del BudgetEngine cuando existe.

const round2 = (value: number) => Math.round(value * 100) / 100;

export interface ProductFinance {
  id: string;
  name: string;
  category: string;
  inputs: EconomicsInputs;
  /** Escenarios reales del análisis económico, si el producto tiene uno. */
  analysis?: EconomicAnalysis;
  isDemo: boolean;
}

export type PnlKey =
  | "revenue"
  | "cogs"
  | "gross"
  | "marketing"
  | "software"
  | "logistics"
  | "returns"
  | "admin"
  | "other"
  | "ebitda"
  | "tax"
  | "net";

export interface PnlRow {
  key: PnlKey;
  label: string;
  amount: number;
  /** Variación frente al mes anterior (fracción); null en los totales derivados. */
  delta: number | null;
  kind: "income" | "cost" | "total";
}

export interface Pnl {
  rows: PnlRow[];
  revenue: number;
  cogs: number;
  grossMargin: number;
  grossMarginPct: number;
  operatingCosts: number;
  ebitda: number;
  ebitdaPct: number;
  tax: number;
  net: number;
  netMarginPct: number;
  /** Gasto total del mes (costes + impuestos). */
  spend: number;
  costByCategory: Record<string, number>;
}

/** Cuenta de resultados mensual de todo el catálogo con los supuestos de Economía.
 * Las variaciones las rellena `withDeltas` comparando con otro mes. */
export function buildPnl(products: ProductFinance[]): Pnl {
  const sum = (pick: (line: { key: string; amount: number }) => number, inputs: EconomicsInputs, orders: number) =>
    costLines(inputs).reduce((acc, line) => acc + pick(line) * orders, 0);

  let revenue = 0;
  let cogs = 0;
  let marketing = 0;
  let logistics = 0;
  let returns = 0;
  let admin = 0;
  let other = 0;

  for (const product of products) {
    const { inputs } = product;
    const orders = inputs.monthlyOrders;
    revenue += inputs.salePrice * orders;
    cogs += sum((l) => (["supplier", "transport", "tariff"].includes(l.key) ? l.amount : 0), inputs, orders);
    marketing += sum((l) => (l.key === "cac" ? l.amount : 0), inputs, orders);
    logistics += sum((l) => (l.key === "fulfillment" ? l.amount : 0), inputs, orders);
    returns += sum((l) => (l.key === "returns" ? l.amount : 0), inputs, orders);
    other += sum((l) => (["payment", "other"].includes(l.key) ? l.amount : 0), inputs, orders);
    admin += inputs.monthlyFixedCosts;
  }

  const software = DEMO_SOFTWARE_MONTHLY;
  const legal = DEMO_LEGAL_MONTHLY;
  const grossMargin = revenue - cogs;
  const operatingCosts = marketing + software + logistics + returns + admin + other + legal;
  const ebitda = grossMargin - operatingCosts;
  const tax = Math.max(0, ebitda * DEMO_TAX_RATE);
  const net = ebitda - tax;
  const rows: PnlRow[] = [
    { key: "revenue", label: "Ingresos", amount: round2(revenue), delta: null, kind: "income" },
    { key: "cogs", label: "Coste de mercancía", amount: -round2(cogs), delta: null, kind: "cost" },
    { key: "gross", label: "Margen bruto", amount: round2(grossMargin), delta: null, kind: "total" },
    { key: "marketing", label: "Marketing", amount: -round2(marketing), delta: null, kind: "cost" },
    { key: "software", label: "Software / IA", amount: -round2(software), delta: null, kind: "cost" },
    { key: "logistics", label: "Logística", amount: -round2(logistics), delta: null, kind: "cost" },
    { key: "returns", label: "Devoluciones", amount: -round2(returns), delta: null, kind: "cost" },
    { key: "admin", label: "Administración", amount: -round2(admin + legal), delta: null, kind: "cost" },
    { key: "other", label: "Otros", amount: -round2(other), delta: null, kind: "cost" },
    { key: "ebitda", label: "EBITDA", amount: round2(ebitda), delta: null, kind: "total" },
    { key: "tax", label: "Impuestos estimados", amount: -round2(tax), delta: null, kind: "cost" },
    { key: "net", label: "Resultado neto", amount: round2(net), delta: null, kind: "total" },
  ];

  return {
    rows,
    revenue: round2(revenue),
    cogs: round2(cogs),
    grossMargin: round2(grossMargin),
    grossMarginPct: revenue > 0 ? grossMargin / revenue : 0,
    operatingCosts: round2(operatingCosts),
    ebitda: round2(ebitda),
    ebitdaPct: revenue > 0 ? ebitda / revenue : 0,
    tax: round2(tax),
    net: round2(net),
    netMarginPct: revenue > 0 ? net / revenue : 0,
    spend: round2(cogs + operatingCosts + tax),
    costByCategory: {
      marketing: round2(marketing),
      operations: round2(logistics + returns),
      software: round2(software),
      legal: round2(legal),
      admin: round2(admin),
      reserve: 0,
    },
  };
}

/** Factor de un mes respecto al actual: tendencia de crecimiento más la variación
 * determinista de los meses ya cerrados (la misma que usa el cash flow). */
export function monthFactor(offset: number, kind: "revenue" | "costs"): number {
  const rate = kind === "revenue" ? DEMO_GROWTH.revenue : DEMO_GROWTH.costs;
  const salt = kind === "revenue" ? "in" : "out";
  const noise = offset <= 0 ? 1 + (demoRandom(`${salt}${offset}`, "cash") * 2 - 1) * DEMO_MONTH_NOISE : 1;
  return (1 + rate) ** offset * noise;
}

/** La misma cuenta de resultados a otra escala: otro mes (con su factor) o la
 * parte del negocio de una entidad. Ingresos y costes escalan por separado. */
export function scalePnl(pnl: Pnl, revenueFactor: number, costFactor: number): Pnl {
  if (revenueFactor === 1 && costFactor === 1) return pnl;
  const scaled = (amount: number, kind: "income" | "cost" | "total") =>
    round2(amount * (kind === "income" ? revenueFactor : costFactor));
  const revenue = round2(pnl.revenue * revenueFactor);
  const cogs = round2(pnl.cogs * costFactor);
  const operatingCosts = round2(pnl.operatingCosts * costFactor);
  const grossMargin = round2(revenue - cogs);
  const ebitda = round2(grossMargin - operatingCosts);
  const tax = round2(Math.max(0, ebitda * DEMO_TAX_RATE));
  const net = round2(ebitda - tax);
  const rows = pnl.rows.map((row) => {
    if (row.key === "gross") return { ...row, amount: grossMargin };
    if (row.key === "ebitda") return { ...row, amount: ebitda };
    if (row.key === "tax") return { ...row, amount: -tax };
    if (row.key === "net") return { ...row, amount: net };
    return { ...row, amount: scaled(row.amount, row.kind) };
  });
  return {
    rows,
    revenue,
    cogs,
    grossMargin,
    grossMarginPct: revenue > 0 ? grossMargin / revenue : 0,
    operatingCosts,
    ebitda,
    ebitdaPct: revenue > 0 ? ebitda / revenue : 0,
    tax,
    net,
    netMarginPct: revenue > 0 ? net / revenue : 0,
    spend: round2(cogs + operatingCosts + tax),
    costByCategory: Object.fromEntries(Object.entries(pnl.costByCategory).map(([key, value]) => [key, round2(value * costFactor)])),
  };
}

/** Variación de cada línea frente al mismo mes anterior. */
export function withDeltas(current: Pnl, previous: Pnl): Pnl {
  const before = new Map(previous.rows.map((row) => [row.key, row.amount]));
  return {
    ...current,
    rows: current.rows.map((row) => {
      if (row.kind === "total") return row;
      const prev = before.get(row.key) ?? 0;
      return { ...row, delta: prev !== 0 ? Math.abs(row.amount) / Math.abs(prev) - 1 : null };
    }),
  };
}

// --- Cash flow -------------------------------------------------------------------

export interface CashFlowMonth {
  /** Meses desde el actual: negativo pasado, 0 el mes en curso, positivo forecast. */
  offset: number;
  label: string;
  inflow: number;
  outflow: number;
  /** Saldo acumulado al cierre del mes. */
  balance: number;
  forecast: boolean;
}

/** Serie mensual de entradas, salidas y saldo. Las entradas y salidas salen de la
 * cuenta de resultados con la tendencia de crecimiento; el saldo de los meses
 * cerrados se reconstruye haciendo crecer la caja actual a ese mismo ritmo (no hay
 * histórico bancario) y el del forecast suma el resultado previsto de cada mes. */
export function cashFlowSeries(pnl: Pnl, cash: number, months: number, monthIndex: number): CashFlowMonth[] {
  const past = Math.ceil(months / 2);
  const future = months - past;
  const rows: CashFlowMonth[] = [];
  let forward = cash;
  for (let offset = -past + 1; offset <= future; offset++) {
    const inflow = round2(pnl.revenue * monthFactor(offset, "revenue"));
    const outflow = round2(pnl.spend * monthFactor(offset, "costs"));
    if (offset > 0) forward += inflow - outflow;
    rows.push({
      offset,
      label: MONTH_LABELS[(((monthIndex + offset) % 12) + 12) % 12],
      inflow,
      outflow,
      balance: round2(offset <= 0 ? cash * (1 + DEMO_GROWTH.revenue) ** offset : forward),
      forecast: offset > 0,
    });
  }
  return rows;
}

/** Primer mes del forecast con saldo por debajo del colchón mínimo (un mes de gastos). */
export function cashWarning(series: CashFlowMonth[], monthlySpend: number): CashFlowMonth | null {
  return series.find((r) => r.forecast && r.balance < monthlySpend) ?? null;
}

// --- Presupuesto -----------------------------------------------------------------

export interface BudgetLine {
  key: string;
  label: string;
  color: string;
  limit: number;
  spent: number;
  /** Gasto sobre el límite (0–∞). */
  usage: number;
}

export interface BudgetView {
  annual: number;
  spent: number;
  usage: number;
  lines: BudgetLine[];
  /** El límite sale del BudgetEngine (informe del CFO) y no de la demostración. */
  isReal: boolean;
}

/** Presupuesto anual: el límite del BudgetEngine si lo hay; el gasto de cada
 * categoría son los meses transcurridos del año al ritmo del mes actual. */
export function budgetView(pnl: Pnl, monthsElapsed: number, report?: CFOReport): BudgetView {
  const limit = report?.data?.total_budget_hard_limit ?? 0;
  const isReal = limit > 0;
  const annual = isReal ? limit : DEMO_ANNUAL_BUDGET;
  const scale = isReal ? limit / DEMO_ANNUAL_BUDGET : 1;
  const reserved = report?.data ? report.data.total_reserved + report.data.total_committed : 0;
  const lines = BUDGET_CATEGORIES.map((category) => {
    const spent =
      category.key === "reserve" ? reserved || round2(pnl.spend * 0.1 * monthsElapsed) : round2((pnl.costByCategory[category.key] ?? 0) * monthsElapsed);
    const categoryLimit = round2(category.annual * scale);
    return { key: category.key, label: category.label, color: category.color, limit: categoryLimit, spent, usage: categoryLimit > 0 ? spent / categoryLimit : 0 };
  });
  const spent = round2(lines.reduce((sum, line) => sum + line.spent, 0));
  return { annual: round2(annual), spent, usage: annual > 0 ? spent / annual : 0, lines, isReal };
}

export interface Deviation {
  key: string;
  label: string;
  /** Desviación del mes frente al presupuesto mensual (fracción). */
  deviation: number;
  detail: string;
  tone: "ok" | "warn" | "bad";
}

/** Desviaciones del mes: gasto real de cada categoría frente a su doceava parte. */
export function deviations(pnl: Pnl, budget: BudgetView): Deviation[] {
  const detailOf = (key: string, deviation: number): string => {
    if (key === "marketing") return deviation > 0 ? "Gasto ligeramente por encima de lo previsto." : "Inversión por debajo del plan.";
    if (key === "operations") return deviation > 0 ? "Aumento por mayores costes de transporte y devoluciones." : "Logística por debajo del plan.";
    if (key === "software") return deviation > 0 ? "Por encima del presupuesto." : "Por debajo del presupuesto.";
    if (key === "legal") return deviation > 0 ? "Asesoría por encima del plan." : "Asesoría por debajo del plan.";
    return deviation > 0 ? "Por encima del plan." : "Por debajo del plan.";
  };
  return budget.lines
    .filter((line) => line.key !== "reserve")
    .map((line) => {
      const monthly = line.limit / 12;
      const actual = pnl.costByCategory[line.key] ?? 0;
      const deviation = monthly > 0 ? actual / monthly - 1 : 0;
      return {
        key: line.key,
        label: line.label,
        deviation,
        detail: detailOf(line.key, deviation),
        tone: deviation > 0.1 ? "bad" : deviation > 0.02 ? "warn" : "ok",
      } satisfies Deviation;
    })
    .sort((a, b) => Math.abs(b.deviation) - Math.abs(a.deviation));
}

// --- Tesorería, cobros y pagos -----------------------------------------------------

export interface TreasuryView {
  operating: number;
  reserve: number;
  stripe: number;
  paypal: number;
  total: number;
}

export function treasury(receivableTotal: number): TreasuryView {
  const stripe = round2(receivableTotal * DEMO_CASH.stripeShare);
  const paypal = round2(receivableTotal * DEMO_CASH.paypalShare);
  return {
    operating: DEMO_CASH.operating,
    reserve: DEMO_CASH.reserve,
    stripe,
    paypal,
    total: round2(DEMO_CASH.operating + DEMO_CASH.reserve + stripe + paypal),
  };
}

export interface UpcomingLine {
  key: string;
  label: string;
  amount: number;
}

/** Movimientos previstos de los próximos 7 días (una semana del ritmo mensual). */
export function upcomingWeek(pnl: Pnl, receivableTotal: number): { lines: UpcomingLine[]; net: number } {
  const week = 7 / 30;
  const lines: UpcomingLine[] = [
    { key: "collections", label: "Cobros previstos", amount: round2(receivableTotal * 0.5 + pnl.revenue * week * 0.4) },
    { key: "suppliers", label: "Proveedores", amount: -round2(pnl.cogs * week) },
    { key: "marketing", label: "Marketing", amount: -round2((pnl.costByCategory.marketing ?? 0) * week) },
    { key: "software", label: "Software / IA", amount: -round2((pnl.costByCategory.software ?? 0) * week) },
  ];
  return { lines, net: round2(lines.reduce((sum, line) => sum + line.amount, 0)) };
}

export interface PayableRow {
  key: string;
  label: string;
  amount: number;
  /** Días hasta el vencimiento. */
  dueInDays: number;
  status: "Pendiente" | "Programado";
}

/** Cuentas a pagar: el coste de proveedor de los pedidos abiertos, el gasto de
 * publicidad del mes y los gastos fijos de la demostración. */
export function payables(orders: Order[], pnl: Pnl, today: number): PayableRow[] {
  const bySupplier = new Map<string, { name: string; amount: number; dueInDays: number }>();
  for (const order of orders) {
    if (!ACTIVE_STATUSES.includes(order.status)) continue;
    const current = bySupplier.get(order.supplierId) ?? { name: order.supplierName, amount: 0, dueInDays: 30 };
    current.amount += order.amount * 0.45;
    current.dueInDays = Math.min(current.dueInDays, Math.max(1, 30 - daysBetween(order.createdAt, today)));
    bySupplier.set(order.supplierId, current);
  }
  const supplierRows: PayableRow[] = [...bySupplier.entries()].map(([id, value]) => ({
    key: id,
    label: value.name,
    amount: round2(value.amount),
    dueInDays: value.dueInDays,
    status: "Pendiente",
  }));
  const marketing = pnl.costByCategory.marketing ?? 0;
  const adRows: PayableRow[] = [
    { key: "meta", label: "Meta Ads", amount: round2(marketing * 0.45), dueInDays: 6, status: "Pendiente" },
    { key: "google", label: "Google Ads", amount: round2(marketing * 0.38), dueInDays: 5, status: "Programado" },
  ];
  const fixedRows: PayableRow[] = DEMO_FIXED_PAYABLES.map((row) => ({
    key: row.key,
    label: row.label,
    amount: row.amount,
    dueInDays: row.dueInDays,
    status: "Pendiente",
  }));
  return [...supplierRows, ...adRows, ...fixedRows].filter((row) => row.amount > 0).sort((a, b) => a.dueInDays - b.dueInDays);
}

export interface ReceivableRow {
  key: string;
  label: string;
  amount: number;
  status: "En tránsito" | "Pendiente";
  /** Días medios hasta el cobro. */
  settlementDays: number;
}

/** Cuentas a cobrar por plataforma de pago, con el importe de los pedidos que
 * todavía no se han liquidado (los abiertos y los entregados hace poco). */
export function receivables(orders: Order[], today: number): { rows: ReceivableRow[]; total: number; averageDays: number } {
  const rows = PAYMENT_CHANNELS.map((channel) => {
    const own = orders.filter(
      (o) => o.channel === channel.channel && (ACTIVE_STATUSES.includes(o.status) || daysBetween(o.estimatedAt, today) < channel.settlementDays),
    );
    const amount = round2(own.reduce((sum, o) => sum + o.amount, 0));
    const inTransit = own.some((o) => o.status === "in_transit" || o.status === "shipped");
    return {
      key: channel.key,
      label: channel.label,
      amount,
      status: (inTransit ? "En tránsito" : "Pendiente") as ReceivableRow["status"],
      settlementDays: channel.settlementDays,
    };
  }).filter((row) => row.amount > 0);
  const total = round2(rows.reduce((sum, row) => sum + row.amount, 0));
  const averageDays = total > 0 ? rows.reduce((sum, row) => sum + row.settlementDays * row.amount, 0) / total : 0;
  return { rows, total, averageDays };
}

export interface WorkingCapitalView {
  prepaidShare: number;
  advanced: number;
  covered: number;
  uncovered: number;
  coverage: number;
  inRange: boolean;
}

/** Capital de trabajo sin stock: lo que AMAZONA adelanta al proveedor frente a lo
 * que ya tiene cobrado o por cobrar. */
export function workingCapital(payableTotal: number, receivableTotal: number): WorkingCapitalView {
  const advanced = round2(payableTotal);
  const covered = round2(Math.min(advanced, receivableTotal));
  const coverage = advanced > 0 ? covered / advanced : 1;
  return {
    prepaidShare: DEMO_WORKING_CAPITAL.prepaidShare,
    advanced,
    covered,
    uncovered: round2(Math.max(0, advanced - covered)),
    coverage,
    inRange: coverage >= DEMO_WORKING_CAPITAL.targetMin,
  };
}

// --- Forecast y rendimiento ---------------------------------------------------------

export type ForecastKey = "conservative" | "base" | "optimistic";

export interface ForecastPoint {
  offset: number;
  label: string;
  revenue: number;
  costs: number;
  profit: number;
}

/** Forecast a seis meses por escenario. Usa los escenarios reales del análisis
 * económico de cada producto y, si no lo hay, los del mismo modelo que Economía. */
export function forecast(products: ProductFinance[], key: ForecastKey, months: number, monthIndex: number): ForecastPoint[] {
  let revenue = 0;
  let profit = 0;
  for (const product of products) {
    const real = product.analysis?.data?.scenarios?.[key];
    if (real) {
      revenue += real.monthly_revenue;
      profit += real.monthly_profit;
    } else {
      const scenario = modelScenarios(product.inputs).find((s) => s.key === key);
      if (scenario) {
        revenue += scenario.result.monthlyRevenue;
        profit += scenario.result.monthlyProfit;
      }
    }
  }
  const points: ForecastPoint[] = [];
  for (let offset = 0; offset < months; offset++) {
    const grown = revenue * (1 + DEMO_GROWTH.revenue) ** offset;
    const grownProfit = profit * (1 + DEMO_GROWTH.revenue) ** offset;
    points.push({
      offset,
      label: MONTH_LABELS[(((monthIndex + offset) % 12) + 12) % 12],
      revenue: round2(grown),
      costs: round2(grown - grownProfit),
      profit: round2(grownProfit),
    });
  }
  return points;
}

export type DimensionKey = "products" | "channels" | "markets" | "suppliers";

export interface DimensionRow {
  key: string;
  label: string;
  value: number;
}

/** Ingresos por producto, canal, mercado o proveedor sobre los pedidos del periodo. */
export function dimensionRows(orders: Order[], dimension: DimensionKey, marketLabel: (market: string) => string): DimensionRow[] {
  const totals = new Map<string, { label: string; value: number }>();
  for (const order of orders) {
    const [key, label] =
      dimension === "products"
        ? [order.productId, order.productName]
        : dimension === "channels"
          ? [order.channel, order.channel]
          : dimension === "markets"
            ? [order.market, marketLabel(order.market)]
            : [order.supplierId, order.supplierName];
    const current = totals.get(key) ?? { label, value: 0 };
    current.value += order.amount;
    totals.set(key, current);
  }
  return [...totals.entries()]
    .map(([key, value]) => ({ key, label: value.label, value: round2(value.value) }))
    .sort((a, b) => b.value - a.value);
}

// --- Salud financiera, fiscalidad y alertas -------------------------------------------

export interface HealthAxis {
  label: string;
  value: number;
}

/** Runway: meses de gasto que cubre la caja (∞ si el mes es rentable). */
export function runwayMonths(cash: number, pnl: Pnl): number {
  const burn = pnl.spend - pnl.revenue;
  return burn > 0 ? cash / burn : pnl.spend > 0 ? cash / pnl.spend : 0;
}

export function financialHealth(input: {
  pnl: Pnl;
  cash: number;
  budget: BudgetView;
  working: WorkingCapitalView;
  cashSeries: CashFlowMonth[];
  taxProvision: number;
}): { score: number; label: string; axes: HealthAxis[] } {
  const { pnl, cash, budget, working, cashSeries, taxProvision } = input;
  const clamp = (value: number) => Math.max(0, Math.min(100, Math.round(value)));
  const runway = runwayMonths(cash, pnl);
  const positiveMonths = cashSeries.filter((m) => m.inflow >= m.outflow).length / (cashSeries.length || 1);
  const axes: HealthAxis[] = [
    { label: "Liquidez", value: clamp((runway / 12) * 100) },
    { label: "Rentabilidad", value: clamp(pnl.netMarginPct * 300) },
    { label: "Cash flow", value: clamp(positiveMonths * 100) },
    { label: "Presupuesto", value: clamp((1 - Math.max(0, budget.usage - 0.5)) * 100) },
    { label: "Capital expuesto", value: clamp(working.coverage * 100) },
    { label: "Cobertura fiscal", value: clamp(taxProvision > 0 ? (cash / taxProvision) * 25 : 100) },
    { label: "Forecast", value: clamp(90 + DEMO_GROWTH.revenue * 100) },
  ];
  const score = Math.round(axes.reduce((sum, axis) => sum + axis.value, 0) / axes.length);
  return { score, label: score >= 90 ? "Excelente" : score >= 75 ? "Buena" : score >= 60 ? "Aceptable" : "Requiere atención", axes };
}

export interface TaxView {
  vat: number;
  corporate: number;
  nextDueMonth: number;
  docsReady: number;
}

/** Fiscalidad estimada: IVA sobre el valor añadido e impuesto de sociedades del EBITDA. */
export function taxView(pnl: Pnl, monthIndex: number, docsReady: number): TaxView {
  const quarterEndMonths = [0, 3, 6, 9];
  const nextDueMonth = quarterEndMonths.find((m) => m > monthIndex % 12) ?? 12;
  return {
    vat: round2(Math.max(0, pnl.grossMargin * DEMO_VAT_RATE)),
    corporate: round2(pnl.tax),
    nextDueMonth,
    docsReady,
  };
}

export interface FinancialAlert {
  level: "Alta" | "Media" | "Info";
  message: string;
  /** El aviso lo ha emitido el agente CFO (texto suyo, en inglés). */
  fromAgent?: boolean;
}

/** Alertas del mes derivadas de las desviaciones, el presupuesto y los cobros. */
export function financialAlerts(input: {
  deviations: Deviation[];
  budget: BudgetView;
  receivables: { rows: ReceivableRow[]; total: number };
  pnl: Pnl;
  monthsElapsed: number;
  /** Riesgos del informe del agente CFO. */
  agentRisks?: string[];
}): FinancialAlert[] {
  const alerts: FinancialAlert[] = [];
  const worst = input.deviations.find((d) => d.tone === "bad");
  if (worst) {
    alerts.push({ level: "Alta", message: `${worst.label}: ${(worst.deviation * 100).toLocaleString("es-ES", { maximumFractionDigits: 0 })} % sobre el presupuesto del mes.` });
  }
  const expected = input.monthsElapsed / 12;
  if (input.budget.usage > expected + 0.05) {
    alerts.push({ level: "Media", message: `Presupuesto anual al ${(input.budget.usage * 100).toLocaleString("es-ES", { maximumFractionDigits: 0 })} % con ${input.monthsElapsed} de 12 meses transcurridos.` });
  }
  const slowest = [...input.receivables.rows].sort((a, b) => b.settlementDays - a.settlementDays)[0];
  if (slowest) {
    alerts.push({ level: "Media", message: `${slowest.label} mantiene ${Math.round(slowest.amount).toLocaleString("es-ES")} € pendientes a ${slowest.settlementDays} días.` });
  }
  alerts.push({ level: "Info", message: `Margen neto del mes: ${(input.pnl.netMarginPct * 100).toLocaleString("es-ES", { maximumFractionDigits: 1 })} %.` });
  for (const risk of input.agentRisks ?? []) alerts.push({ level: "Media", message: risk, fromAgent: true });
  return alerts;
}
