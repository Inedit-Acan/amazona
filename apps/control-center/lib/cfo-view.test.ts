import assert from "node:assert/strict";
import { test } from "node:test";
import { BUDGET_CATEGORIES, DEMO_ANNUAL_BUDGET, DEMO_SOFTWARE_MONTHLY, DEMO_TAX_RATE } from "./demo/cfo.ts";
import {
  budgetView,
  buildPnl,
  cashFlowSeries,
  cashWarning,
  deviations,
  dimensionRows,
  financialAlerts,
  financialHealth,
  forecast,
  payables,
  receivables,
  monthFactor,
  runwayMonths,
  scalePnl,
  taxView,
  withDeltas,
  treasury,
  upcomingWeek,
  workingCapital,
  type ProductFinance,
} from "./cfo-view.ts";
import type { EconomicsInputs } from "./economics-model.ts";
import { buildOrders, startOfDay, type ProductInput, type SupplierInput } from "./operations-view.ts";

const INPUTS: EconomicsInputs = {
  salePrice: 29.9,
  supplierCost: 8.4,
  transport: 2.09,
  tariff: 0.37,
  fulfillment: 0.75,
  paymentFeePct: 2.9,
  returnsPct: 4,
  cac: 3.2,
  otherCosts: 0.4,
  conversionPct: 2.8,
  monthlyOrders: 300,
  monthlyFixedCosts: 1000,
  initialInvestment: 5245,
};

const PRODUCTS: ProductFinance[] = [
  { id: "p1", name: "LED strip lights", category: "home", inputs: INPUTS, isDemo: false },
  { id: "p2", name: "Collapsible laundry basket", category: "home", inputs: { ...INPUTS, salePrice: 18.5, monthlyOrders: 200 }, isDemo: true },
];

const PNL = buildPnl(PRODUCTS);

test("buildPnl: ingresos, margen bruto, EBITDA y resultado cuadran entre sí", () => {
  assert.equal(PNL.revenue, 29.9 * 300 + 18.5 * 200);
  assert.equal(PNL.grossMargin, Math.round((PNL.revenue - PNL.cogs) * 100) / 100);
  assert.ok(Math.abs(PNL.ebitda - (PNL.grossMargin - PNL.operatingCosts)) < 0.02);
  assert.ok(Math.abs(PNL.tax - PNL.ebitda * DEMO_TAX_RATE) < 0.02);
  assert.ok(Math.abs(PNL.net - (PNL.ebitda - PNL.tax)) < 0.02);
  assert.ok(Math.abs(PNL.netMarginPct - PNL.net / PNL.revenue) < 1e-6);
  // Software es un coste de empresa, no por producto.
  assert.equal(PNL.costByCategory.software, DEMO_SOFTWARE_MONTHLY);
  // Marketing = CAC × pedidos, el mismo supuesto que usa la pantalla de Marketing.
  assert.equal(PNL.costByCategory.marketing, 3.2 * 500);
});

test("buildPnl: las filas llevan signo y los totales no inventan variación", () => {
  const byKey = Object.fromEntries(PNL.rows.map((r) => [r.key, r]));
  assert.ok(byKey.revenue.amount > 0 && byKey.cogs.amount < 0 && byKey.marketing.amount < 0);
  for (const key of ["gross", "ebitda", "net"]) assert.equal(byKey[key].delta, null);
  assert.equal(byKey.revenue.delta, null, "buildPnl no inventa variaciones");
  const previous = scalePnl(PNL, 0.8, 0.9);
  const withVariation = withDeltas(PNL, previous);
  const revenueRow = withVariation.rows.find((r) => r.key === "revenue")!;
  assert.ok(Math.abs(revenueRow.delta! - (1 / 0.8 - 1)) < 1e-6);
  assert.equal(withVariation.rows.find((r) => r.key === "net")!.delta, null);
  assert.deepEqual(buildPnl(PRODUCTS).rows, PNL.rows, "determinista");
  const empty = buildPnl([]);
  assert.equal(empty.revenue, 0);
  assert.equal(empty.netMarginPct, 0);
});

