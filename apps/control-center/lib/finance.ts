import type { CFOReport, EconomicAnalysis, Product } from "./api.ts";

// El informe del CFO es catalog-wide y sale de las decisiones económicas más
// recientes, las campañas y las reservas del BudgetEngine (cfo/service.py). No hay
// contabilidad, tesorería ni facturación. Este módulo NO calcula P&L, caja ni
// forecast: solo ordena y reexpresa lo que el informe y los análisis ya dicen.

export type CFOData = NonNullable<CFOReport["data"]>;

export interface BudgetBreakdown {
  limit: number;
  reserved: number;
  committed: number;
  spent: number;
  /** Límite menos lo ya usado (reservado + comprometido + gastado); nunca negativo. */
  available: number;
  /** Uso sobre el límite; null si no hay límite registrado. */
  utilization: number | null;
  /** El uso supera el límite. */
  overLimit: boolean;
}

/** Presupuesto global (spec §4.7) con los mismos totales que usa el agente. */
export function budgetBreakdown(
  data: Pick<CFOData, "total_budget_hard_limit" | "total_reserved" | "total_committed" | "total_spent">,
): BudgetBreakdown {
  const limit = data.total_budget_hard_limit;
  const used = data.total_reserved + data.total_committed + data.total_spent;
  return {
    limit,
    reserved: data.total_reserved,
    committed: data.total_committed,
    spent: data.total_spent,
    available: Math.max(0, limit - used),
    utilization: limit > 0 ? used / limit : null,
    overLimit: limit > 0 && used > limit,
  };
}

export interface PortfolioRow {
  productId: string;
  name: string;
  category: string;
  salePrice: number;
  marginPercent: number;
  /** Beneficio mensual del escenario base (estimado por el agente económico). */
  monthlyProfit: number | null;
  recommendation: EconomicAnalysis["recommendation"];
}

/** Última decisión económica de cada producto, de mayor a menor beneficio base
 * (los que no tienen escenario base van al final). `analysesByProduct` guarda los
 * análisis de cada producto del más reciente al más antiguo, como los devuelve la API. */
export function portfolioRows(
  products: Pick<Product, "id" | "name" | "category">[],
  analysesByProduct: Record<string, Pick<EconomicAnalysis, "sale_price" | "margin_percent" | "recommendation" | "data">[]>,
): PortfolioRow[] {
  const rows: PortfolioRow[] = [];
  for (const product of products) {
    const latest = analysesByProduct[product.id]?.[0];
    if (!latest) continue;
    rows.push({
      productId: product.id,
      name: product.name,
      category: product.category,
      salePrice: latest.sale_price,
      marginPercent: latest.margin_percent,
      monthlyProfit: latest.data?.scenarios?.base?.monthly_profit ?? null,
      recommendation: latest.recommendation,
    });
  }
  return rows.sort((a, b) => {
    if (a.monthlyProfit === null && b.monthlyProfit === null) return a.name.localeCompare(b.name, "es");
    if (a.monthlyProfit === null) return 1;
    if (b.monthlyProfit === null) return -1;
    return b.monthlyProfit - a.monthlyProfit;
  });
}

export interface FinancialVerdict {
  title: string;
  detail: string;
  tone: "ok" | "warn" | "bad";
}

/** Estado de salud financiera del agente (`financial_health_status`) en lenguaje llano. */
export const FINANCIAL_VERDICT: Record<CFOReport["financial_health_status"], FinancialVerdict> = {
  HEALTHY: {
    title: "Saludable",
    detail: "Pocas decisiones NO_GO y el presupuesto no está cerca de su límite.",
    tone: "ok",
  },
  AT_RISK: {
    title: "En riesgo",
    detail: "Hay una proporción elevada de decisiones NO_GO o el presupuesto está cerca de agotarse.",
    tone: "warn",
  },
  CRITICAL: {
    title: "Crítica",
    detail: "Más de la mitad de los productos analizados son NO_GO.",
    tone: "bad",
  },
  NEEDS_REVIEW: {
    title: "Requiere revisión",
    detail: "Faltan datos para valorar la salud financiera: todavía no hay análisis económicos en el catálogo.",
    tone: "warn",
  },
};

/** Reglas que el agente aplica hoy (cfo.py). Documentación fija del backend. */
export const CFO_RULES: { rule: string; result: string }[] = [
  { rule: "Más del 50 % de los productos analizados son NO_GO", result: "Crítica" },
  { rule: "Más del 20 % son NO_GO, o el presupuesto usa más del 90 % del límite", result: "En riesgo" },
  { rule: "Ningún análisis económico en el catálogo", result: "Requiere revisión" },
  { rule: "Resto de casos", result: "Saludable" },
];
