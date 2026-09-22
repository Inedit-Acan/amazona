import type { CFOReport } from "./api.ts";

// El informe del CFO es catalog-wide y sale de las decisiones económicas más
// recientes, las campañas y las reservas del BudgetEngine (cfo/service.py). No hay
// contabilidad, tesorería ni facturación: lo que la pantalla enseña lo calcula
// lib/cfo-view.ts. Aquí solo queda el veredicto del agente en lenguaje llano.

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