test("scalePnl y monthFactor: la misma cuenta a otra escala, recalculando totales", () => {
  const half = scalePnl(PNL, 0.5, 0.5);
  assert.equal(half.revenue, Math.round(PNL.revenue * 0.5 * 100) / 100);
  assert.ok(Math.abs(half.grossMargin - (half.revenue - half.cogs)) < 0.02);
  assert.ok(Math.abs(half.net - (half.ebitda - half.tax)) < 0.02);
  assert.equal(half.rows.find((r) => r.key === "net")!.amount, half.net);
  assert.equal(scalePnl(PNL, 1, 1), PNL);
  // Un mes anterior encoge y uno futuro crece.
  assert.ok(monthFactor(-2, "revenue") < monthFactor(2, "revenue"));
  assert.equal(monthFactor(0, "revenue"), monthFactor(0, "revenue"));
  assert.ok(monthFactor(3, "costs") > 1);
});

test("cashFlowSeries: mitad pasado y mitad forecast, con saldo acumulado", () => {
  const series = cashFlowSeries(PNL, 24680, 6, 8);
  assert.equal(series.length, 6);
  assert.equal(series.filter((m) => m.forecast).length, 3);
  assert.equal(series.find((m) => m.offset === 0)!.forecast, false);
  // El saldo del mes en curso es la caja que se le pasa y ninguno es negativo.
  assert.ok(Math.abs(series.find((m) => m.offset === 0)!.balance - 24680) < 0.02);
  assert.ok(series.every((m) => m.balance > 0));
  // El forecast acumula el resultado de cada mes sobre la caja actual.
  for (const month of series.filter((m) => m.forecast)) {
    const previous = series[series.indexOf(month) - 1];
    assert.ok(Math.abs(month.balance - (previous.balance + month.inflow - month.outflow)) < 0.02);
  }
  assert.deepEqual(series.map((m) => m.label).slice(0, 3), ["Jul", "Ago", "Sep"]);
  assert.equal(cashFlowSeries(PNL, 24680, 12, 8).length, 12);
});

test("cashWarning: avisa del primer mes futuro por debajo de un mes de gastos", () => {
  const series = cashFlowSeries(PNL, 1000, 6, 8);
  const warning = cashWarning(series, PNL.spend);
  if (warning) assert.ok(warning.forecast && warning.balance < PNL.spend);
  assert.equal(cashWarning(cashFlowSeries(PNL, 10_000_000, 6, 8), PNL.spend), null);
});

test("budgetView: usa el límite del BudgetEngine si existe y reparte el gasto por categoría", () => {
  const demo = budgetView(PNL, 9);
  assert.equal(demo.isReal, false);
  assert.equal(demo.annual, DEMO_ANNUAL_BUDGET);
  assert.deepEqual(demo.lines.map((l) => l.key), BUDGET_CATEGORIES.map((c) => c.key));
  assert.equal(demo.lines.find((l) => l.key === "marketing")!.spent, Math.round(PNL.costByCategory.marketing * 9 * 100) / 100);
  assert.ok(demo.usage > 0);

  const report = {
    correlation_id: "c",
    financial_health_status: "HEALTHY" as const,
    recommendation: "GO" as const,
    confidence: 0.9,
    data: {
      no_go_ratio: 0,
      budget_utilization: 0.2,
      total_products_analyzed: 2,
      go_count: 2,
      review_count: 0,
      no_go_count: 0,
      total_campaigns: 1,
      active_campaigns: 1,
      total_daily_budget: 20,
      total_budget_hard_limit: 200_000,
      total_reserved: 1000,
      total_committed: 500,
      total_spent: 250,
    },
  };
  const real = budgetView(PNL, 9, report);
  assert.equal(real.isReal, true);
  assert.equal(real.annual, 200_000);
  assert.equal(real.lines.find((l) => l.key === "reserve")!.spent, 1500);
  // Los límites por categoría se escalan al límite real.
  assert.equal(real.lines.find((l) => l.key === "marketing")!.limit, Math.round((35000 * 200000) / DEMO_ANNUAL_BUDGET * 100) / 100);
});

