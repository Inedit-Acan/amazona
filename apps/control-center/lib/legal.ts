import type { LegalAnalysis } from "./api.ts";

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
