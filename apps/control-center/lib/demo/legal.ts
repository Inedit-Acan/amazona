// DATOS DE DEMOSTRACIÓN — pantalla de Legal y cumplimiento.
//
// Valores inventados (con permiso del propietario, 22-09-2026) para que el
// panel se vea como el mockup mientras el backend no los proporciona. NO son
// requisitos legales reales ni asesoría legal. Sustituir cuando existan los
// endpoints (docs/design/AMAZONA_estado_paneles_rediseno.md, sección 3).

export type Criticality = "Crítico" | "Alto" | "Medio" | "Bajo";
export type RequirementStatus = "Verificado" | "Revisar" | "Incompleto" | "No aplica" | "Pendiente";

export interface DemoRequirement {
  name: string;
  criticality: Criticality;
  status: RequirementStatus;
  /** Documentos de evidencia adjuntos. */
  evidence: number;
  source: string;
  /** Código de certificación que exige el agente legal (CE, RoHS, FCC…), si lo es. */
  certification?: string;
}

export const DEMO_REQUIREMENTS: Record<string, DemoRequirement[]> = {
  eu: [
    { name: "Seguridad general de productos (GPSR)", criticality: "Crítico", status: "Verificado", evidence: 4, source: "Comisión Europea" },
    { name: "Marcado CE", criticality: "Crítico", status: "Revisar", evidence: 2, source: "Proveedor", certification: "CE" },
    { name: "RoHS (2011/65/UE)", criticality: "Alto", status: "Verificado", evidence: 1, source: "Proveedor + ECHA", certification: "RoHS" },
    { name: "REACH (Reg. 1907/2006)", criticality: "Alto", status: "Verificado", evidence: 1, source: "ECHA", certification: "REACH" },
    { name: "Etiquetado e instrucciones", criticality: "Alto", status: "Incompleto", evidence: 0, source: "UE" },
    { name: "WEEE (2012/19/UE)", criticality: "Medio", status: "Verificado", evidence: 1, source: "Comisión Europea", certification: "WEEE" },
    { name: "Baterías (2006/66/CE)", criticality: "Medio", status: "No aplica", evidence: 0, source: "UE" },
    { name: "Manual de usuario (ES)", criticality: "Medio", status: "Pendiente", evidence: 0, source: "Proveedor" },
    { name: "Información ecommerce", criticality: "Medio", status: "Verificado", evidence: 1, source: "Agente legal" },
    { name: "Política de devoluciones", criticality: "Bajo", status: "Verificado", evidence: 1, source: "AMAZONA" },
  ],
  us: [
    { name: "FCC Parte 15 (emisiones)", criticality: "Crítico", status: "Revisar", evidence: 1, source: "FCC", certification: "FCC" },
    { name: "Seguridad de producto (CPSC)", criticality: "Alto", status: "Verificado", evidence: 2, source: "CPSC" },
    { name: "Baterías de litio (UN 38.3)", criticality: "Alto", status: "Verificado", evidence: 1, source: "Proveedor" },
    { name: "Proposición 65 (California)", criticality: "Alto", status: "Pendiente", evidence: 0, source: "OEHHA" },
    { name: "Etiquetado (FTC)", criticality: "Medio", status: "Verificado", evidence: 1, source: "FTC" },
    { name: "Política de devoluciones", criticality: "Bajo", status: "Verificado", evidence: 1, source: "AMAZONA" },
  ],
  mx: [
    { name: "Norma Oficial Mexicana (NOM)", criticality: "Crítico", status: "Pendiente", evidence: 0, source: "Secretaría de Economía", certification: "NOM" },
    { name: "Etiquetado comercial (NOM-024)", criticality: "Alto", status: "Incompleto", evidence: 0, source: "Secretaría de Economía" },
    { name: "Homologación inalámbrica (IFT)", criticality: "Alto", status: "Pendiente", evidence: 0, source: "IFT" },
    { name: "Información comercial", criticality: "Medio", status: "Verificado", evidence: 1, source: "PROFECO" },
    { name: "Garantía y devoluciones", criticality: "Bajo", status: "Verificado", evidence: 1, source: "PROFECO" },
  ],
};

export interface DemoRisk {
  name: string;
  /** 1 = baja … 3 = alta. */
  probability: 1 | 2 | 3;
  /** 1 = bajo … 4 = crítico. */
  impact: 1 | 2 | 3 | 4;
}

export const DEMO_RISKS: Record<string, DemoRisk[]> = {
  eu: [
    { name: "Declaración de conformidad no validada", probability: 3, impact: 4 },
    { name: "Responsable económico UE por confirmar", probability: 2, impact: 3 },
    { name: "Manual solo en inglés", probability: 2, impact: 2 },
    { name: "Riesgo bajo en Safety Gate", probability: 1, impact: 1 },
  ],
  us: [
    { name: "Etiqueta FCC sin validar", probability: 2, impact: 4 },
    { name: "Aviso Prop 65 ausente", probability: 2, impact: 3 },
    { name: "Reclamaciones por garantía", probability: 1, impact: 2 },
  ],
  mx: [
    { name: "Certificado NOM ausente", probability: 3, impact: 4 },
    { name: "Etiquetado en español incompleto", probability: 3, impact: 2 },
    { name: "Retención en aduana", probability: 2, impact: 3 },
  ],
};

export interface DemoSource {
  name: string;
  flag?: "eu" | "es" | "mx";
  status: string;
  ok: boolean;
  lastCheck: string;
}