test("deviations: compara el gasto del mes con la doceava parte del presupuesto", () => {
  const budget = budgetView(PNL, 9);
  const rows = deviations(PNL, budget);
  assert.ok(rows.every((r) => r.key !== "reserve"));
  const marketing = rows.find((r) => r.key === "marketing")!;
  const limit = budget.lines.find((l) => l.key === "marketing")!.limit;
  assert.ok(Math.abs(marketing.deviation - (PNL.costByCategory.marketing / (limit / 12) - 1)) < 1e-9);
  for (let k = 1; k < rows.length; k++) assert.ok(Math.abs(rows[k - 1].deviation) >= Math.abs(rows[k].deviation));
});

// --- Cobros, pagos y capital de trabajo ------------------------------------------

const TODAY = "2026-09-22";
const SUPPLIERS: SupplierInput[] = [
  { id: "sup-cn", name: "Foshan Home Goods Co", region: "china", leadTimeDays: 30, reliability: 0.79, verified: true, isDemo: false },
  { id: "sup-eu", name: "Bratislava Homeware Supply", region: "eu", leadTimeDays: 10, reliability: 0.9, verified: true, isDemo: false },
];
const ORDER_PRODUCTS: ProductInput[] = [
  { id: "p1", name: "LED strip lights", sku: "AMZ-HOM-P1", price: 29.9, suppliers: SUPPLIERS },
  { id: "p2", name: "Collapsible laundry basket", sku: "AMZ-HOM-P2", price: 18.5, suppliers: SUPPLIERS },
];
const ORDERS = buildOrders(ORDER_PRODUCTS, TODAY);
const NOW = startOfDay(TODAY);

test("receivables: agrupa por plataforma de pago y calcula el plazo medio", () => {
  const { rows, total, averageDays } = receivables(ORDERS, NOW);
  assert.ok(rows.length > 0);
  assert.ok(rows.every((r) => r.amount > 0));
  assert.equal(total, Math.round(rows.reduce((s, r) => s + r.amount, 0) * 100) / 100);
  assert.ok(averageDays > 0 && averageDays <= 14);
  assert.deepEqual(receivables([], NOW), { rows: [], total: 0, averageDays: 0 });
});

test("payables: proveedores de pedidos abiertos, publicidad y gastos fijos, por vencimiento", () => {
  const rows = payables(ORDERS, PNL, NOW);
  assert.ok(rows.some((r) => r.key === "sup-cn" || r.key === "sup-eu"));
  assert.ok(rows.some((r) => r.key === "meta") && rows.some((r) => r.key === "aws"));
  for (let k = 1; k < rows.length; k++) assert.ok(rows[k - 1].dueInDays <= rows[k].dueInDays);
  assert.ok(rows.every((r) => r.amount > 0));
});

test("treasury y upcomingWeek: liquidez total y movimientos de la semana", () => {
  const { total: receivableTotal } = receivables(ORDERS, NOW);
  const t = treasury(receivableTotal);
  assert.equal(t.total, Math.round((t.operating + t.reserve + t.stripe + t.paypal) * 100) / 100);
  const week = upcomingWeek(PNL, receivableTotal);
  assert.equal(week.lines.length, 4);
  assert.ok(week.lines[0].amount > 0 && week.lines.slice(1).every((l) => l.amount < 0));
  assert.equal(week.net, Math.round(week.lines.reduce((s, l) => s + l.amount, 0) * 100) / 100);
});

test("workingCapital: la cobertura nunca pasa de 1 y el descubierto es el resto", () => {
  const covered = workingCapital(1000, 1200);
  assert.equal(covered.coverage, 1);
  assert.equal(covered.uncovered, 0);
  const partial = workingCapital(1000, 400);
  assert.equal(partial.covered, 400);
  assert.equal(partial.uncovered, 600);
  assert.equal(partial.inRange, false);
});

// --- Forecast, dimensiones, salud, fiscalidad y alertas ----------------------------

