import type { LegalAnalysis } from "./api.ts";
import { marketLabel } from "./markets.ts";

// El «cumplimiento» lo decide el agente legal del backend sobre un dataset
// regulatorio simulado (legal_compliance.py). Este módulo NO evalúa requisitos:
// solo etiqueta, ordena y reexpresa lo que el análisis ya devolvió.

export type Recommendation = LegalAnalysis["recommendation"];

export interface LegalGate {
  title: string;
  detail: string;
  tone: "ok" | "warn" | "bad";
}

/** Estados del Legal Gate de la spec §8.11 (Bloqueado / Requiere revisión humana /
 * Preparado), traducidos desde la recomendación del agente. Nunca se dice
 * «100 % legal»: «Preparado» solo significa que el análisis simulado no bloquea. */
export function legalGate(recommendation: Recommendation): LegalGate {
  switch (recommendation) {
    case "NO_GO":
      return {
        title: "Bloqueado",
        detail: "No apto para lanzamiento hasta resolver los requisitos críticos.",
        tone: "bad",
      };
    case "REVIEW":
      return {
        title: "Requiere revisión humana",
        detail: "El análisis no puede darse por bueno sin que una persona revise los puntos pendientes.",
        tone: "warn",
      };
    case "GO":
      return {
        title: "Preparado",
        detail:
          "El análisis simulado no encuentra bloqueos. No es asesoría legal ni garantiza el cumplimiento: valida con un profesional.",
        tone: "ok",
      };
  }
}

/** El análisis no guarda si el usuario declaró las certificaciones; se deduce de
 * la regla del agente: exigiéndolas, solo devuelve GO si estaban disponibles. */
export function certificationsDeclared(analysis: Pick<LegalAnalysis, "recommendation" | "data">): boolean {
  const required = analysis.data?.required_certifications ?? [];
  return required.length > 0 && analysis.recommendation === "GO";
}

export interface RequirementRow {
  id: string;
  name: string;
  market: string;
  /** declared = el usuario dijo tenerla (sin documento que lo pruebe); pending = sin acreditar. */
  status: "declared" | "pending";
}

/** Un requisito por certificación exigida en el mercado del análisis. */
export function requirementRows(analysis: Pick<LegalAnalysis, "market" | "recommendation" | "data">): RequirementRow[] {
  const declared = certificationsDeclared(analysis);
  return (analysis.data?.required_certifications ?? []).map((name) => ({
    id: `${analysis.market}:${name}`,
    name,
    market: analysis.market,
    status: declared ? "declared" : "pending",
  }));
}

/** Motivos legibles del estado del Legal Gate, sacados de los datos del análisis. */
export function gateReasons(
  analysis: Pick<LegalAnalysis, "market" | "restricted" | "recommendation" | "data">,
): string[] {
  if (analysis.restricted === null) {
    return ["Sin datos regulatorios modelados para esta categoría y mercado: hace falta revisión manual."];
  }
  const reasons: string[] = [];
  const required = analysis.data?.required_certifications ?? [];
  if (analysis.restricted) {
    reasons.push(`Categoría restringida en ${marketLabel(analysis.market)}.`);
  }
  if (required.length > 0 && !certificationsDeclared(analysis)) {
    reasons.push(`Certificaciones sin acreditar: ${required.join(", ")}.`);
  }
  return reasons;
}

/** Cambios regulatorios del más reciente al más antiguo. */
export function changesNewestFirst(changes: { date: string; description: string }[] | undefined) {
  return [...(changes ?? [])].sort((a, b) => b.date.localeCompare(a.date));
}
