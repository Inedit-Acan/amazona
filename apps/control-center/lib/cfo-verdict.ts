import type { CFOReport } from "./api.ts";

// La evaluación del agente CFO (M45, Commit 10).
//
// Es un VEREDICTO sobre los análisis del catálogo y las reservas del BudgetEngine, no un hecho contable: no sale del
// registro de pagos ni de ninguna contabilidad. Por eso vive en su propio bloque, separado de las magnitudes
// financieras, y por eso el título dice siempre con cuánta información se emitió.
//
// Si le faltan datos esenciales, lo dice: «Evaluación CFO — información parcial», nunca «rentabilidad confirmada».

export type InformationLevel = "complete" | "partial" | "insufficient";

export interface VerdictView {
  /** «Evaluación CFO — información completa / parcial / insuficiente». */
  title: string;
  level: InformationLevel;
  /** El veredicto en lenguaje llano. */
  status: string;
  detail: string;
  tone: "ok" | "warn" | "bad";
  /** La confianza que declara el propio agente, en tanto por uno. */
  confidence: number;
  /** Qué miró para decidir, con su valor tal como lo dio. */
  inputs: { label: string; value: string }[];
  /** Qué le faltaba y es relevante para lo que afirma. */
  missing: string[];
  /** De dónde sale esto, dicho sin rodeos. */
  source: string;
}

const STATUS: Record<CFOReport["financial_health_status"], { status: string; detail: string; tone: VerdictView["tone"] }> = {
  HEALTHY: {
    status: "Saludable",
    detail: "Pocas decisiones NO_GO y el presupuesto no está cerca de su límite.",
    tone: "ok",
  },
  AT_RISK: {
    status: "En riesgo",
    detail: "Hay una proporción elevada de decisiones NO_GO o el presupuesto está cerca de agotarse.",
    tone: "warn",
  },
  CRITICAL: {
    status: "Crítica",
    detail: "Más de la mitad de los productos analizados son NO_GO.",
    tone: "bad",
  },
  NEEDS_REVIEW: {
    status: "Requiere revisión",
    detail: "Faltan datos para valorar la salud financiera: todavía no hay análisis económicos en el catálogo.",
    tone: "warn",
  },
};

const LEVEL_LABEL: Record<InformationLevel, string> = {
  complete: "información completa",
  partial: "información parcial",
  insufficient: "información insuficiente",
};

export const VERDICT_SOURCE =
  "Evaluación del agente CFO sobre los análisis económicos del catálogo y las reservas del presupuesto. " +
  "No procede del registro financiero: no es contabilidad y no confirma rentabilidad.";

/** Lo que al agente le falta para que su veredicto sea más que una orientación. */
function missingOf(report: CFOReport): string[] {
  const data = report.data;
  const missing: string[] = [];
  if (data === null) {
    return ["El informe no trae ningún dato de apoyo."];
  }
  if (data.total_products_analyzed === 0) missing.push("Ningún producto analizado.");
  if (data.no_go_ratio === null) missing.push("Proporción de decisiones NO_GO no calculada.");
  if (data.budget_utilization === null) missing.push("Uso del presupuesto no calculado.");
  // Lo que el agente nunca ve, y conviene decir en voz alta junto a su veredicto.
  missing.push("No ve el registro de pagos: su veredicto no incluye ingresos ni reembolsos verificados.");
  missing.push("No ve costes efectivamente pagados, impuestos, caja ni comisiones.");
  return missing;
}

function levelOf(report: CFOReport): InformationLevel {
  const data = report.data;
  if (data === null || data.total_products_analyzed === 0) return "insufficient";
  if (data.no_go_ratio === null || data.budget_utilization === null) return "partial";
  return "partial"; // nunca «completa»: el agente no ve el registro de pagos ni los costes efectivamente pagados
}

const percent = (fraction: number) => `${Math.round(fraction * 100)} %`;

export function verdictView(report: CFOReport): VerdictView {
  const status = STATUS[report.financial_health_status];
  const level = levelOf(report);
  const data = report.data;
  const inputs: { label: string; value: string }[] = [];
  if (data !== null) {
    inputs.push({ label: "Productos analizados", value: String(data.total_products_analyzed) });
    inputs.push({ label: "GO / REVIEW / NO_GO", value: `${data.go_count} / ${data.review_count} / ${data.no_go_count}` });
    if (data.no_go_ratio !== null) inputs.push({ label: "Proporción NO_GO", value: percent(data.no_go_ratio) });
    if (data.budget_utilization !== null) inputs.push({ label: "Uso del presupuesto", value: percent(data.budget_utilization) });
    inputs.push({ label: "Campañas activas", value: `${data.active_campaigns} de ${data.total_campaigns}` });
  }
  return {
    title: `Evaluación CFO — ${LEVEL_LABEL[level]}`,
    level,
    status: status.status,
    detail: status.detail,
    tone: status.tone,
    confidence: report.confidence,
    inputs,
    missing: missingOf(report),
    source: VERDICT_SOURCE,
  };
}

/** Sin informe no hay veredicto: no se inventa uno neutro. */
export const NO_VERDICT_TEXT = "El agente CFO no ha emitido ninguna evaluación todavía.";