test("forecast: usa los escenarios reales del análisis y crece mes a mes", () => {
  const withAnalysis: ProductFinance[] = [
    {
      ...PRODUCTS[0],
      analysis: {
        correlation_id: "c",
        product_id: "p1",
        supplier_quote_id: "q",
        sale_price: 50,
        monthly_fixed_costs: 500,
        margin_percent: 0.93,
        recommendation: "GO",
        confidence: 0.85,
        data: {
          scenarios: {
            conservative: { monthly_unit_sales: 186, margin_percent: 0.93, monthly_revenue: 9318.75, monthly_profit: 8197 },
            base: { monthly_unit_sales: 266, margin_percent: 0.93, monthly_revenue: 13312.5, monthly_profit: 11924.29 },
            optimistic: { monthly_unit_sales: 346, margin_percent: 0.93, monthly_revenue: 17306.25, monthly_profit: 15651.58 },
          },
        },
      },
    },
  ];
  const base = forecast(withAnalysis, "base", 6, 8);
  assert.equal(base.length, 6);
  assert.equal(base[0].revenue, 13312.5);
  assert.equal(base[0].costs, Math.round((13312.5 - 11924.29) * 100) / 100);
  assert.ok(base[5].revenue > base[0].revenue);
  assert.ok(forecast(withAnalysis, "conservative", 6, 8)[0].revenue < base[0].revenue);
  // Sin análisis real se usan los escenarios del mismo modelo que Economía.
  const modelled = forecast(PRODUCTS, "base", 3, 8);
  assert.equal(modelled[0].revenue, PNL.revenue);
});

test("dimensionRows: ingresos por producto, canal, mercado y proveedor", () => {
  const label = (market: string) => ({ eu: "España + UE", us: "Estados Unidos", mx: "México" })[market] ?? market;
  const products = dimensionRows(ORDERS, "products", label);
  const total = Math.round(ORDERS.reduce((s, o) => s + o.amount, 0) * 100) / 100;
  assert.ok(Math.abs(products.reduce((s, r) => s + r.value, 0) - total) < 1);
  for (let k = 1; k < products.length; k++) assert.ok(products[k - 1].value >= products[k].value);
  assert.ok(dimensionRows(ORDERS, "markets", label).every((r) => r.label.length > 2));
  assert.ok(dimensionRows(ORDERS, "suppliers", label).some((r) => r.label.includes("Foshan")));
  assert.deepEqual(dimensionRows([], "channels", label), []);
});

test("runwayMonths y financialHealth: siete ejes 0–100 y score medio", () => {
  const loss = { ...PNL, spend: PNL.revenue + 1000 };
  assert.ok(Math.abs(runwayMonths(10000, loss) - 10) < 0.01);
  assert.ok(runwayMonths(10000, PNL) > 0);

  const budget = budgetView(PNL, 9);
  const series = cashFlowSeries(PNL, 24680, 6, 8);
  const health = financialHealth({
    pnl: PNL,
    cash: 24680,
    budget,
    working: workingCapital(5000, 4000),
    cashSeries: series,
    taxProvision: PNL.tax,
  });
  assert.equal(health.axes.length, 7);
  assert.ok(health.axes.every((a) => a.value >= 0 && a.value <= 100));
  assert.equal(health.score, Math.round(health.axes.reduce((s, a) => s + a.value, 0) / 7));
  assert.ok(["Excelente", "Buena", "Aceptable", "Requiere atención"].includes(health.label));
});

test("taxView: IVA sobre el valor añadido, sociedades del EBITDA y próximo trimestre", () => {
  const view = taxView(PNL, 8, 0.94);
  assert.equal(view.corporate, PNL.tax);
  assert.ok(view.vat > 0);
  assert.equal(view.nextDueMonth, 9);
  assert.equal(taxView(PNL, 10, 0.94).nextDueMonth, 12);
  assert.equal(view.docsReady, 0.94);
});

test("financialAlerts: prioriza la desviación grave y siempre informa del margen", () => {
  const budget = budgetView(PNL, 9);
  const alerts = financialAlerts({
    deviations: deviations(PNL, budget),
    budget,
    receivables: receivables(ORDERS, NOW),
    pnl: PNL,
    monthsElapsed: 9,
  });
  assert.ok(alerts.length >= 2);
  assert.equal(alerts.at(-1)!.level, "Info");
  assert.ok(alerts.at(-1)!.message.includes("Margen neto"));
});