export const DEMO_SOURCES: Record<string, DemoSource[]> = {
  eu: [
    { name: "Comisión Europea", flag: "eu", status: "Sin incidencias", ok: true, lastCheck: "hace 12 min" },
    { name: "Access2Markets", flag: "eu", status: "{n} requisitos aplicables", ok: false, lastCheck: "hace 14 min" },
    { name: "ECHA (REACH/SCIP)", status: "Sin incidencias", ok: true, lastCheck: "hace 16 min" },
    { name: "Safety Gate", status: "0 coincidencias", ok: true, lastCheck: "hace 16 min" },
    { name: "Legislación nacional (ES)", flag: "es", status: "3 requisitos adicionales", ok: false, lastCheck: "hace 19 min" },
  ],
  us: [
    { name: "FCC", status: "{n} requisitos aplicables", ok: false, lastCheck: "hace 10 min" },
    { name: "CPSC Recalls", status: "0 coincidencias", ok: true, lastCheck: "hace 12 min" },
    { name: "OEHHA (Prop 65)", status: "1 aviso aplicable", ok: false, lastCheck: "hace 15 min" },
  ],
  mx: [
    { name: "Secretaría de Economía (NOM)", flag: "mx", status: "{n} requisitos aplicables", ok: false, lastCheck: "hace 11 min" },
    { name: "IFT", flag: "mx", status: "Homologación requerida", ok: false, lastCheck: "hace 13 min" },
    { name: "PROFECO", flag: "mx", status: "Sin incidencias", ok: true, lastCheck: "hace 18 min" },
  ],
};

export type RoleAnswer = "Sí" | "No" | "Posible";

export const DEMO_ROLES: { role: string; answer: RoleAnswer }[] = [
  { role: "Fabricante", answer: "No" },
  { role: "Importador", answer: "Posible" },
  { role: "Distribuidor", answer: "Sí" },
  { role: "Vendedor al consumidor", answer: "Sí" },
  { role: "Marketplace", answer: "No" },
  { role: "Representante autorizado", answer: "No" },
];

export const DEMO_RESPONSIBILITIES = {
  supplier: ["Documentación técnica", "Conformidad", "Producto seguro"],
  amazona: ["Vendedor / posible importador", "Información al consumidor", "Devoluciones y garantías"],
  customer: ["Uso seguro", "Derechos de consumidor", "Reclamaciones"],
};

export interface DemoChange {
  date: string;
  description: string;
  relevance: "crítico" | "relevante" | "informativo";
}

export const DEMO_CHANGES: Record<string, DemoChange[]> = {
  eu: [
    { date: "2026-09-17", description: "Sin cambios críticos", relevance: "informativo" },
    { date: "2026-09-12", description: "Nueva guía sobre productos electrónicos (UE)", relevance: "relevante" },
    { date: "2026-09-04", description: "Actualización REACH: sustancias", relevance: "informativo" },
  ],
  us: [{ date: "2026-09-10", description: "Aclaración FCC sobre etiquetado electrónico", relevance: "relevante" }],
  mx: [{ date: "2026-09-08", description: "Consulta pública sobre etiquetado NOM-024", relevance: "relevante" }],
};

export interface DemoDocument {
  name: string;
  status: "Verificado" | "Requiere revisión" | "Pendiente";
  date?: string;
}

export const DEMO_DOCUMENTS: Record<string, DemoDocument[]> = {
  eu: [
    { name: "Declaration_of_Conformity.pdf", status: "Verificado", date: "12/09/2026" },
    { name: "RoHS_Report.pdf", status: "Verificado", date: "10/09/2026" },
    { name: "Test_Report_2024.pdf", status: "Requiere revisión" },
    { name: "Manual_ES.pdf", status: "Pendiente" },
    { name: "Packaging_Label.pdf", status: "Verificado", date: "08/09/2026" },
  ],
  us: [
    { name: "FCC_Test_Report.pdf", status: "Requiere revisión" },
    { name: "UN38.3_Summary.pdf", status: "Verificado", date: "05/09/2026" },
    { name: "Prop65_Warning.pdf", status: "Pendiente" },
  ],
  mx: [
    { name: "Certificado_NOM.pdf", status: "Pendiente" },
    { name: "Etiqueta_NOM-024.pdf", status: "Pendiente" },
    { name: "Garantia_PROFECO.pdf", status: "Verificado", date: "02/09/2026" },
  ],
};

export const DEMO_CONTEXT = {
  logisticsModel: "Envío directo",
  logisticsDetail: "(dropshipping)",
  channel: "Web propia",
};

/** Traducción de los textos (en inglés) del dataset regulatorio simulado del backend. */
const TRANSLATIONS: Record<string, string> = {
  "battery shipping restrictions for lithium cells": "Restricciones de transporte para baterías de litio",
  "WEEE take-back obligation for electronic waste": "Obligación de recogida de residuos electrónicos (WEEE)",
  "import permit required for wireless transmitters": "Permiso de importación para transmisores inalámbricos",
  "CPSIA lead content limits apply if marketed for children": "Límites de plomo CPSIA si se vende para niños",
  "restricted substances (e.g. certain phthalates) in synthetic leather/PVC":
    "Sustancias restringidas (ftalatos) en cuero sintético o PVC",
  "updated FCC labeling requirement for wireless devices": "Nuevo requisito de etiquetado FCC para dispositivos inalámbricos",
  "EU RoHS scope update for wireless accessories": "Ampliación del alcance de RoHS a accesorios inalámbricos",
  "REACH restriction added for certain phthalates in accessories": "Nueva restricción REACH de ftalatos en accesorios",
};

export function translateLegal(text: string): string {
  const clean = text.replace(/^simulated:\s*/i, "");
  return TRANSLATIONS[clean] ?? clean.charAt(0).toUpperCase() + clean.slice(1);
}
