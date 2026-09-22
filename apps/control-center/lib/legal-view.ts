import type { LegalAnalysis } from "./api.ts";
import {
  DEMO_CHANGES,
  DEMO_REQUIREMENTS,
  DEMO_RISKS,
  translateLegal,
  type Criticality,
  type RequirementStatus,
} from "./demo/legal.ts";
import { certificationsDeclared } from "./legal.ts";

// Vista de la pantalla de Legal (mockup docs/design/legal y cumplimiento.png).
// Real (agente legal, dataset simulado del backend): certificaciones exigidas,
// si se declararon disponibles, restricción, riesgos conocidos, cambios y la
// recomendación. Demo (lib/demo/legal.ts): el resto de la matriz de requisitos,
// estados, evidencias, riesgos con probabilidad × impacto y cambios adicionales.

export const CRITICALITY_ORDER: Criticality[] = ["Crítico", "Alto", "Medio", "Bajo"];

export interface RequirementRow {
  id: string;
  name: string;
  market: string;
  status: RequirementStatus;
  evidence: number;
  source: string;
  criticality: Criticality;
  /** true si la exige el agente legal (dato real). */
  fromAgent: boolean;
}

export type RiskLevel = "Crítico" | "Alto" | "Medio" | "Bajo";

export interface RiskRow {
  name: string;
  probability: 1 | 2 | 3;
  impact: 1 | 2 | 3 | 4;
  level: RiskLevel;
  fromAgent: boolean;
}

export interface ChangeRow {
  date: string;
  description: string;
  relevance: "crítico" | "relevante" | "informativo";
  fromAgent: boolean;
}

export type GateState = "blocked" | "review" | "ready";

export interface LegalView {
  requirements: RequirementRow[];
  compliance: { ok: number; total: number; ratio: number };
  certifications: { verified: number; pending: number };
  documents: { verified: number; pending: number; required: number };
  risks: RiskRow[];
  risk: { level: "Bajo" | "Medio" | "Alto"; critical: number; high: number };
  changes: ChangeRow[];
  relevantChanges: number;
  gate: { state: GateState; criticalOpen: number };
  actions: string[];
}

export function isRequirementOk(status: RequirementStatus): boolean {
  return status === "Verificado" || status === "No aplica";
}

export function riskLevel(probability: number, impact: number): RiskLevel {
  const score = probability * impact;
  return score >= 9 ? "Crítico" : score >= 6 ? "Alto" : score >= 3 ? "Medio" : "Bajo";
}

const ACTION_VERB: Record<RequirementStatus, string> = {
  Revisar: "Validar",
  Incompleto: "Completar",
  Pendiente: "Aportar",
  Verificado: "",
  "No aplica": "",
};

export function buildLegalView(market: string, analysis: LegalAnalysis | undefined): LegalView {
  const required = analysis?.data?.required_certifications ?? [];
  const declared = analysis ? certificationsDeclared(analysis) : true;

  const requirements: RequirementRow[] = (DEMO_REQUIREMENTS[market] ?? DEMO_REQUIREMENTS.eu).map((r, k) => {
    const fromAgent = Boolean(r.certification && required.includes(r.certification));
    return {
      id: `${market}:${k}`,
      name: r.name,
      market,
      // Si el agente la exige y no se declaró disponible, no puede estar verificada.
      status: fromAgent && !declared ? "Pendiente" : r.status,
      evidence: fromAgent && !declared ? 0 : r.evidence,
      source: fromAgent ? `${r.source} · agente legal` : r.source,
      criticality: r.criticality,
      fromAgent,
    };
  });
  // Certificaciones que exige el agente y la matriz de ejemplo no recoge.
  for (const code of required) {
    if (!requirements.some((r) => r.name.includes(code))) {
      requirements.unshift({
        id: `${market}:agent:${code}`,
        name: `Certificación ${code}`,
        market,
        status: declared ? "Revisar" : "Pendiente",
        evidence: 0,
        source: "Agente legal",
        criticality: "Crítico",
        fromAgent: true,
      });
    }
  }
  requirements.sort((a, b) => CRITICALITY_ORDER.indexOf(a.criticality) - CRITICALITY_ORDER.indexOf(b.criticality));

  const ok = requirements.filter((r) => isRequirementOk(r.status)).length;
  const open = requirements.filter((r) => !isRequirementOk(r.status));
  const certs = requirements.filter((r) => r.fromAgent || /CE|RoHS|REACH|WEEE|FCC|NOM/.test(r.name));
  const verifiedDocs = requirements.filter((r) => r.status === "Verificado").reduce((s, r) => s + r.evidence, 0);

  const risks: RiskRow[] = (DEMO_RISKS[market] ?? DEMO_RISKS.eu).map((r) => ({
    ...r,
    level: riskLevel(r.probability, r.impact),
    fromAgent: false,
  }));
  if (analysis?.restricted) {
    risks.unshift({ name: "Categoría restringida en este mercado", probability: 3, impact: 4, level: "Crítico", fromAgent: true });
  }
  for (const text of analysis?.data?.known_risks ?? []) {
    risks.push({ name: translateLegal(text), probability: 2, impact: 3, level: riskLevel(2, 3), fromAgent: true });
  }
  risks.sort((a, b) => b.probability * b.impact - a.probability * a.impact);
  const avgRisk = risks.length ? risks.reduce((s, r) => s + r.probability * r.impact, 0) / risks.length : 0;

  const changes: ChangeRow[] = [
    ...(DEMO_CHANGES[market] ?? []).map((c) => ({ ...c, fromAgent: false })),
    ...(analysis?.data?.recent_changes ?? []).map((c) => ({
      date: c.date,
      description: translateLegal(c.description),
      relevance: "relevante" as const,
      fromAgent: true,
    })),
  ].sort((a, b) => b.date.localeCompare(a.date));

  const criticalOpen = open.filter((r) => r.criticality === "Crítico").length;
  const state: GateState =
    analysis?.recommendation === "NO_GO" || analysis?.restricted || criticalOpen > 0
      ? "blocked"
      : analysis?.recommendation === "REVIEW" || open.length > 0
        ? "review"
        : "ready";

  return {
    requirements,
    compliance: { ok, total: requirements.length, ratio: requirements.length ? ok / requirements.length : 0 },
    certifications: {
      verified: certs.filter((r) => r.status === "Verificado").length,
      pending: certs.filter((r) => !isRequirementOk(r.status)).length,
    },
    documents: { verified: verifiedDocs, pending: open.length, required: verifiedDocs + open.length },
    risks,
    risk: {
      level: avgRisk >= 8 ? "Alto" : avgRisk >= 4 ? "Medio" : "Bajo",
      critical: risks.filter((r) => r.level === "Crítico").length,
      high: risks.filter((r) => r.level === "Alto").length,
    },
    changes,
    relevantChanges: changes.filter((c) => c.relevance !== "informativo").length,
    gate: { state, criticalOpen },
    actions: open.slice(0, 3).map((r) => `${ACTION_VERB[r.status]} ${r.name.charAt(0).toLowerCase()}${r.name.slice(1)}`),
  };
}
